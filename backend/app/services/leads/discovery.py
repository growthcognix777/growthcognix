"""Discovery campaign runner (RQ worker).

Stages: plan targets (buyer profile x geography x source) -> search/directory -> create or merge prospects by
normalised domain -> inspect each prospect's own website -> score. Every target and every prospect is committed
as it finishes, so pause, cancel, a crash or a provider outage keeps progress and a resume skips done work.

What it never does: invent companies, contacts or intent. A search hit only makes a company `discovered`;
fetching its site can only add `website_verified`. Everything else is a person's decision.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import (ActivityLog, BuyerPersona, BusinessContact, Client, Competitor, DiscoveryCampaign, DiscoveryTarget,
                        EvidenceSource, GeographicArea, LeadScore, LeadVerification, ProductApplication, ProspectCompany,
                        ProspectProductFit, SuppressionEntry)
from app.models.leads import VERIFICATION_ORDER
from app.services.leads import providers, scoring, site_verifier
from app.services.web.crawler_service import domain_of

log = logging.getLogger(__name__)
QUERIES_PER_PROFILE = 2


def _now():
    return datetime.now(timezone.utc)


def rank(status: str) -> int:
    return VERIFICATION_ORDER.index(status) if status in VERIFICATION_ORDER else -1


def norm_domain(url_or_domain: str | None) -> str | None:
    if not url_or_domain:
        return None
    s = url_or_domain.strip().lower()
    d = domain_of(s if "://" in s else "https://" + s)
    return d or None


# ------------------------------------------------------------------ suppression
def suppressed(db, tenant_id: str, kind: str, value: str | None) -> bool:
    if not value:
        return False
    v = value.strip().lower()
    if kind == "phone":
        v = re.sub(r"\D", "", v)
    rows = db.scalars(select(SuppressionEntry.value).where(SuppressionEntry.tenant_id == tenant_id, SuppressionEntry.kind == kind)).all()
    if kind == "domain":
        return any(v == r or v.endswith("." + r) for r in rows)
    if kind == "email":
        return v in rows or (v.split("@")[-1] in set(db.scalars(select(SuppressionEntry.value).where(
            SuppressionEntry.tenant_id == tenant_id, SuppressionEntry.kind == "domain")).all()))
    return v in {re.sub(r"\D", "", r) for r in rows}


# ------------------------------------------------------------------ planning
def _phrases(p: BuyerPersona) -> list[str]:
    out = []
    for x in list(p.company_types or []) + list(p.application_categories or []) + [p.industry or ""]:
        x = " ".join(str(x).split())
        if x and x.lower() not in {o.lower() for o in out}:
            out.append(x)
    return out[:QUERIES_PER_PROFILE] or [p.name]


def _geo_text(g: GeographicArea) -> str:
    path = [x for x in (g.path or []) if x]
    if g.level == "global" or not path:
        return ""
    # most specific two levels, e.g. "Belagavi Karnataka", plus the country for international areas
    tail = list(reversed(path[-2:]))  # most specific first: "Belagavi Karnataka"
    if path[0] != "India" and path[0] not in tail:
        tail.append(path[0])
    return " ".join(tail)


def _key(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:40]


def plan_targets(db, c: DiscoveryCampaign) -> int:
    personas = db.scalars(select(BuyerPersona).where(BuyerPersona.tenant_id == c.tenant_id, BuyerPersona.client_id == c.client_id,
                                                     BuyerPersona.id.in_(c.persona_ids or []))).all()
    geos = db.scalars(select(GeographicArea).where(GeographicArea.tenant_id == c.tenant_id, GeographicArea.client_id == c.client_id,
                                                   GeographicArea.id.in_(c.geography_ids or []))).all() or [None]
    existing = set(db.scalars(select(DiscoveryTarget.key).where(DiscoveryTarget.campaign_id == c.id)).all())
    added = 0
    for src in c.sources or []:
        if src == "directory":
            for url in (c.config or {}).get("directory_urls", []):
                k = _key("directory", url)
                if k not in existing:
                    db.add(DiscoveryTarget(tenant_id=c.tenant_id, client_id=c.client_id, campaign_id=c.id, key=k, provider="directory", query=url))
                    existing.add(k)
                    added += 1
            continue
        for p in personas:
            for g in geos:
                for phrase in _phrases(p):
                    q = " ".join(x for x in (phrase, _geo_text(g) if g else "") if x)[:500]
                    k = _key(src, p.id, g.id if g else "-", q)
                    if k in existing:
                        continue
                    db.add(DiscoveryTarget(tenant_id=c.tenant_id, client_id=c.client_id, campaign_id=c.id, key=k, persona_id=p.id,
                                           geography_id=g.id if g else None, provider=src, query=q))
                    existing.add(k)
                    added += 1
    db.flush()
    return added


# ------------------------------------------------------------------ prospects
def _clean_name(title: str, domain: str) -> str:
    t = re.split(r"\s+[|\-–—:]\s+", title or "")[0].strip()
    return (t or domain)[:300]


def _evidence(db, p: ProspectCompany, *, field: str, source_type: str, url: str | None, excerpt: str, provider: str,
              ref: str | None = None) -> None:
    db.add(EvidenceSource(tenant_id=p.tenant_id, client_id=p.client_id, finding_type="prospect", finding_id=p.id,
                          source_type=source_type, source_ref=(ref or "")[:80] or None, source_url=(url or "")[:500] or None,
                          excerpt=(excerpt or "")[:1000], quote_matched=source_type == "website", field=field, provider=provider,
                          observed_at=_now()))


def absorb_hit(db, c: DiscoveryCampaign, t: DiscoveryTarget, hit: providers.Hit, block: set[str], counts: dict,
               persona: BuyerPersona | None, geo: GeographicArea | None) -> bool:
    """Create or merge one candidate. Returns True if a new prospect was created."""
    d = norm_domain(hit.url)
    if not d:
        counts["invalid"] = counts.get("invalid", 0) + 1
        return False
    if providers.is_listing_site(d):
        counts["listing_skipped"] = counts.get("listing_skipped", 0) + 1
        return False
    if d in block:
        counts["own_or_competitor"] = counts.get("own_or_competitor", 0) + 1
        return False
    if suppressed(db, c.tenant_id, "domain", d):
        counts["suppressed"] = counts.get("suppressed", 0) + 1
        return False
    source_type = "directory" if hit.provider == "directory" else "search_result"
    excerpt = " — ".join(x for x in (hit.title, hit.snippet) if x)
    area = list(geo.path) if geo else []
    p = db.scalar(select(ProspectCompany).where(ProspectCompany.client_id == c.client_id, ProspectCompany.domain == d))
    if p:
        counts["duplicates_merged"] = counts.get("duplicates_merged", 0) + 1
        if hit.provider not in (p.providers or []):
            p.providers = list(p.providers or []) + [hit.provider]
        if area and area not in (p.searched_area or []):
            p.searched_area = list(p.searched_area or []) + [area]
        seen = db.scalar(select(EvidenceSource.id).where(EvidenceSource.finding_type == "prospect", EvidenceSource.finding_id == p.id,
                                                          EvidenceSource.field == "discovery", EvidenceSource.provider == hit.provider,
                                                          EvidenceSource.source_url == (hit.source_url or hit.url)[:500]))
        if not seen:
            _evidence(db, p, field="discovery", source_type=source_type, url=hit.source_url or hit.url, excerpt=excerpt,
                      provider=hit.provider, ref=f"{t.provider}:{t.query}")
        return False
    if counts.get("new_prospects", 0) >= int((c.config or {}).get("max_companies") or get_settings().discovery_max_companies):
        counts["over_limit"] = counts.get("over_limit", 0) + 1
        return False
    root = f"https://{d}/" if not hit.url.startswith("http://") else f"http://{d}/"
    reason = f"Found by {'directory' if hit.provider == 'directory' else 'search'} '{t.query}'"
    if persona:
        reason += f" for buyer profile '{persona.name}'"
    p = ProspectCompany(tenant_id=c.tenant_id, client_id=c.client_id, name=_clean_name(hit.title, d), website=root, domain=d,
                        buyer_type=persona.buyer_type if persona else None, searched_area=[area] if area else [],
                        qualification_reason=reason + ". Not verified.", verification_status="discovered",
                        providers=[hit.provider], origin="discovery", first_campaign_id=c.id, created_by=c.created_by)
    db.add(p)
    db.flush()
    _evidence(db, p, field="discovery", source_type=source_type, url=hit.source_url or hit.url, excerpt=excerpt,
              provider=hit.provider, ref=f"{t.provider}:{t.query}")
    counts["new_prospects"] = counts.get("new_prospects", 0) + 1
    return True


def apply_site(db, p: ProspectCompany, obs: dict, personas: list[BuyerPersona], user_id: str | None = None) -> None:
    """Record site observations on a prospect. Only sets website_verified (the system fetched it)."""
    p.site_checked_at, p.site_status = obs["checked_at"], (obs["status"] or "error")[:60]
    if obs["status"] != "ok":
        db.add(LeadVerification(tenant_id=p.tenant_id, client_id=p.client_id, prospect_id=p.id, field="website",
                                decision="needs_review", note=f"Site check: {obs['status']}", source_url=p.website, user_id=user_id))
        return
    vf = dict(p.verified_fields or {})
    vf["website"] = {"by": "system", "at": obs["checked_at"].isoformat(), "note": f"Site fetched: {obs['final_url']}"}
    p.verified_fields = vf
    if p.verification_status not in ("rejected", "needs_review") and rank(p.verification_status) < rank("website_verified"):
        p.verification_status = "website_verified"
    if obs.get("description") and not p.description:
        p.description = obs["description"][:2000]
    p.observed_locations = [x["name"] for x in obs["locations"]]
    p.signals = {"matched_terms": obs["matched_terms"], "intent": obs["intent"], "capacity": obs["capacity"],
                 "pages": obs["pages"], "checked_at": obs["checked_at"].isoformat()}
    db.add(LeadVerification(tenant_id=p.tenant_id, client_id=p.client_id, prospect_id=p.id, field="website",
                            decision="system_observed", note=f"Fetched {len(obs['pages'])} page(s)", source_url=obs["final_url"], user_id=user_id))
    for m in obs["matched_terms"]:
        _evidence(db, p, field=m["kind"], source_type="website", url=m["url"], excerpt=m["excerpt"], provider="site_verification")
    for i in obs["intent"]:
        _evidence(db, p, field="intent", source_type="website", url=i["url"], excerpt=i["excerpt"], provider="site_verification")
    for cap in obs["capacity"]:
        _evidence(db, p, field="capacity", source_type="website", url=cap["url"], excerpt=cap["excerpt"], provider="site_verification")
    # product fit rows: one per buyer profile whose terms the site mentions
    db.query(ProspectProductFit).filter(ProspectProductFit.prospect_id == p.id, ProspectProductFit.origin == "observed").delete()
    matched = {m["term"] for m in obs["matched_terms"]}
    for persona in personas:
        own = {t["term"] for t in site_verifier.terms_from([persona], [])}
        hit = sorted(own & matched)
        if hit:
            db.add(ProspectProductFit(tenant_id=p.tenant_id, client_id=p.client_id, prospect_id=p.id, product_id=persona.product_id,
                                      persona_id=persona.id, application=hit[0][:300], relation=persona.industry_relation or "direct",
                                      matched_terms=hit, origin="observed",
                                      reason=f"Its site mentions {', '.join(hit[:4])} (buyer profile '{persona.name}')"))
    client = db.get(Client, p.client_id)
    for ct in obs["contacts"]:
        if suppressed(db, p.tenant_id, "email" if ct["kind"] == "role_email" else "phone", ct["value"]):
            continue
        dup = db.scalar(select(BusinessContact.id).where(BusinessContact.prospect_id == p.id, BusinessContact.value == ct["value"]))
        if not dup:
            db.add(BusinessContact(tenant_id=p.tenant_id, client_id=p.client_id, prospect_id=p.id, kind=ct["kind"], value=ct["value"],
                                   source_url=ct["url"], observed_at=obs["checked_at"], origin="observed",
                                   purpose=f"B2B prospect research for {client.company_name if client else 'client'}"))


def weights_for(db, client_id: str, override: dict | None = None) -> dict:
    """Campaign- or request-level weights; defaults otherwise (fit 30, need 25, intent 20, capacity 15, contact 10)."""
    return scoring.normalise_weights(override or None)


def rescore(db, p: ProspectCompany, weights: dict | None = None) -> dict:
    db.flush()  # sessions run with autoflush off; make new evidence/contacts visible to the queries below
    contacts = db.scalars(select(BusinessContact).where(BusinessContact.prospect_id == p.id)).all()
    uev = db.scalars(select(EvidenceSource).where(EvidenceSource.finding_type == "prospect", EvidenceSource.finding_id == p.id,
                                                  EvidenceSource.source_type == "user")).all()
    res = scoring.compute(p, list(contacts), list(uev), weights)
    p.score_total, p.score_class, p.confidence = res["total"], res["score_class"], res["confidence"]
    db.add(LeadScore(tenant_id=p.tenant_id, client_id=p.client_id, prospect_id=p.id, total=res["total"], score_class=res["score_class"],
                     confidence=res["confidence"], components=res["components"], weights=res["weights"], explanation=res["explanation"],
                     version=res["version"]))
    return res


# ------------------------------------------------------------------ runner
def run_campaign(campaign_id: str, crawler=None) -> None:
    db = SessionLocal()
    try:
        _run(db, campaign_id, crawler)
    except Exception as e:  # noqa: BLE001
        log.exception("campaign %s failed", campaign_id)
        db.rollback()
        c = db.get(DiscoveryCampaign, campaign_id)
        if c:
            c.status, c.error, c.completed_at = "failed", f"{type(e).__name__}: {e}"[:2000], _now()
            db.commit()
    finally:
        db.close()


def _halted(db, c: DiscoveryCampaign) -> bool:
    db.refresh(c)
    return c.status in ("paused", "cancelled")


def _run(db, campaign_id: str, crawler) -> None:
    c = db.get(DiscoveryCampaign, campaign_id)
    if c is None or c.status not in ("queued", "running"):
        return
    s = get_settings()
    c.status, c.started_at, c.error, c.attempts = "running", c.started_at or _now(), None, c.attempts + 1
    c.stage = "search"
    plan_targets(db, c)
    db.commit()
    counts = dict(c.counts or {})
    personas = {p.id: p for p in db.scalars(select(BuyerPersona).where(BuyerPersona.id.in_(c.persona_ids or []))).all()}
    geos = {g.id: g for g in db.scalars(select(GeographicArea).where(GeographicArea.id.in_(c.geography_ids or []))).all()}
    client = db.get(Client, c.client_id)
    block = {d for d in [norm_domain(getattr(client, "website", None))] + [
        x for x in db.scalars(select(Competitor.domain).where(Competitor.client_id == c.client_id)).all()] if d}

    targets = db.scalars(select(DiscoveryTarget).where(DiscoveryTarget.campaign_id == c.id, DiscoveryTarget.status.in_(("pending", "failed")))
                         .order_by(DiscoveryTarget.created_at, DiscoveryTarget.id)).all()
    total_targets = db.query(DiscoveryTarget).filter(DiscoveryTarget.campaign_id == c.id).count() or 1
    per_query = int((c.config or {}).get("results_per_query") or s.discovery_results_per_query)
    for t in targets:
        if _halted(db, c):
            c.counts = counts
            db.commit()
            return
        prov = providers.ALL.get(t.provider)
        if prov is None or not prov.configured():
            t.status, t.error = "skipped", f"Source '{t.provider}' is not configured on this server"
            db.commit()
            continue
        if providers.used_today(db, c.tenant_id, t.provider) >= prov.daily_limit():
            c.status, c.error = "paused", f"Daily limit for {prov.label} reached ({prov.daily_limit()}). Resume tomorrow; finished work is kept."
            c.counts = counts
            db.commit()
            return
        t.attempts += 1
        geo = geos.get(t.geography_id) if t.geography_id else None
        try:
            if t.provider == "directory":
                hits, _ = providers.call_with_retry(lambda: prov.fetch(t.query, s.discovery_max_companies))
            else:
                region = geo.country_code if geo else None
                hits, _ = providers.call_with_retry(lambda: prov.search(t.query, per_query, region))
        except providers.ProviderFailure as e:
            t.status, t.error, t.executed_at = "failed", str(e)[:500], _now()
            counts["failed_targets"] = counts.get("failed_targets", 0) + 1
            db.commit()
            continue
        new = 0
        for h in hits:
            new += absorb_hit(db, c, t, h, block, counts, personas.get(t.persona_id), geo)
        t.status, t.results_count, t.new_prospects, t.executed_at, t.error = "done", len(hits), new, _now(), None
        counts["results"] = counts.get("results", 0) + len(hits)
        done = db.query(DiscoveryTarget).filter(DiscoveryTarget.campaign_id == c.id, DiscoveryTarget.status != "pending").count()
        c.progress, c.counts = min(60, int(60 * done / total_targets)), dict(counts)
        db.commit()

    # verify: fetch each new prospect's own site
    c.stage = "verify"
    db.commit()
    plist = list(personas.values())
    terms = site_verifier.terms_from(plist, db.scalars(select(ProductApplication).where(
        ProductApplication.client_id == c.client_id, ProductApplication.verification_status != "rejected")).all())
    todo = db.scalars(select(ProspectCompany).where(ProspectCompany.first_campaign_id == c.id, ProspectCompany.site_checked_at.is_(None))).all()
    n = len(todo) or 1
    for i, p in enumerate(todo):
        if _halted(db, c):
            c.counts = counts
            db.commit()
            return
        obs = site_verifier.inspect(p.website, terms, s.discovery_verify_pages, crawler)
        apply_site(db, p, obs, plist)
        counts["sites_checked"] = counts.get("sites_checked", 0) + 1
        if obs["status"] == "ok":
            counts["sites_ok"] = counts.get("sites_ok", 0) + 1
        c.progress, c.counts = 60 + int(30 * (i + 1) / n), dict(counts)
        db.commit()

    c.stage = "score"
    w = weights_for(db, c.client_id, (c.config or {}).get("weights"))
    for p in db.scalars(select(ProspectCompany).where(ProspectCompany.first_campaign_id == c.id)).all():
        rescore(db, p, w)
    c.status, c.stage, c.progress, c.completed_at, c.counts = "completed", None, 100, _now(), dict(counts)
    db.add(ActivityLog(tenant_id=c.tenant_id, user_id=c.created_by, action="discovery.completed", entity_type="discovery_campaign",
                       entity_id=c.id, summary=f"Discovery '{c.name}' finished: {counts.get('new_prospects', 0)} new prospect(s)",
                       meta={"client_id": c.client_id, "counts": counts}))
    db.commit()
