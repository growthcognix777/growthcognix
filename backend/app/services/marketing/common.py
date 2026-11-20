"""Shared plumbing for Phase 5: the client's real records as numbered sources, the AI call, claim checks,
revision history.

Sources reuse Phase 2's builder (client record, product records, extracted documents, website pages) and add
what earlier phases produced: approved/team buyer profiles, target markets, active competitors, the latest
website audit summary, approved brand assets and connected channels. Anything not in these sources is not
a fact; the generators must put it under assumptions or leave it out.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from types import SimpleNamespace

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.models import (BuyerPersona, Client, Competitor, ContentAsset, ContentRevision, Product, SocialAccount, TargetMarket,
                        WebsiteAudit)
from app.services.intelligence.common import Source, _fmt, _norm, build_sources, render_sources

# Phrases a marketing draft must never contain as a promise.
GUARANTEE = re.compile(r"\b(guarantee[sd]?|guaranteed|assured (?:results|leads|roi|returns|sales)|100% (?:results|success)|"
                       r"(?:will|shall) (?:definitely|surely) (?:get|generate|double|triple)|risk[- ]free returns?)\b", re.I)
# Claims that need a source before anything is published.
CLAIM_PATTERNS = [
    ("certification", re.compile(r"\b(ISO\s?\d{3,5}|CE\b|BIS\b|ISI\b|FDA|GMP|HACCP|FSSAI|NABL|UL\b|IATF|certified|certification)", re.I)),
    ("award", re.compile(r"\b(award(?:-winning|ed)?|winner|ranked|best[- ]in[- ]class|no\.?\s?1|number one|#1|leading|market leader)\b", re.I)),
    ("number", re.compile(r"\b\d[\d,.]*\s?(%|percent|years?|customers|clients|units|tonnes?|tons?|kg|lph|litres?|countries|installations|\+)", re.I)),
    ("price", re.compile(r"(₹|rs\.?\s?\d|inr\s?\d|\$\s?\d|usd\s?\d|price|discount|% off|offer)", re.I)),
    ("endorsement", re.compile(r"\b(trusted by|endorsed|recommended by|approved by|partner of|used by)\b", re.I)),
    ("comparison", re.compile(r"\b(better than|cheaper than|faster than|unlike (?:other|competitors)|only (?:company|supplier|manufacturer))\b", re.I)),
]


def now() -> datetime:
    return datetime.now(timezone.utc)


def str_list(v, n: int = 15, size: int = 300) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        v = [v]
    return [str(x).strip()[:size] for x in v if str(x).strip()][:n]


class Fact(BaseModel):
    text: str = Field(max_length=600)
    source_id: str = Field(default="", max_length=80)
    quote: str = Field(default="", max_length=600)


class Claimable(BaseModel):
    claims_to_check: list[str] = Field(default_factory=list)

    @field_validator("claims_to_check", mode="before")
    @classmethod
    def _c(cls, v):
        return str_list(v, 20)


def marketing_sources(db, tenant_id: str, client: Client, product_ids: list[str] | None = None) -> list[Source]:
    q = select(Product).where(Product.tenant_id == tenant_id, Product.client_id == client.id)
    if product_ids:
        q = q.where(Product.id.in_(product_ids))
    products = list(db.scalars(q).all())
    srcs = build_sources(SimpleNamespace(db=db, tenant_id=tenant_id, client=client, products=products))
    budget = client.marketing_budget
    srcs[0].text += "\n" + _fmt([("Monthly marketing budget given by client", f"{budget} {client.budget_currency}" if budget is not None else None)])
    for p in db.scalars(select(BuyerPersona).where(BuyerPersona.tenant_id == tenant_id, BuyerPersona.client_id == client.id,
                                                   BuyerPersona.verification_status != "rejected")).all():
        if not (p.approved or p.origin == "user"):
            continue
        srcs.append(Source(f"persona:{p.id}", "client_record", f"Buyer profile (team-approved hypothesis): {p.name}", _fmt([
            ("Name", p.name), ("Buyer type", p.buyer_type), ("Industry", p.industry), ("Company types", p.company_types),
            ("Applications", p.application_categories), ("Problems solved", p.problems_solved or p.pain_points),
            ("Decision-makers", p.job_titles), ("Purchase reasons", p.purchase_reasons), ("Substitutes", p.substitutes),
            ("Geography", p.geography)]), product_id=p.product_id))
    mk = db.scalars(select(TargetMarket).where(TargetMarket.tenant_id == tenant_id, TargetMarket.client_id == client.id,
                                               TargetMarket.verification_status != "rejected")).all()
    if mk:
        srcs.append(Source("markets", "client_record", "Target markets (Phase 2 findings; hypotheses unless verified)",
                           "\n".join(f"- {m.name} ({m.scope}{', ' + m.parent if m.parent else ''}){': ' + m.rationale if m.rationale else ''}"
                                     f" [{'approved' if m.approved else m.verification_status}]" for m in mk[:30])))
    comps = db.scalars(select(Competitor).where(Competitor.tenant_id == tenant_id, Competitor.client_id == client.id,
                                                Competitor.status == "active")).all()
    if comps:
        srcs.append(Source("competitors", "client_record", "Competitors entered or accepted by the team",
                           "\n".join(f"- {c.name} ({c.category}) {c.website or ''} relevance: "
                                     + "; ".join(f"{k}: {v}" for k, v in (c.relevance or {}).items()) for c in comps[:20])))
    audit = db.scalar(select(WebsiteAudit).where(WebsiteAudit.tenant_id == tenant_id, WebsiteAudit.client_id == client.id)
                      .order_by(WebsiteAudit.created_at.desc()).limit(1))
    if audit:
        s = audit.summary or {}
        recs = "; ".join(r.get("title", "") for r in (audit.recommendations or [])[:8])
        srcs.append(Source("audit", "website", "Latest website audit (crawler observations)", _fmt([
            ("Health score (crawler observations, not a ranking)", audit.health_score), ("Findings by severity", s.get("by_severity")),
            ("Recommendations", recs)])))
    assets = db.scalars(select(ContentAsset).where(ContentAsset.tenant_id == tenant_id, ContentAsset.client_id == client.id,
                                                   ContentAsset.approved.is_(True))).all()
    if assets:
        srcs.append(Source("brand", "client_record", "Approved brand assets", "\n".join(
            f"- {a.kind}: {a.name}{' = ' + a.value if a.value else ''}{' — ' + a.notes if a.notes else ''}" for a in assets[:40])))
    accts = db.scalars(select(SocialAccount).where(SocialAccount.tenant_id == tenant_id, SocialAccount.client_id == client.id)).all()
    if accts:
        srcs.append(Source("channels", "client_record", "Social channels on record",
                           "\n".join(f"- {a.platform}: {a.account_name} ({a.status})" for a in accts)))
    return srcs


def source_text(srcs: list[Source], budget: int) -> str:
    return render_sources(srcs, budget)


def quote_ok(srcs: list[Source], source_id: str, quote: str) -> bool:
    s = next((x for x in srcs if x.ref == source_id), None)
    q = _norm(quote or "")
    return bool(s and len(q) >= 8 and q in _norm(s.text))


def detect_claims(text: str, srcs: list[Source] | None = None) -> list[str]:
    """Sentences with certifications, awards, numbers, prices, endorsements or comparisons. Each must be
    fact-checked by a person; sentences whose wording appears verbatim in a source are noted as such."""
    out = []
    for sent in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        s = sent.strip()
        if len(s) < 6:
            continue
        kinds = [k for k, rx in CLAIM_PATTERNS if rx.search(s)]
        if kinds:
            found = srcs and any(_norm(s)[:60] in _norm(x.text) for x in srcs)
            out.append(f"[{'/'.join(kinds)}] {s[:280]}" + (" (wording found in client sources)" if found else ""))
    return out[:20]


def guarantee_issues(*texts: str) -> list[str]:
    return [m.group(0) for t in texts for m in GUARANTEE.finditer(t or "")]


def snapshot(obj, fields: list[str]) -> dict:
    out = {}
    for f in fields:
        v = getattr(obj, f)
        out[f] = v.isoformat() if isinstance(v, datetime) else v
    return out


def record_revision(db, tenant_id: str, entity_type: str, obj, fields: list[str], user_id: str | None, note: str | None = None) -> None:
    db.add(ContentRevision(tenant_id=tenant_id, entity_type=entity_type, entity_id=obj.id, version=obj.version or 1,
                           snapshot=snapshot(obj, fields), note=note, user_id=user_id, created_at=now()))
