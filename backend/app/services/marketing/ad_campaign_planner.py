"""Ad campaign planner for Meta, Google and LinkedIn. Plans only.

The AI drafts objective, audience, headlines, ad copy, creative brief, bidding suggestion, conversion
tracking and A/B tests from the client's records. Budget comes from the team. Nothing is created, published,
bid on or spent on any ad platform: there is no ad-account adapter in this phase, and when there is one it
must check the recorded spend approval (spend_approved, spend_cap, who, when) before any call.
"""
from __future__ import annotations

from pydantic import Field, field_validator

from app.models import AdvertisingCampaign, BuyerPersona, Product
from app.services.ai.providers import get_provider
from app.services.intelligence.common import ask
from app.services.marketing.common import GUARANTEE, Claimable, detect_claims, guarantee_issues, marketing_sources, source_text, str_list

PLATFORMS = {"meta": "Meta (Facebook & Instagram) Ads", "google": "Google Ads", "linkedin": "LinkedIn Ads"}
# Published ad-copy limits (characters): Google RSA headline 30 / description 90; Meta primary text ~125 shown,
# headline ~40 shown; LinkedIn intro text 150 shown (600 max), headline 70.
COPY_LIMITS = {"google": (30, 90), "meta": (40, 125), "linkedin": (70, 600)}
ADAPTERS = {
    "meta": "Not connected. Creating ads needs a Meta Marketing API app with ads_management (App Review) and access to the client's ad account.",
    "google": "Not connected. Creating ads needs a Google Ads API developer token (approval required) and OAuth access to the client's account.",
    "linkedin": "Not connected. Creating ads needs the LinkedIn Advertising API product (application required) and a role on the ad account.",
}


class Plan(Claimable):
    name: str = Field(max_length=200)
    objective: str = Field(default="", max_length=100)
    audience: dict = Field(default_factory=dict)
    geography: list[str] = Field(default_factory=list)
    creative_brief: str = Field(default="", max_length=3000)
    headlines: list[str] = Field(default_factory=list)
    ad_copy: list[str] = Field(default_factory=list)
    bidding: str = Field(default="", max_length=1000)
    conversion_tracking: str = Field(default="", max_length=1500)
    ab_tests: list[str] = Field(default_factory=list)

    @field_validator("geography", "headlines", "ad_copy", "ab_tests", mode="before")
    @classmethod
    def _l(cls, v):
        return str_list(v, 15, 700)

    @field_validator("audience", mode="before")
    @classmethod
    def _a(cls, v):
        return v if isinstance(v, dict) else {"description": str(v)[:500]} if v else {}


SHAPE = """{"name": "...", "objective": "leads|traffic|awareness|conversions|video_views",
 "audience": {"description": "...", "industries": ["..."], "job_titles": ["..."], "interests": ["..."], "keywords": ["for Google"], "exclusions": ["..."]},
 "geography": ["..."], "creative_brief": "...", "headlines": ["..."], "ad_copy": ["..."],
 "bidding": "suggested strategy and why", "conversion_tracking": "what to track and how (pixel / tag / lead form)",
 "ab_tests": ["what to test"], "claims_to_check": ["facts used that a person must verify"]}"""


def generate(db, tenant_id: str, client, user_id: str | None, *, platform: str, product_id: str | None, persona_id: str | None,
             objective: str | None, geography: list[str], landing_page: str | None, daily_budget: float | None,
             total_budget: float | None, currency: str, campaign_id: str | None) -> AdvertisingCampaign:
    if platform not in PLATFORMS:
        raise ValueError("Platform must be meta, google or linkedin")
    product = db.get(Product, product_id) if product_id else None
    if product_id and (not product or product.client_id != client.id):
        raise ValueError("Product not found for this client")
    persona = db.get(BuyerPersona, persona_id) if persona_id else None
    if persona_id and (not persona or persona.client_id != client.id):
        raise ValueError("Buyer profile not found for this client")
    provider = get_provider("analysis")
    srcs = marketing_sources(db, tenant_id, client, [product.id] if product else None)
    hl, dl = COPY_LIMITS[platform]
    task = (f"Plan one {PLATFORMS[platform]} campaign. " + (f"Product: {product.name}. " if product else "")
            + (f"Buyer profile: {persona.name}. " if persona else "") + (f"Objective: {objective}. " if objective else "")
            + (f"Geography: {', '.join(geography)}. " if geography else "") + (f"Landing page: {landing_page}. " if landing_page else "")
            + f"Write 5-10 headlines of at most {hl} characters and 3-5 ad texts of at most {dl} characters. Do not set or "
            "change the budget. Performance targets are set by the team, so do not predict CPL, CTR or ROAS. Use only facts from "
            "the sources; never invent certifications, awards, prices or offers; no guarantees.")
    p: Plan = ask(provider, Plan, task, SHAPE, source_text(srcs, provider.max_context_chars))
    heads = [GUARANTEE.sub("", h).strip()[:hl] for h in p.headlines if h.strip()]
    copy = [GUARANTEE.sub("", c).strip()[:dl] for c in p.ad_copy if c.strip()]
    removed = guarantee_issues(*p.headlines, *p.ad_copy, p.creative_brief)
    claims = list(dict.fromkeys(p.claims_to_check + detect_claims(" ".join(heads + copy), srcs)))
    ad = AdvertisingCampaign(tenant_id=tenant_id, client_id=client.id, campaign_id=campaign_id, platform=platform,
                             name=p.name.strip()[:200] or f"{PLATFORMS[platform]} plan", objective=(objective or p.objective)[:100] or None,
                             audience=p.audience, geography=geography or p.geography, creative_brief=p.creative_brief, headlines=heads,
                             ad_copy=copy, landing_page=landing_page, currency=currency, daily_budget=daily_budget, total_budget=total_budget,
                             bidding=p.bidding, conversion_tracking=p.conversion_tracking, ab_tests=p.ab_tests,
                             targets={"removed_promises": sorted(set(removed))} if removed else {}, claims_to_check=claims,
                             status="ai_generated", origin="ai", provider=provider.name, model=provider.model, created_by=user_id)
    db.add(ad)
    db.flush()
    return ad
