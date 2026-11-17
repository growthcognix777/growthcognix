"""Phase 4 API: buyer profiles, research areas, discovery campaigns, prospects, verification, scoring,
assignment, export, CRM hand-off, suppression and trade insights.

Tenant comes from the verified token; every row is loaded through scoped()/get_owned(). Buyer profiles are
Phase 2 personas (create/edit/review them through /intelligence/findings/persona); this router adds the AI
generator for the Phase 4 profile fields.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select

from app.core.config import get_settings
from app.deps import ROLE_RANK, Ctx, get_ctx
from app.models import (BuyerPersona, BusinessContact, Client, DiscoveryCampaign, DiscoveryTarget, EvidenceSource, GeographicArea,
                        LeadAssignment, LeadScore, LeadVerification, Product, ProspectCompany, ProspectProductFit, SuppressionEntry,
                        TradeMarketInsight, User)
from app.models.leads import BUYER_TYPES, VERIFICATION_ORDER
from app.services.activity import log
from app.services.ai.providers import ProviderNotConfigured, get_provider
from app.services.intelligence.common import StageError
from app.services.leads import buyer_profiles, comtrade, discovery, geo, providers, scoring, site_verifier
from app.services.leads.providers import ProviderFailure
from app.services.tenancy import get_owned, scoped
from app.services.web.competitor_discovery import clean_website
from app.services.web.crawler_service import normalize

router = APIRouter(tags=["buyer discovery & lead intelligence"])
HUMAN_FIELDS = ("company", "website", "industry", "product_relevance", "contact")
FIELD_STATUS = {"company": "company_verified", "website": "website_verified", "industry": "industry_verified",
                "product_relevance": "product_relevance_verified", "contact": "contact_verified"}
EXPORT_COLUMNS = ["name", "website", "domain", "buyer_type", "industry", "company_category", "country", "state", "district", "city",
                  "industrial_area", "verification_status", "score_total", "score_class", "confidence", "qualification_reason",
                  "role_emails", "phones", "assigned_to", "evidence_urls", "last_verified_at"]


def _need(ctx: Ctx, role: str) -> None:
    if ROLE_RANK[ctx.user.role] < ROLE_RANK[role]:
        raise HTTPException(403, f"Requires {role} role or higher")


def _now():
    return datetime.now(timezone.utc)


def _client(ctx: Ctx, client_id: str) -> Client:
    return get_owned(ctx, Client, client_id, "Client")


def _enqueue(c: DiscoveryCampaign, background: BackgroundTasks, ctx: Ctx) -> None:
    if get_settings().analysis_inline:
        background.add_task(discovery.run_campaign, c.id)
        return
    try:
        from app.worker import queue
        queue().enqueue(discovery.run_campaign, c.id, job_timeout=6 * 3600)
    except Exception as e:  # noqa: BLE001
        c.status, c.error = "failed", f"Job queue unavailable ({type(e).__name__}). Start Redis and the worker, then retry."
        ctx.db.commit()


# ------------------------------------------------------------------ serializers
def campaign_out(c: DiscoveryCampaign) -> dict:
    return {k: getattr(c, k) for k in ("id", "client_id", "name", "status", "product_ids", "persona_ids", "geography_ids", "buyer_types",
                                       "sources", "config", "progress", "stage", "counts", "attempts", "error", "started_at",
                                       "completed_at", "created_at")}


def geo_out(g: GeographicArea) -> dict:
    return {k: getattr(g, k) for k in ("id", "client_id", "level", "name", "code", "parent_id", "country_code", "path", "notes",
                                       "source_url", "created_at")}


def prospect_out(p: ProspectCompany) -> dict:
    return {k: getattr(p, k) for k in ("id", "client_id", "name", "legal_name", "website", "domain", "description", "industry",
                                       "sub_industry", "company_category", "buyer_type", "country", "state", "district", "city",
                                       "industrial_area", "searched_area", "observed_locations", "qualification_reason",
                                       "verification_status", "verified_fields", "providers", "origin", "last_verified_at",
                                       "site_checked_at", "site_status", "score_total", "score_class", "confidence", "crm_status",
                                       "crm_handoff_at", "assigned_to", "first_campaign_id", "created_at", "updated_at")}


def ev_out(e: EvidenceSource) -> dict:
    return {k: getattr(e, k) for k in ("id", "source_type", "source_ref", "source_url", "excerpt", "quote_matched", "field", "provider",
                                       "observed_at", "created_at")}


def contact_out(c: BusinessContact) -> dict:
    return {k: getattr(c, k) for k in ("id", "kind", "value", "person_name", "role", "source_url", "observed_at", "origin", "verified", "purpose")}


def insight_out(i: TradeMarketInsight) -> dict:
    return {k: getattr(i, k) for k in ("id", "client_id", "product_id", "kind", "hs_code", "reporter", "partner", "flow", "period", "value_usd",
                                       "quantity", "quantity_unit", "title", "detail", "source", "source_url", "retrieved_at", "created_at")}


# ------------------------------------------------------------------ reference
@router.get("/api/v1/leads/providers")
def provider_status(ctx: Ctx = Depends(get_ctx)):
    return {"providers": providers.status(ctx.db, ctx.tenant_id), "weights": scoring.DEFAULT_WEIGHTS,
            "classes": [{"min": t, "class": c} for t, c in scoring.CLASSES], "verification_order": VERIFICATION_ORDER,
            "buyer_types": BUYER_TYPES}


@router.get("/api/v1/leads/geo/reference")
def geo_reference(ctx: Ctx = Depends(get_ctx)):
    return geo.reference()


# ------------------------------------------------------------------ buyer profiles
class ProfileGen(BaseModel):
    product_ids: list[str] = Field(default_factory=list, max_length=50)
    buyer_types: list[Literal["end_user", "distributor", "importer", "dealer", "oem", "institutional", "project"]] = Field(default_factory=list)
    geography: list[str] = Field(default_factory=list, max_length=20)


@router.get("/api/v1/clients/{client_id}/leads/buyer-profiles")
def list_profiles(client_id: str, ctx: Ctx = Depends(get_ctx)):
    _client(ctx, client_id)
    from app.routers.intelligence import _serialize
    rows = ctx.db.scalars(scoped(ctx, BuyerPersona).where(BuyerPersona.client_id == client_id, BuyerPersona.verification_status != "rejected")
                          .order_by(BuyerPersona.created_at)).all()
    return _serialize(ctx, "persona", list(rows))


@router.post("/api/v1/clients/{client_id}/leads/buyer-profiles/generate", status_code=201)
def generate_profiles(client_id: str, body: ProfileGen, ctx: Ctx = Depends(get_ctx)):
    _need(ctx, "manager")
    client = _client(ctx, client_id)
    try:
        get_provider("analysis")
    except ProviderNotConfigured as e:
        raise HTTPException(409, str(e))
    try:
        res = buyer_profiles.generate(ctx.db, ctx.tenant_id, client, ctx.user.id, body.product_ids or None, body.buyer_types or None,
                                      body.geography or None)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except StageError as e:
        raise HTTPException(502, f"The AI provider failed: {e}"[:500])
    log(ctx, "leads.profiles_generated", "client", client.id, f"Generated {res['created']} buyer profile hypotheses", client_id=client.id)
    ctx.db.commit()
    return res


# ------------------------------------------------------------------ geographies
class GeoIn(BaseModel):
    level: Literal["global", "country", "state", "district", "city", "industrial_area"]
    name: str = Field(min_length=2, max_length=200)
    parent_id: str | None = None
    code: str | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=2000)
    source_url: str | None = Field(default=None, max_length=500)


@router.get("/api/v1/clients/{client_id}/leads/geographies")
def list_geos(client_id: str, ctx: Ctx = Depends(get_ctx)):
    _client(ctx, client_id)
    rows = ctx.db.scalars(scoped(ctx, GeographicArea).where(GeographicArea.client_id == client_id).order_by(GeographicArea.created_at)).all()
    return [geo_out(g) for g in rows]


@router.post("/api/v1/clients/{client_id}/leads/geographies", status_code=201)
def add_geo(client_id: str, body: GeoIn, ctx: Ctx = Depends(get_ctx)):
    _client(ctx, client_id)
    name = " ".join(body.name.split())
    parent = None
    if body.parent_id:
        parent = get_owned(ctx, GeographicArea, body.parent_id, "Parent area")
        if parent.client_id != client_id:
            raise HTTPException(400, "Parent area belongs to another client")
        if parent.level not in geo.LEVEL_PARENT.get(body.level, ()):
            raise HTTPException(422, f"A {body.level} cannot sit under a {parent.level}")
    elif body.level not in ("global", "country"):
        raise HTTPException(422, f"A {body.level} needs a parent area")
    code = (body.code or "").strip().upper() or None
    cc = None
    if body.level == "country":
        ref = next((x for x in geo.COUNTRIES if x["name"].lower() == name.lower() or x["code"] == code), None)
        if ref:
            name, code = ref["name"], ref["code"]
        cc = code if code and len(code) == 2 else None
    else:
        cc = parent.country_code if parent else None
    if body.level == "state" and parent and parent.country_code == "IN" and name not in geo.INDIA_STATES + geo.INDIA_UTS:
        raise HTTPException(422, "Not an Indian state or union territory name (check spelling)")
    src = None
    if body.source_url:
        try:
            src = clean_website(body.source_url)
        except ValueError as e:
            raise HTTPException(422, str(e))
    path = (list(parent.path) if parent else []) + ([] if body.level == "global" else [name])
    dup = ctx.db.scalar(scoped(ctx, GeographicArea).where(GeographicArea.client_id == client_id, GeographicArea.level == body.level,
                                                          GeographicArea.parent_id == (parent.id if parent else None),
                                                          func.lower(GeographicArea.name) == name.lower()))
    if dup:
        raise HTTPException(409, f"{name} is already saved")
    g = GeographicArea(tenant_id=ctx.tenant_id, client_id=client_id, level=body.level, name=name, code=code, country_code=cc,
                       parent_id=parent.id if parent else None, path=path, notes=body.notes, source_url=src, created_by=ctx.user.id)
    ctx.db.add(g)
    ctx.db.commit()
    return geo_out(g)


@router.delete("/api/v1/leads/geographies/{geo_id}", status_code=204)
def delete_geo(geo_id: str, ctx: Ctx = Depends(get_ctx)):
    g = get_owned(ctx, GeographicArea, geo_id, "Area")
    ctx.db.delete(g)
    ctx.db.commit()


# ------------------------------------------------------------------ campaigns
class CampaignIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    persona_ids: list[str] = Field(min_length=1, max_length=30)
    geography_ids: list[str] = Field(default_factory=list, max_length=50)
    sources: list[str] = Field(min_length=1, max_length=5)
    directory_urls: list[str] = Field(default_factory=list, max_length=20)
    results_per_query: int = Field(default=10, ge=1, le=20)
    max_companies: int = Field(default=200, ge=1, le=1000)
    weights: dict[str, int] | None = None

    @field_validator("sources")
    @classmethod
    def _src(cls, v):
        bad = [s for s in v if s not in providers.ALL]
        if bad:
            raise ValueError(f"Unknown sources: {', '.join(bad)}. Use {', '.join(providers.ALL)}")
        return list(dict.fromkeys(v))


@router.get("/api/v1/clients/{client_id}/leads/campaigns")
def list_campaigns(client_id: str, ctx: Ctx = Depends(get_ctx)):
    _client(ctx, client_id)
    rows = ctx.db.scalars(scoped(ctx, DiscoveryCampaign).where(DiscoveryCampaign.client_id == client_id)
                          .order_by(DiscoveryCampaign.created_at.desc())).all()
    return [campaign_out(c) for c in rows]


@router.post("/api/v1/clients/{client_id}/leads/campaigns", status_code=201)
def create_campaign(client_id: str, body: CampaignIn, ctx: Ctx = Depends(get_ctx)):
    _need(ctx, "manager")
    _client(ctx, client_id)
    personas = ctx.db.scalars(scoped(ctx, BuyerPersona).where(BuyerPersona.client_id == client_id, BuyerPersona.id.in_(body.persona_ids))).all()
    if len(personas) != len(set(body.persona_ids)):
        raise HTTPException(400, "Some buyer profiles were not found for this client")
    unapproved = [p.name for p in personas if not (p.approved or p.origin == "user") or p.verification_status == "rejected"]
    if unapproved:
        raise HTTPException(400, "Approve these buyer profiles before searching for them: " + ", ".join(unapproved[:5]))
    geos = ctx.db.scalars(scoped(ctx, GeographicArea).where(GeographicArea.client_id == client_id, GeographicArea.id.in_(body.geography_ids))).all()
    if len(geos) != len(set(body.geography_ids)):
        raise HTTPException(400, "Some research areas were not found for this client")
    dirs = []
    for u in body.directory_urls:
        try:
            dirs.append(clean_website(u))
        except ValueError as e:
            raise HTTPException(422, f"Directory URL: {e}")
    if "directory" in body.sources and not dirs:
        raise HTTPException(422, "Add at least one directory URL for the directory source")
    if body.weights:
        try:
            scoring.normalise_weights(body.weights)
        except ValueError as e:
            raise HTTPException(422, str(e))
    product_ids = sorted({p.product_id for p in personas if p.product_id})
    c = DiscoveryCampaign(tenant_id=ctx.tenant_id, client_id=client_id, name=body.name.strip(), status="draft", product_ids=product_ids,
                          persona_ids=list(dict.fromkeys(body.persona_ids)), geography_ids=list(dict.fromkeys(body.geography_ids)),
                          buyer_types=sorted({p.buyer_type for p in personas if p.buyer_type}), sources=body.sources,
                          config={"directory_urls": dirs, "results_per_query": body.results_per_query, "max_companies": body.max_companies,
                                  "weights": body.weights}, created_by=ctx.user.id)
    ctx.db.add(c)
    ctx.db.flush()
    n = discovery.plan_targets(ctx.db, c)
    c.counts = {"planned_targets": n}
    log(ctx, "leads.campaign_created", "discovery_campaign", c.id, f"Discovery campaign '{c.name}' planned ({n} searches)", client_id=client_id)
    ctx.db.commit()
    return campaign_out(c)


def _campaign(ctx: Ctx, cid: str) -> DiscoveryCampaign:
    return get_owned(ctx, DiscoveryCampaign, cid, "Campaign")


@router.get("/api/v1/leads/campaigns/{campaign_id}")
def get_campaign(campaign_id: str, ctx: Ctx = Depends(get_ctx)):
    c = _campaign(ctx, campaign_id)
    by = dict(ctx.db.execute(select(DiscoveryTarget.status, func.count()).where(DiscoveryTarget.campaign_id == c.id)
                             .group_by(DiscoveryTarget.status)).all())
    return {**campaign_out(c), "targets": by}


@router.get("/api/v1/leads/campaigns/{campaign_id}/targets")
def campaign_targets(campaign_id: str, ctx: Ctx = Depends(get_ctx), status: str | None = None):
    c = _campaign(ctx, campaign_id)
    q = select(DiscoveryTarget).where(DiscoveryTarget.campaign_id == c.id)
    if status:
        q = q.where(DiscoveryTarget.status == status)
    return [{k: getattr(t, k) for k in ("id", "provider", "query", "status", "results_count", "new_prospects", "attempts", "error",
                                         "executed_at", "persona_id", "geography_id")}
            for t in ctx.db.scalars(q.order_by(DiscoveryTarget.created_at).limit(1000)).all()]


@router.post("/api/v1/leads/campaigns/{campaign_id}/start")
def start_campaign(campaign_id: str, background: BackgroundTasks, ctx: Ctx = Depends(get_ctx)):
    """Start or resume. Done targets are skipped; failed ones are retried."""
    _need(ctx, "manager")
    c = _campaign(ctx, campaign_id)
    if c.status in ("queued", "running"):
        raise HTTPException(409, "Campaign is already running")
    if c.status in ("cancelled", "completed") and c.status == "cancelled":
        raise HTTPException(409, "A cancelled campaign cannot be restarted; create a new one")
    usable = [s for s in c.sources if providers.ALL[s].configured()]
    if not usable:
        raise HTTPException(409, "None of this campaign's sources is configured on the server. Set SEARXNG_URL (free, self-hosted), "
                                 "GOOGLE_PSE_KEY + GOOGLE_PSE_CX, or BRAVE_API_KEY, or use the directory source.")
    if c.status == "completed":
        ctx.db.query(DiscoveryTarget).filter(DiscoveryTarget.campaign_id == c.id, DiscoveryTarget.status == "failed").update({"status": "pending"})
    c.status, c.error, c.completed_at = "queued", None, None
    log(ctx, "leads.campaign_started", "discovery_campaign", c.id, f"Discovery '{c.name}' started", client_id=c.client_id)
    ctx.db.commit()
    _enqueue(c, background, ctx)
    return campaign_out(c)


@router.post("/api/v1/leads/campaigns/{campaign_id}/pause")
def pause_campaign(campaign_id: str, ctx: Ctx = Depends(get_ctx)):
    c = _campaign(ctx, campaign_id)
    if c.status not in ("queued", "running"):
        raise HTTPException(409, f"Campaign is {c.status}")
    c.status = "paused"
    ctx.db.commit()
    return campaign_out(c)


@router.post("/api/v1/leads/campaigns/{campaign_id}/cancel")
def cancel_campaign(campaign_id: str, ctx: Ctx = Depends(get_ctx)):
    c = _campaign(ctx, campaign_id)
    if c.status in ("completed", "cancelled"):
        raise HTTPException(409, f"Campaign is {c.status}")
    c.status, c.completed_at = "cancelled", _now()
    log(ctx, "leads.campaign_cancelled", "discovery_campaign", c.id, f"Discovery '{c.name}' cancelled", client_id=c.client_id)
    ctx.db.commit()
    return campaign_out(c)


# ------------------------------------------------------------------ prospects
class ProspectIn(BaseModel):
    name: str = Field(min_length=2, max_length=300)
    website: str | None = Field(default=None, max_length=500)
    source_url: str = Field(min_length=8, max_length=500, description="Where the team found this company")
    buyer_type: Literal["end_user", "distributor", "importer", "dealer", "oem", "institutional", "project"] | None = None
    industry: str | None = Field(default=None, max_length=200)
    company_category: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    district: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    industrial_area: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=2000)


class ProspectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=300)
    legal_name: str | None = Field(default=None, max_length=300)
    buyer_type: Literal["end_user", "distributor", "importer", "dealer", "oem", "institutional", "project"] | None = None
    industry: str | None = Field(default=None, max_length=200)
    sub_industry: str | None = Field(default=None, max_length=200)
    company_category: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    district: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    industrial_area: str | None = Field(default=None, max_length=200)
    qualification_reason: str | None = Field(default=None, max_length=2000)


def _src(url: str | None, required: bool = False) -> str | None:
    if not url:
        if required:
            raise HTTPException(422, "A source URL is required")
        return None
    u = url.strip()
    n = normalize(u if "://" in u else "https://" + u)
    if not n:
        raise HTTPException(422, "Source URL must be a valid http(s) link")
    return n[:500]


@router.get("/api/v1/clients/{client_id}/leads/prospects")
def list_prospects(client_id: str, ctx: Ctx = Depends(get_ctx), q: str | None = None, country: str | None = None,
                   state: str | None = None, district: str | None = None, city: str | None = None, industry: str | None = None,
                   product_id: str | None = None, buyer_type: str | None = None, score_class: str | None = None,
                   min_score: int | None = Query(None, ge=0, le=100), verification: str | None = None, source: str | None = None,
                   campaign_id: str | None = None, assigned_to: str | None = None, crm_status: str | None = None,
                   include_rejected: bool = False, sort: Literal["score", "recent", "name"] = "score",
                   limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    _client(ctx, client_id)
    qq = scoped(ctx, ProspectCompany).where(ProspectCompany.client_id == client_id)
    if not include_rejected and verification != "rejected":
        qq = qq.where(ProspectCompany.verification_status != "rejected")
    if q:
        like = f"%{q.strip()[:100]}%"
        qq = qq.where(or_(ProspectCompany.name.ilike(like), ProspectCompany.domain.ilike(like), ProspectCompany.description.ilike(like)))
    for col, val in ((ProspectCompany.buyer_type, buyer_type), (ProspectCompany.score_class, score_class),
                     (ProspectCompany.verification_status, verification), (ProspectCompany.first_campaign_id, campaign_id),
                     (ProspectCompany.assigned_to, assigned_to), (ProspectCompany.crm_status, crm_status)):
        if val:
            qq = qq.where(col == val)
    if industry:
        qq = qq.where(or_(ProspectCompany.industry.ilike(f"%{industry}%"), ProspectCompany.sub_industry.ilike(f"%{industry}%")))
    if min_score is not None:
        qq = qq.where(ProspectCompany.score_total >= min_score)
    if product_id:
        qq = qq.where(ProspectCompany.id.in_(select(ProspectProductFit.prospect_id).where(ProspectProductFit.product_id == product_id)))
    order = {"score": (ProspectCompany.score_total.desc().nulls_last(), ProspectCompany.created_at.desc()),
             "recent": (ProspectCompany.created_at.desc(),), "name": (ProspectCompany.name,)}[sort]
    rows = ctx.db.scalars(qq.order_by(*order).limit(5000)).all()

    def geo_ok(p: ProspectCompany) -> bool:
        for want, field, idx in ((country, p.country, 0), (state, p.state, 1), (district, p.district, 2), (city, p.city, 3)):
            if not want:
                continue
            w = want.lower()
            if (field or "").lower() == w:
                continue
            if any(len(a) > idx and a[idx].lower() == w for a in p.searched_area or []):
                continue
            if any(x.lower() == w for x in p.observed_locations or []):
                continue
            return False
        return True

    rows = [p for p in rows if geo_ok(p) and (not source or source in (p.providers or []))]
    return {"total": len(rows), "items": [prospect_out(p) for p in rows[offset: offset + limit]]}


@router.post("/api/v1/clients/{client_id}/leads/prospects", status_code=201)
def add_prospect(client_id: str, body: ProspectIn, ctx: Ctx = Depends(get_ctx)):
    _client(ctx, client_id)
    src = _src(body.source_url, required=True)
    site = _src(body.website) if body.website else None
    d = discovery.norm_domain(site) if site else None
    if d and providers.is_listing_site(d):
        raise HTTPException(422, "That is a listing or social site, not the company's own website")
    if d and discovery.suppressed(ctx.db, ctx.tenant_id, "domain", d):
        raise HTTPException(409, "This domain is on the do-not-contact list")
    if d and ctx.db.scalar(scoped(ctx, ProspectCompany).where(ProspectCompany.client_id == client_id, ProspectCompany.domain == d)):
        raise HTTPException(409, "A prospect with this domain already exists")
    data = body.model_dump(exclude={"website", "source_url", "note"})
    p = ProspectCompany(tenant_id=ctx.tenant_id, client_id=client_id, website=site, domain=d, origin="manual",
                        verification_status="discovered", providers=["manual"], created_by=ctx.user.id,
                        qualification_reason=body.note, **data)
    ctx.db.add(p)
    ctx.db.flush()
    discovery._evidence(ctx.db, p, field="discovery", source_type="user", url=src, excerpt=body.note or "Added by the team", provider="manual")
    discovery.rescore(ctx.db, p)
    log(ctx, "leads.prospect_added", "prospect", p.id, f"Prospect {p.name} added manually", client_id=client_id)
    ctx.db.commit()
    return prospect_out(p)


def _prospect(ctx: Ctx, pid: str) -> ProspectCompany:
    return get_owned(ctx, ProspectCompany, pid, "Prospect")


@router.get("/api/v1/leads/prospects/{prospect_id}")
def prospect_detail(prospect_id: str, ctx: Ctx = Depends(get_ctx)):
    p = _prospect(ctx, prospect_id)
    db = ctx.db
    ev = db.scalars(select(EvidenceSource).where(EvidenceSource.tenant_id == ctx.tenant_id, EvidenceSource.finding_type == "prospect",
                                                 EvidenceSource.finding_id == p.id).order_by(EvidenceSource.created_at)).all()
    score = db.scalar(select(LeadScore).where(LeadScore.prospect_id == p.id).order_by(LeadScore.created_at.desc()).limit(1))
    fits = db.scalars(select(ProspectProductFit).where(ProspectProductFit.prospect_id == p.id)).all()
    ver = db.scalars(select(LeadVerification).where(LeadVerification.prospect_id == p.id).order_by(LeadVerification.created_at.desc())).all()
    asg = db.scalars(select(LeadAssignment).where(LeadAssignment.prospect_id == p.id).order_by(LeadAssignment.created_at.desc())).all()
    return {**prospect_out(p), "signals": p.signals,
            "evidence": [ev_out(e) for e in ev],
            "contacts": [contact_out(c) for c in db.scalars(select(BusinessContact).where(BusinessContact.prospect_id == p.id)).all()],
            "fits": [{k: getattr(f, k) for k in ("id", "product_id", "persona_id", "application", "relation", "reason", "matched_terms",
                                                  "origin", "verified")} for f in fits],
            "score": {k: getattr(score, k) for k in ("total", "score_class", "confidence", "components", "weights", "explanation",
                                                      "version", "created_at")} if score else None,
            "verifications": [{k: getattr(v, k) for k in ("id", "field", "decision", "note", "source_url", "user_id", "created_at")} for v in ver],
            "assignments": [{k: getattr(a, k) for k in ("id", "user_id", "assigned_by", "status", "note", "created_at")} for a in asg]}


@router.patch("/api/v1/leads/prospects/{prospect_id}")
def edit_prospect(prospect_id: str, body: ProspectPatch, ctx: Ctx = Depends(get_ctx)):
    p = _prospect(ctx, prospect_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v.strip() if isinstance(v, str) else v)
    ctx.db.commit()
    return prospect_out(p)


@router.delete("/api/v1/leads/prospects/{prospect_id}", status_code=204)
def delete_prospect(prospect_id: str, ctx: Ctx = Depends(get_ctx)):
    _need(ctx, "manager")
    p = _prospect(ctx, prospect_id)
    ctx.db.query(EvidenceSource).filter(EvidenceSource.finding_type == "prospect", EvidenceSource.finding_id == p.id).delete()
    log(ctx, "leads.prospect_deleted", "prospect", p.id, f"Prospect {p.name} deleted", client_id=p.client_id)
    ctx.db.delete(p)
    ctx.db.commit()


class VerifyIn(BaseModel):
    field: Literal["company", "website", "industry", "product_relevance", "contact", "status"]
    decision: Literal["verified", "rejected", "needs_review"]
    note: str | None = Field(default=None, max_length=2000)
    source_url: str | None = Field(default=None, max_length=500)


def _recompute_status(p: ProspectCompany) -> None:
    if p.verification_status in ("rejected", "needs_review"):
        return
    best = "discovered"
    for f, st in FIELD_STATUS.items():
        if f in (p.verified_fields or {}) and VERIFICATION_ORDER.index(st) > VERIFICATION_ORDER.index(best):
            best = st
    p.verification_status = best


@router.post("/api/v1/leads/prospects/{prospect_id}/verify")
def verify_prospect(prospect_id: str, body: VerifyIn, ctx: Ctx = Depends(get_ctx)):
    p = _prospect(ctx, prospect_id)
    src = _src(body.source_url)
    if body.decision == "verified" and body.field != "status" and not (src or body.note):
        raise HTTPException(422, "Say how you verified it: add a source URL or a note")
    vf = dict(p.verified_fields or {})
    if body.field == "status":
        if body.decision == "verified":
            raise HTTPException(422, "Verify individual fields; status accepts rejected or needs_review")
        p.verification_status = body.decision
        if body.decision == "rejected" and p.crm_status == "approved":
            p.crm_status = "none"
    elif body.decision == "verified":
        vf[body.field] = {"by": ctx.user.id, "at": _now().isoformat(), "note": body.note, "source_url": src}
        p.verified_fields = vf
        if p.verification_status == "needs_review":
            p.verification_status = "discovered"
        _recompute_status(p)
        p.last_verified_at = _now()
        if src:
            discovery._evidence(ctx.db, p, field=body.field, source_type="user", url=src, excerpt=body.note or f"{body.field} verified",
                                provider="team")
    else:
        vf.pop(body.field, None)
        p.verified_fields = vf
        if body.decision == "needs_review":
            p.verification_status = "needs_review"
        else:
            _recompute_status(p)
    ctx.db.add(LeadVerification(tenant_id=ctx.tenant_id, client_id=p.client_id, prospect_id=p.id, field=body.field, decision=body.decision,
                                note=body.note, source_url=src, user_id=ctx.user.id))
    discovery.rescore(ctx.db, p)
    log(ctx, "leads.verified", "prospect", p.id, f"{p.name}: {body.field} {body.decision}", client_id=p.client_id)
    ctx.db.commit()
    return prospect_out(p)


@router.post("/api/v1/leads/prospects/{prospect_id}/reopen")
def reopen_prospect(prospect_id: str, ctx: Ctx = Depends(get_ctx)):
    p = _prospect(ctx, prospect_id)
    p.verification_status = "discovered"
    _recompute_status(p)
    discovery.rescore(ctx.db, p)
    ctx.db.commit()
    return prospect_out(p)


class EvidenceIn(BaseModel):
    field: Literal["fit", "need", "intent", "capacity", "company", "industry", "location", "other"]
    source_url: str = Field(min_length=8, max_length=500)
    excerpt: str = Field(min_length=3, max_length=1000)


@router.post("/api/v1/leads/prospects/{prospect_id}/evidence", status_code=201)
def add_evidence(prospect_id: str, body: EvidenceIn, ctx: Ctx = Depends(get_ctx)):
    p = _prospect(ctx, prospect_id)
    discovery._evidence(ctx.db, p, field=body.field, source_type="user", url=_src(body.source_url, True), excerpt=body.excerpt, provider="team")
    discovery.rescore(ctx.db, p)
    ctx.db.commit()
    return prospect_detail(prospect_id, ctx)


class ContactIn(BaseModel):
    kind: Literal["role_email", "phone", "person"]
    value: str | None = Field(default=None, max_length=300)
    person_name: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, max_length=200)
    source_url: str = Field(min_length=8, max_length=500, description="Public page where this business contact is published")
    purpose: str | None = Field(default=None, max_length=200)


@router.post("/api/v1/leads/prospects/{prospect_id}/contacts", status_code=201)
def add_contact(prospect_id: str, body: ContactIn, ctx: Ctx = Depends(get_ctx)):
    p = _prospect(ctx, prospect_id)
    src = _src(body.source_url, True)
    v = (body.value or "").strip() or None
    if body.kind == "role_email":
        if not v or not re.fullmatch(r"[\w.+-]+@[\w-]+\.[\w.-]+", v):
            raise HTTPException(422, "Enter a valid email")
        v = v.lower()
    if body.kind == "phone" and (not v or len(re.sub(r"\D", "", v)) < 8):
        raise HTTPException(422, "Enter a valid phone number")
    if body.kind == "person" and not (body.person_name and body.role):
        raise HTTPException(422, "A business contact needs a name and a role as published on the source page")
    kind = "email" if v and "@" in v else "phone"
    if v and discovery.suppressed(ctx.db, ctx.tenant_id, kind, v):
        raise HTTPException(409, "This contact is on the do-not-contact list")
    client = ctx.db.get(Client, p.client_id)
    c = BusinessContact(tenant_id=ctx.tenant_id, client_id=p.client_id, prospect_id=p.id, kind=body.kind, value=v,
                        person_name=body.person_name, role=body.role, source_url=src, observed_at=_now(), origin="user",
                        purpose=body.purpose or f"B2B prospect research for {client.company_name}")
    ctx.db.add(c)
    discovery.rescore(ctx.db, p)
    ctx.db.commit()
    return contact_out(c)


@router.post("/api/v1/leads/contacts/{contact_id}/verify")
def verify_contact(contact_id: str, ctx: Ctx = Depends(get_ctx), verified: bool = True):
    c = get_owned(ctx, BusinessContact, contact_id, "Contact")
    c.verified = verified
    p = ctx.db.get(ProspectCompany, c.prospect_id)
    discovery.rescore(ctx.db, p)
    ctx.db.commit()
    return contact_out(c)


@router.delete("/api/v1/leads/contacts/{contact_id}", status_code=204)
def delete_contact(contact_id: str, ctx: Ctx = Depends(get_ctx)):
    c = get_owned(ctx, BusinessContact, contact_id, "Contact")
    p = ctx.db.get(ProspectCompany, c.prospect_id)
    ctx.db.delete(c)
    ctx.db.flush()
    discovery.rescore(ctx.db, p)
    ctx.db.commit()


@router.post("/api/v1/leads/prospects/{prospect_id}/check-site")
def check_site(prospect_id: str, ctx: Ctx = Depends(get_ctx)):
    """Fetch the prospect's own site now (up to DISCOVERY_VERIFY_PAGES pages, robots-aware)."""
    p = _prospect(ctx, prospect_id)
    if not p.website:
        raise HTTPException(400, "This prospect has no website")
    personas = ctx.db.scalars(scoped(ctx, BuyerPersona).where(BuyerPersona.client_id == p.client_id, BuyerPersona.verification_status != "rejected",
                                                              or_(BuyerPersona.approved.is_(True), BuyerPersona.origin == "user"))).all()
    from app.models import ProductApplication
    apps = ctx.db.scalars(scoped(ctx, ProductApplication).where(ProductApplication.client_id == p.client_id,
                                                                ProductApplication.verification_status != "rejected")).all()
    obs = site_verifier.inspect(p.website, site_verifier.terms_from(list(personas), list(apps)), get_settings().discovery_verify_pages)
    discovery.apply_site(ctx.db, p, obs, list(personas), ctx.user.id)
    discovery.rescore(ctx.db, p)
    ctx.db.commit()
    return prospect_detail(prospect_id, ctx)


class ScoreIn(BaseModel):
    weights: dict[str, int] | None = None
    prospect_ids: list[str] = Field(default_factory=list, max_length=5000)


@router.post("/api/v1/clients/{client_id}/leads/rescore")
def rescore_all(client_id: str, body: ScoreIn, ctx: Ctx = Depends(get_ctx)):
    _need(ctx, "manager")
    _client(ctx, client_id)
    try:
        w = discovery.weights_for(ctx.db, client_id, body.weights)
    except ValueError as e:
        raise HTTPException(422, str(e))
    q = scoped(ctx, ProspectCompany).where(ProspectCompany.client_id == client_id)
    if body.prospect_ids:
        q = q.where(ProspectCompany.id.in_(body.prospect_ids))
    rows = ctx.db.scalars(q).all()
    for p in rows:
        discovery.rescore(ctx.db, p, w)
    ctx.db.commit()
    return {"rescored": len(rows), "weights": w}


@router.get("/api/v1/leads/prospects/{prospect_id}/scores")
def score_history(prospect_id: str, ctx: Ctx = Depends(get_ctx)):
    p = _prospect(ctx, prospect_id)
    rows = ctx.db.scalars(select(LeadScore).where(LeadScore.prospect_id == p.id).order_by(LeadScore.created_at.desc()).limit(50)).all()
    return [{k: getattr(s, k) for k in ("total", "score_class", "confidence", "components", "weights", "explanation", "version", "created_at")}
            for s in rows]


class AssignIn(BaseModel):
    prospect_ids: list[str] = Field(min_length=1, max_length=500)
    user_id: str | None = None
    note: str | None = Field(default=None, max_length=1000)


@router.post("/api/v1/clients/{client_id}/leads/assign")
def assign(client_id: str, body: AssignIn, ctx: Ctx = Depends(get_ctx)):
    _need(ctx, "manager")
    _client(ctx, client_id)
    if body.user_id:
        u = ctx.db.get(User, body.user_id)
        if not u or u.tenant_id != ctx.tenant_id or not u.is_active:
            raise HTTPException(400, "That team member was not found")
    rows = ctx.db.scalars(scoped(ctx, ProspectCompany).where(ProspectCompany.client_id == client_id, ProspectCompany.id.in_(body.prospect_ids))).all()
    for p in rows:
        ctx.db.query(LeadAssignment).filter(LeadAssignment.prospect_id == p.id, LeadAssignment.status == "active").update({"status": "released"})
        p.assigned_to = body.user_id
        if body.user_id:
            ctx.db.add(LeadAssignment(tenant_id=ctx.tenant_id, client_id=client_id, prospect_id=p.id, user_id=body.user_id,
                                      assigned_by=ctx.user.id, note=body.note))
    log(ctx, "leads.assigned", "client", client_id, f"{len(rows)} prospect(s) {'assigned' if body.user_id else 'unassigned'}",
        client_id=client_id, user_id=body.user_id)
    ctx.db.commit()
    return {"updated": len(rows)}


# ------------------------------------------------------------------ approval, export, CRM
def _approvable(p: ProspectCompany) -> str | None:
    if p.verification_status in ("rejected", "needs_review"):
        return f"{p.name} is {p.verification_status.replace('_', ' ')}"
    human = [f for f, v in (p.verified_fields or {}).items() if v.get("by") != "system"]
    if "company" not in human:
        return f"{p.name}: a person must verify the company first"
    return None


class ApproveIn(BaseModel):
    prospect_ids: list[str] = Field(min_length=1, max_length=500)
    approved: bool = True


@router.post("/api/v1/clients/{client_id}/leads/approve")
def approve(client_id: str, body: ApproveIn, ctx: Ctx = Depends(get_ctx)):
    _need(ctx, "manager")
    _client(ctx, client_id)
    rows = ctx.db.scalars(scoped(ctx, ProspectCompany).where(ProspectCompany.client_id == client_id, ProspectCompany.id.in_(body.prospect_ids))).all()
    blocked, ok = [], 0
    for p in rows:
        if body.approved:
            why = _approvable(p)
            if why:
                blocked.append(why)
                continue
            if p.crm_status == "none":
                p.crm_status = "approved"
        elif p.crm_status == "approved":
            p.crm_status = "none"
        ok += 1
    log(ctx, "leads.approved" if body.approved else "leads.unapproved", "client", client_id, f"{ok} prospect(s) updated", client_id=client_id)
    ctx.db.commit()
    return {"updated": ok, "blocked": blocked}


def _export_rows(ctx: Ctx, client_id: str, ids: list[str] | None) -> list[dict]:
    q = scoped(ctx, ProspectCompany).where(ProspectCompany.client_id == client_id, ProspectCompany.crm_status.in_(("approved", "handed_off")))
    if ids:
        q = q.where(ProspectCompany.id.in_(ids))
    out = []
    names = {u.id: u.full_name or u.email for u in ctx.db.scalars(select(User).where(User.tenant_id == ctx.tenant_id)).all()}
    for p in ctx.db.scalars(q.order_by(ProspectCompany.score_total.desc().nulls_last())).all():
        contacts = ctx.db.scalars(select(BusinessContact).where(BusinessContact.prospect_id == p.id)).all()
        emails = [c.value for c in contacts if c.kind == "role_email" and not discovery.suppressed(ctx.db, ctx.tenant_id, "email", c.value)]
        phones = [c.value for c in contacts if c.kind == "phone" and not discovery.suppressed(ctx.db, ctx.tenant_id, "phone", c.value)]
        urls = ctx.db.scalars(select(EvidenceSource.source_url).where(EvidenceSource.finding_type == "prospect", EvidenceSource.finding_id == p.id,
                                                                     EvidenceSource.source_url.is_not(None)).limit(5)).all()
        row = {k: getattr(p, k) for k in EXPORT_COLUMNS if hasattr(p, k)}
        row.update({"role_emails": "; ".join(emails), "phones": "; ".join(phones), "assigned_to": names.get(p.assigned_to, ""),
                    "evidence_urls": " ".join(dict.fromkeys(urls)),
                    "last_verified_at": p.last_verified_at.isoformat() if p.last_verified_at else ""})
        out.append({k: ("" if row.get(k) is None else row[k]) for k in EXPORT_COLUMNS})
    return out


@router.get("/api/v1/clients/{client_id}/leads/export")
def export(client_id: str, ctx: Ctx = Depends(get_ctx), format: Literal["csv", "xlsx"] = "csv", ids: str | None = None):
    """Approved prospects only, without suppressed contacts."""
    _need(ctx, "manager")
    client = _client(ctx, client_id)
    rows = _export_rows(ctx, client_id, [x for x in (ids or "").split(",") if x] or None)
    if not rows:
        raise HTTPException(404, "No approved prospects to export. Verify and approve prospects first.")
    slug = re.sub(r"[^a-z0-9]+", "-", client.company_name.lower()).strip("-")[:40] or "client"
    log(ctx, "leads.exported", "client", client_id, f"Exported {len(rows)} approved prospect(s) as {format.upper()}", client_id=client_id)
    ctx.db.commit()
    if format == "csv":
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: (f"'{v}" if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v) for k, v in r.items()})
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{slug}-prospects.csv"'})
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Approved prospects"
    ws.append(EXPORT_COLUMNS)
    for r in rows:
        ws.append([(f"'{v}" if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v) for v in (r[k] for k in EXPORT_COLUMNS)])
    out = io.BytesIO()
    wb.save(out)
    return Response(out.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{slug}-prospects.xlsx"'})


class HandoffIn(BaseModel):
    prospect_ids: list[str] = Field(min_length=1, max_length=500)


@router.post("/api/v1/clients/{client_id}/leads/crm-handoff")
def crm_handoff(client_id: str, body: HandoffIn, ctx: Ctx = Depends(get_ctx)):
    """Marks approved prospects as handed off to the CRM. The Phase 6 CRM reads handed-off prospects; nothing is
    contacted here."""
    _need(ctx, "manager")
    _client(ctx, client_id)
    rows = ctx.db.scalars(scoped(ctx, ProspectCompany).where(ProspectCompany.client_id == client_id, ProspectCompany.id.in_(body.prospect_ids))).all()
    done, skipped = 0, []
    for p in rows:
        if p.crm_status != "approved":
            skipped.append(f"{p.name}: not approved")
            continue
        p.crm_status, p.crm_handoff_at = "handed_off", _now()
        done += 1
    log(ctx, "leads.crm_handoff", "client", client_id, f"{done} approved prospect(s) handed to CRM", client_id=client_id)
    ctx.db.commit()
    return {"handed_off": done, "skipped": skipped}


# ------------------------------------------------------------------ dashboards
@router.get("/api/v1/clients/{client_id}/leads/summary")
def summary(client_id: str, ctx: Ctx = Depends(get_ctx)):
    _client(ctx, client_id)
    base = scoped(ctx, ProspectCompany).where(ProspectCompany.client_id == client_id).subquery()

    def group(col):
        return {k or "unset": v for k, v in ctx.db.execute(select(getattr(base.c, col), func.count()).group_by(getattr(base.c, col))).all()}

    total = ctx.db.scalar(select(func.count()).select_from(base)) or 0
    camps = ctx.db.scalars(scoped(ctx, DiscoveryCampaign).where(DiscoveryCampaign.client_id == client_id)).all()
    return {"prospects": total, "by_class": group("score_class"), "by_status": group("verification_status"),
            "by_buyer_type": group("buyer_type"), "by_crm": group("crm_status"),
            "assigned": ctx.db.scalar(select(func.count()).select_from(base).where(base.c.assigned_to.is_not(None))) or 0,
            "campaigns": {s: len([c for c in camps if c.status == s]) for s in {c.status for c in camps}},
            "profiles": ctx.db.scalar(select(func.count()).select_from(BuyerPersona).where(BuyerPersona.tenant_id == ctx.tenant_id,
                                      BuyerPersona.client_id == client_id, BuyerPersona.verification_status != "rejected")) or 0,
            "areas": ctx.db.scalar(select(func.count()).select_from(GeographicArea).where(GeographicArea.tenant_id == ctx.tenant_id,
                                   GeographicArea.client_id == client_id)) or 0,
            "avg_score": ctx.db.scalar(select(func.avg(base.c.score_total))) if total else None}


@router.get("/api/v1/clients/{client_id}/leads/verification-queue")
def verification_queue(client_id: str, ctx: Ctx = Depends(get_ctx), limit: int = Query(100, ge=1, le=500)):
    _client(ctx, client_id)
    rows = ctx.db.scalars(scoped(ctx, ProspectCompany).where(
        ProspectCompany.client_id == client_id,
        ProspectCompany.verification_status.in_(("discovered", "website_verified", "needs_review")))
        .order_by((ProspectCompany.verification_status == "needs_review").desc(), ProspectCompany.score_total.desc().nulls_last())
        .limit(limit)).all()
    return [prospect_out(p) for p in rows]


# ------------------------------------------------------------------ suppression
class SuppressIn(BaseModel):
    kind: Literal["domain", "email", "phone"]
    value: str = Field(min_length=3, max_length=300)
    reason: str | None = Field(default=None, max_length=300)


@router.get("/api/v1/leads/suppression")
def list_suppression(ctx: Ctx = Depends(get_ctx)):
    rows = ctx.db.scalars(select(SuppressionEntry).where(SuppressionEntry.tenant_id == ctx.tenant_id).order_by(SuppressionEntry.created_at.desc())).all()
    return [{k: getattr(s, k) for k in ("id", "kind", "value", "reason", "created_at")} for s in rows]


@router.post("/api/v1/leads/suppression", status_code=201)
def add_suppression(body: SuppressIn, ctx: Ctx = Depends(get_ctx)):
    v = body.value.strip().lower()
    if body.kind == "domain":
        v = discovery.norm_domain(v) or ""
        if not v:
            raise HTTPException(422, "Enter a domain like example.com")
    elif body.kind == "phone":
        v = re.sub(r"\D", "", v)
        if len(v) < 8:
            raise HTTPException(422, "Enter a valid phone number")
    elif not re.fullmatch(r"[\w.+-]+@[\w-]+\.[\w.-]+", v):
        raise HTTPException(422, "Enter a valid email")
    if ctx.db.scalar(select(SuppressionEntry).where(SuppressionEntry.tenant_id == ctx.tenant_id, SuppressionEntry.kind == body.kind,
                                                    SuppressionEntry.value == v)):
        raise HTTPException(409, "Already on the list")
    s = SuppressionEntry(tenant_id=ctx.tenant_id, kind=body.kind, value=v, reason=body.reason, created_by=ctx.user.id)
    ctx.db.add(s)
    log(ctx, "leads.suppressed", "suppression", None, f"Added {body.kind} to do-not-contact list")
    ctx.db.commit()
    return {k: getattr(s, k) for k in ("id", "kind", "value", "reason", "created_at")}


@router.delete("/api/v1/leads/suppression/{entry_id}", status_code=204)
def delete_suppression(entry_id: str, ctx: Ctx = Depends(get_ctx)):
    _need(ctx, "manager")
    s = ctx.db.scalar(select(SuppressionEntry).where(SuppressionEntry.tenant_id == ctx.tenant_id, SuppressionEntry.id == entry_id))
    if not s:
        raise HTTPException(404, "Entry not found")
    ctx.db.delete(s)
    ctx.db.commit()


# ------------------------------------------------------------------ market insights
class ComtradeIn(BaseModel):
    hs_code: str = Field(min_length=2, max_length=6)
    reporter: str = Field(min_length=2, max_length=60, description="Country that reports the trade (name, ISO code or Comtrade code)")
    period: str = Field(min_length=4, max_length=4)
    flow: Literal["M", "X"] = "M"
    partner: str | None = Field(default=None, max_length=60)
    product_id: str | None = None


class InsightIn(BaseModel):
    kind: Literal["current_demand", "tariff", "certification", "regulation", "logistics", "trade_agreement", "hs_code"]
    title: str = Field(min_length=3, max_length=300)
    detail: str | None = Field(default=None, max_length=4000)
    source_url: str = Field(min_length=8, max_length=500)
    product_id: str | None = None
    hs_code: str | None = Field(default=None, max_length=12)
    reporter: str | None = Field(default=None, max_length=100)


def _product(ctx: Ctx, client_id: str, pid: str | None) -> str | None:
    if not pid:
        return None
    p = get_owned(ctx, Product, pid, "Product")
    if p.client_id != client_id:
        raise HTTPException(400, "Product belongs to another client")
    return p.id


@router.get("/api/v1/clients/{client_id}/leads/market-insights")
def list_insights(client_id: str, ctx: Ctx = Depends(get_ctx), kind: str | None = None):
    _client(ctx, client_id)
    q = scoped(ctx, TradeMarketInsight).where(TradeMarketInsight.client_id == client_id)
    if kind:
        q = q.where(TradeMarketInsight.kind == kind)
    return [insight_out(i) for i in ctx.db.scalars(q.order_by(TradeMarketInsight.created_at.desc()).limit(500)).all()]


@router.post("/api/v1/clients/{client_id}/leads/market-insights/comtrade", status_code=201)
def fetch_comtrade(client_id: str, body: ComtradeIn, ctx: Ctx = Depends(get_ctx)):
    _client(ctx, client_id)
    pid = _product(ctx, client_id, body.product_id)
    try:
        rows = comtrade.save(ctx.db, ctx.tenant_id, client_id, ctx.user.id, pid, body.hs_code, body.reporter, body.period, body.flow, body.partner)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except ProviderFailure as e:
        raise HTTPException(502, f"UN Comtrade: {e}")
    log(ctx, "leads.comtrade", "client", client_id, f"Fetched {len(rows)} UN Comtrade row(s) for HS {body.hs_code}", client_id=client_id)
    ctx.db.commit()
    return [insight_out(i) for i in rows]


@router.post("/api/v1/clients/{client_id}/leads/market-insights", status_code=201)
def add_insight(client_id: str, body: InsightIn, ctx: Ctx = Depends(get_ctx)):
    _client(ctx, client_id)
    i = TradeMarketInsight(tenant_id=ctx.tenant_id, client_id=client_id, product_id=_product(ctx, client_id, body.product_id), kind=body.kind,
                           title=body.title.strip(), detail=body.detail, source="user", source_url=_src(body.source_url, True),
                           hs_code=body.hs_code, reporter=body.reporter, retrieved_at=_now(), created_by=ctx.user.id)
    ctx.db.add(i)
    ctx.db.commit()
    return insight_out(i)


@router.delete("/api/v1/leads/market-insights/{insight_id}", status_code=204)
def delete_insight(insight_id: str, ctx: Ctx = Depends(get_ctx)):
    i = get_owned(ctx, TradeMarketInsight, insight_id, "Insight")
    ctx.db.delete(i)
    ctx.db.commit()
