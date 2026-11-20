"""AI drafting for the social, SEO and ads studios (one engine, three briefs).

Every generated item:
  * is grounded in the client's records (common.marketing_sources) and the chosen product / buyer profile;
  * is saved as status `ai_generated`, never approved or scheduled;
  * carries `claims_to_check`: what the model flagged plus every sentence our own scan finds with a
    certification, award, number, price, endorsement or comparison. A person clears them in review;
  * has guarantee language removed;
  * is cut to the platform's published limits.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

from app.models import BuyerPersona, ContentItem, Product
from app.services.ai.providers import get_provider
from app.services.intelligence.common import ask
from app.services.marketing.common import GUARANTEE, Claimable, detect_claims, guarantee_issues, marketing_sources, source_text, str_list

SOCIAL_KINDS = {"single_image_post", "carousel", "reel_script", "short_video_script", "long_video_script", "caption",
                "product_announcement", "educational", "case_study", "promotional", "seasonal"}
SEO_KINDS = {"keyword_cluster", "topic_map", "article_outline", "blog_article", "product_description", "industry_landing_page",
             "location_landing_page", "meta_tags", "faq", "internal_links"}
SOCIAL_PLATFORMS = {"instagram", "facebook", "linkedin", "youtube", "youtube_shorts"}
# Published limits (characters). Instagram also caps hashtags at 30 per post.
LIMITS = {"instagram": 2200, "facebook": 63206, "linkedin": 3000, "youtube": 5000, "youtube_shorts": 5000, "website": 60000}
VIDEO_KINDS = {"reel_script", "short_video_script", "long_video_script"}


class Draft(Claimable):
    title: str = Field(max_length=300)
    body: str = Field(default="", max_length=60000)
    hashtags: list[str] = Field(default_factory=list)
    cta: str | None = Field(default=None, max_length=300)
    slides: list[str] = Field(default_factory=list)  # carousel
    scenes: list[dict] = Field(default_factory=list)  # video scripts: [{time, visual, voiceover, on_screen_text}]
    creative_brief: str | None = Field(default=None, max_length=2000)
    # SEO parts
    keywords: list[str] = Field(default_factory=list)
    outline: list[str] = Field(default_factory=list)
    meta_title: str | None = Field(default=None, max_length=200)
    meta_description: str | None = Field(default=None, max_length=400)
    faqs: list[dict] = Field(default_factory=list)  # [{q, a}]
    internal_links: list[dict] = Field(default_factory=list)  # [{anchor, target}]

    @field_validator("hashtags", "slides", "keywords", "outline", mode="before")
    @classmethod
    def _l(cls, v):
        return str_list(v, 40, 600)

    @field_validator("scenes", "faqs", "internal_links", mode="before")
    @classmethod
    def _d(cls, v):
        return [x for x in (v or []) if isinstance(x, dict)][:30]


class Out(BaseModel):
    items: list[Draft] = Field(default_factory=list, max_length=10)


SHAPE = """{"items": [{"title": "...", "body": "caption / article / script text", "hashtags": ["#..."], "cta": "...",
  "slides": ["carousel slide text"], "scenes": [{"time": "0-3s", "visual": "...", "voiceover": "...", "on_screen_text": "..."}],
  "creative_brief": "what the visual should show, using only approved brand assets",
  "keywords": ["..."], "outline": ["H2 ..."], "meta_title": "...", "meta_description": "...",
  "faqs": [{"q": "...", "a": "..."}], "internal_links": [{"anchor": "...", "target": "existing page URL from the sources"}],
  "claims_to_check": ["every factual statement a person must verify before publishing"]}]}"""

RULES = ("Use only facts in the sources about the client and its products. Never invent certifications, awards, endorsements, "
         "customer names, statistics, prices, delivery times or comparisons with competitors. If a claim would help but is "
         "not in the sources, write around it or add it to claims_to_check as 'needs confirmation'. Never promise results. "
         "Write for the buyer profile's industry, application and problem. List in claims_to_check every product fact you used.")

KIND_HINTS = {
    "single_image_post": "one feed post: caption, hashtags, CTA, creative brief for one image",
    "carousel": "5-8 slides (slides list) plus caption, hashtags, CTA",
    "reel_script": "15-30 second vertical video: scenes with timings, on-screen text, voiceover, caption",
    "short_video_script": "under 60 seconds (YouTube Shorts): scenes, title, description",
    "long_video_script": "5-10 minute YouTube video: title, description, scenes as chapters",
    "caption": "caption only, with hashtags and CTA",
    "product_announcement": "announce a product using only its recorded facts",
    "educational": "teach the buyer about the application or problem; product mention is secondary",
    "case_study": "a case-study TEMPLATE with [placeholders] for customer, results and quotes; never invent them",
    "promotional": "promotional post; no price or discount unless the sources state it",
    "seasonal": "festival or seasonal post tied to the buyer's industry; name the occasion given",
    "keyword_cluster": "keyword clusters grouped by intent (keywords list, outline = cluster names); no search volumes",
    "topic_map": "pillar and cluster topics (outline) linked to the products and applications",
    "article_outline": "H2/H3 outline, meta title and description, FAQs",
    "blog_article": "an 800-1500 word article in body (markdown), meta title/description, FAQs, internal links",
    "product_description": "product page copy from the product record only, meta title/description",
    "industry_landing_page": "landing page for one industry: sections in outline, copy in body, FAQs, CTA",
    "location_landing_page": "landing page for one location: only real presence or service area from the sources",
    "meta_tags": "meta title (<= 60 chars) and description (<= 155 chars) for the given page",
    "faq": "8-12 FAQs with answers from the sources",
    "internal_links": "internal link suggestions between existing pages found in the sources",
}


def _finish(d: Draft, platform: str | None, srcs) -> tuple[str, dict, list[str]]:
    body = d.body or ""
    removed = guarantee_issues(body, d.title, d.cta or "")
    if removed:
        body = GUARANTEE.sub("[removed: no outcome is promised]", body)
    tags = []
    for h in d.hashtags:
        h = "#" + re.sub(r"[^\w]", "", h.lstrip("#"))
        if len(h) > 1 and h.lower() not in {t.lower() for t in tags}:
            tags.append(h)
    if platform == "instagram":
        tags = tags[:30]
    limit = LIMITS.get(platform or "website", 60000)
    note = None
    caption_len = len(body) + (len(" ".join(tags)) + 2 if tags else 0)
    if caption_len > limit:
        body = body[: max(0, limit - (len(" ".join(tags)) + 2 if tags else 0) - 1)].rstrip() + "…"
        note = f"Cut to the {platform} limit of {limit} characters"
    claims = list(dict.fromkeys(d.claims_to_check + detect_claims(" ".join([d.title, body, d.cta or "", " ".join(d.slides),
                                                                            " ".join(str(s.get("voiceover", "")) for s in d.scenes)]), srcs)))
    data = {k: v for k, v in {"hashtags": tags, "cta": d.cta, "slides": d.slides, "scenes": d.scenes, "creative_brief": d.creative_brief,
                              "keywords": d.keywords, "outline": d.outline, "meta_title": (d.meta_title or "")[:60] or None,
                              "meta_description": (d.meta_description or "")[:160] or None, "faqs": d.faqs,
                              "internal_links": d.internal_links, "limit_note": note,
                              "removed_promises": sorted(set(removed)) or None}.items() if v not in (None, [], "")}
    return body, data, claims


def generate(db, tenant_id: str, client, user_id: str | None, *, studio: str, kind: str, platform: str | None,
             product_id: str | None, persona_id: str | None, topic: str | None, count: int = 1, tone: str | None = None,
             campaign_id: str | None = None, extra: str | None = None) -> list[ContentItem]:
    if studio == "social" and (kind not in SOCIAL_KINDS or platform not in SOCIAL_PLATFORMS):
        raise ValueError("Choose a social content type and one of Instagram, Facebook, LinkedIn, YouTube, YouTube Shorts")
    if studio == "seo" and kind not in SEO_KINDS:
        raise ValueError("Choose an SEO content type")
    if platform in ("youtube", "youtube_shorts") and kind in ("carousel", "single_image_post"):
        raise ValueError("YouTube takes video scripts, not image posts")
    product = db.get(Product, product_id) if product_id else None
    if product_id and (not product or product.client_id != client.id or product.tenant_id != tenant_id):
        raise ValueError("Product not found for this client")
    persona = db.get(BuyerPersona, persona_id) if persona_id else None
    if persona_id and (not persona or persona.client_id != client.id or persona.tenant_id != tenant_id):
        raise ValueError("Buyer profile not found for this client")
    provider = get_provider("fast" if studio == "social" else "analysis")
    srcs = marketing_sources(db, tenant_id, client, [product.id] if product else None)
    task = (f"Write {count} {kind.replace('_', ' ')} draft(s) for {platform or 'the client website'}: {KIND_HINTS.get(kind, '')}. "
            + (f"Product: {product.name} (source_id=product:{product.id}). " if product else "")
            + (f"Buyer profile: {persona.name} (source_id=persona:{persona.id}). " if persona else "")
            + (f"Topic / angle: {topic}. " if topic else "") + (f"Tone: {tone}. " if tone else "")
            + (f"{extra} " if extra else "") + RULES)
    out: Out = ask(provider, Out, task, SHAPE, source_text(srcs, provider.max_context_chars))
    made = []
    for d in out.items[: max(1, min(count, 10))]:
        body, data, claims = _finish(d, platform, srcs)
        it = ContentItem(tenant_id=tenant_id, client_id=client.id, campaign_id=campaign_id, product_id=product.id if product else None,
                         persona_id=persona.id if persona else None, studio=studio, kind=kind, platform=platform,
                         title=d.title.strip()[:300] or kind.replace("_", " ").title(), body=body, data=data, claims_to_check=claims,
                         status="ai_generated", origin="ai", provider=provider.name, model=provider.model, created_by=user_id)
        db.add(it)
        made.append(it)
    db.flush()
    return made
