"""Marketing analytics: only what a provider API returns, plus clearly labelled calculations from those values.

Implemented reads (official APIs, the connected account's own token):
  facebook   post reactions, comments and shares       (Graph API post fields)
  instagram  media like_count and comments_count        (Instagram Graph API)
Not available in this phase (shown as such, never estimated): LinkedIn post statistics (Community Management
API), YouTube Analytics, GA4 sessions/conversions, ad spend, CPL, ROAS (no ad-account adapter).
Calculated (source="calculated"): engagements = sum of the platform's reaction/like, comment and share counts.
"""
from __future__ import annotations

from sqlalchemy import select

from app.core.config import get_settings
from app.models import CampaignMetric, ContentItem, PublishingJob, SocialAccount
from app.services.marketing.common import now
from app.services.marketing import publishing_service as pub
from app.services.marketing.publishing_service import PublishError, _json, decrypt

UNAVAILABLE = {
    "linkedin": "Post statistics need LinkedIn's Community Management API (reviewed access).",
    "youtube": "Needs the YouTube Analytics API (not connected in this phase).",
    "website": "Sessions, leads and conversions need GA4 (not connected in this phase).",
    "ads": "Ad spend, CPL, conversion rate and ROAS need an authorised ad-account connection (none in this phase).",
}


def _fetch(acct: SocialAccount, post_id: str) -> dict[str, float]:
    s = get_settings()
    token = decrypt(acct.token_encrypted)
    g = f"https://graph.facebook.com/{s.meta_graph_version}/{post_id}"
    with pub.http_client() as c:
        if acct.platform == "facebook":
            b = _json(c.get(g, params={"access_token": token, "fields": "shares,reactions.summary(total_count).limit(0),comments.summary(total_count).limit(0)"}),
                      "Facebook post metrics")
            return {"reactions": float(((b.get("reactions") or {}).get("summary") or {}).get("total_count") or 0),
                    "comments": float(((b.get("comments") or {}).get("summary") or {}).get("total_count") or 0),
                    "shares": float((b.get("shares") or {}).get("count") or 0)}
        if acct.platform == "instagram":
            b = _json(c.get(g, params={"access_token": token, "fields": "like_count,comments_count"}), "Instagram media metrics")
            return {"likes": float(b.get("like_count") or 0), "comments": float(b.get("comments_count") or 0)}
    raise PublishError(UNAVAILABLE.get(acct.platform, "Not available"))


def refresh(db, tenant_id: str, client_id: str) -> dict:
    jobs = db.scalars(select(PublishingJob).where(PublishingJob.tenant_id == tenant_id, PublishingJob.client_id == client_id,
                                                  PublishingJob.status == "published", PublishingJob.external_post_id.is_not(None))).all()
    stored, errors, skipped = 0, [], []
    t = now()
    for j in jobs:
        acct = db.get(SocialAccount, j.social_account_id) if j.social_account_id else None
        if not acct or acct.platform not in ("facebook", "instagram"):
            skipped.append(f"{j.platform}: {UNAVAILABLE.get(j.platform, 'not available')}")
            continue
        if acct.status != "connected" or not (acct.permissions or {}).get("can_read_insights", True):
            errors.append(f"{acct.account_name}: account not connected or lacks read permission")
            continue
        try:
            vals = _fetch(acct, j.external_post_id)
        except PublishError as e:
            errors.append(str(e)[:200])
            continue
        for k, v in vals.items():
            db.add(CampaignMetric(tenant_id=tenant_id, client_id=client_id, source="platform", platform=acct.platform, entity_type="post",
                                  entity_id=j.content_item_id, external_id=j.external_post_id, metric=k, value=v, retrieved_at=t))
        db.add(CampaignMetric(tenant_id=tenant_id, client_id=client_id, source="calculated", platform=acct.platform, entity_type="post",
                              entity_id=j.content_item_id, external_id=j.external_post_id, metric="engagements", value=sum(vals.values()),
                              retrieved_at=t, formula=" + ".join(vals.keys())))
        stored += 1
    return {"posts_updated": stored, "errors": errors, "not_available": sorted(set(skipped)), "notes": UNAVAILABLE}


def latest(db, tenant_id: str, client_id: str) -> list[dict]:
    rows = db.scalars(select(CampaignMetric).where(CampaignMetric.tenant_id == tenant_id, CampaignMetric.client_id == client_id)
                      .order_by(CampaignMetric.retrieved_at.desc())).all()
    seen, out = set(), []
    titles = {i.id: i.title for i in db.scalars(select(ContentItem).where(ContentItem.client_id == client_id)).all()}
    for m in rows:
        k = (m.entity_type, m.entity_id, m.metric, m.source)
        if k in seen:
            continue
        seen.add(k)
        out.append({"source": m.source, "platform": m.platform, "entity_type": m.entity_type, "entity_id": m.entity_id,
                    "title": titles.get(m.entity_id), "external_id": m.external_id, "metric": m.metric, "value": m.value,
                    "formula": m.formula, "retrieved_at": m.retrieved_at})
    return out
