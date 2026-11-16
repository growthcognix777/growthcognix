"""Competitor entry, domain validation and AI suggestions.

A competitor must be relevant by product, application, customer type or geography. AI suggestions are
stored as `suggested` (origin=ai) until a person accepts them; suggestions with no relevance basis or a
domain that does not resolve to a public address are dropped, never shown as found competitors.
"""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from app.models import Client, Competitor, Product, ProductApplication, TargetMarket
from app.services.ai.providers import ProviderError, get_provider
from app.services.intelligence.website_analyser import UnsafeURL, check_url
from app.services.web.crawler_service import domain_of, normalize

CATEGORIES = ("direct", "indirect", "substitute", "aspirational")
RELEVANCE_KEYS = ("product", "application", "customer", "geography")


def clean_website(url: str | None) -> str | None:
    if not url or not url.strip():
        return None
    url = url.strip()
    if "://" not in url:
        url = "https://" + url
    n = normalize(url)
    if not n:
        raise ValueError("Enter a valid website (e.g. competitor.com)")
    return n.split("?")[0]


def validate_domain(website: str | None) -> tuple[bool | None, str | None]:
    """(valid, reason). DNS must resolve to public addresses (same SSRF guard the crawler uses)."""
    if not website:
        return None, None
    try:
        check_url(website)
        return True, None
    except UnsafeURL as e:
        return False, str(e)


class Suggestion(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    website: str = Field(min_length=4, max_length=300)
    category: Literal["direct", "indirect", "substitute", "aspirational"] = "direct"
    relevance: dict[str, str] = Field(default_factory=dict)
    geography: list[str] = Field(default_factory=list, max_length=10)
    reason: str = Field(default="", max_length=600)


class SuggestOut(BaseModel):
    competitors: list[Suggestion] = Field(default_factory=list, max_length=30)


SYSTEM = """You help a digital marketing agency identify a client's real competitors.
Only suggest companies you are confident exist, with their real public website domain. Never invent a
company or domain. A competitor must overlap with the client by product, application, customer type or
geography: a shared keyword alone is not enough. Return JSON only."""


def suggest(db, tenant_id: str, client: Client, count: int = 15) -> dict:
    provider = get_provider("fast")
    products = db.scalars(select(Product).where(Product.tenant_id == tenant_id, Product.client_id == client.id)).all()
    apps = db.scalars(select(ProductApplication).where(ProductApplication.tenant_id == tenant_id,
                      ProductApplication.client_id == client.id, ProductApplication.verification_status != "rejected")).all()
    markets = db.scalars(select(TargetMarket).where(TargetMarket.tenant_id == tenant_id,
                         TargetMarket.client_id == client.id, TargetMarket.verification_status != "rejected")).all()
    brief = {"client": client.company_name, "website": client.website, "industry": client.industry,
             "business_type": client.business_type, "description": (client.description or "")[:1500],
             "target_markets": client.target_markets,
             "products": [{"name": p.name, "category": p.category, "description": (p.description or "")[:400]} for p in products[:20]],
             "applications": [{"application": a.application, "industry": a.industry} for a in apps[:30]],
             "market_hypotheses": [m.name for m in markets[:30]]}
    prompt = (f"Suggest up to {count} competitors for this client.\nCLIENT:\n{json.dumps(brief, ensure_ascii=False)}\n\n"
              'JSON SHAPE: {"competitors": [{"name": "...", "website": "domain.com", "category": "direct|indirect|substitute|aspirational", '
              '"relevance": {"product": "overlapping product or empty", "application": "...", "customer": "...", "geography": "..."}, '
              '"geography": ["countries/regions they sell in"], "reason": "one sentence"}]}')
    try:
        raw = provider.generate_json(SYSTEM, prompt)
        out = SuggestOut.model_validate(raw)
    except (ProviderError, ValidationError) as e:
        raise RuntimeError(f"AI suggestion failed: {str(e)[:300]}") from e

    existing = {c.domain for c in db.scalars(select(Competitor).where(Competitor.tenant_id == tenant_id,
                                                                       Competitor.client_id == client.id)).all() if c.domain}
    own = domain_of(client.website) if client.website else None
    created, dropped = [], {"no_relevance": 0, "invalid_domain": 0, "duplicate": 0}
    for s in out.competitors:
        relevance = {k: v.strip()[:300] for k, v in s.relevance.items() if k in RELEVANCE_KEYS and v and v.strip()}
        if not relevance:
            dropped["no_relevance"] += 1
            continue
        try:
            site = clean_website(s.website)
        except ValueError:
            dropped["invalid_domain"] += 1
            continue
        dom = domain_of(site)
        if dom in existing or dom == own:
            dropped["duplicate"] += 1
            continue
        valid, _ = validate_domain(site)
        if not valid:
            dropped["invalid_domain"] += 1
            continue
        existing.add(dom)
        c = Competitor(tenant_id=tenant_id, client_id=client.id, name=s.name.strip(), website=site, domain=dom,
                       category=s.category, relevance=relevance, geography=[g.strip()[:100] for g in s.geography if g.strip()],
                       notes=s.reason or None, origin="ai", status="suggested", domain_valid=True)
        db.add(c)
        created.append(c)
    db.flush()
    return {"created": len(created), "dropped": dropped, "provider": provider.name, "model": provider.model}
