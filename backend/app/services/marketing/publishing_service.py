"""Publishing through official APIs only (no browser automation, no scraping, no workarounds).

Adapters:
  facebook   Facebook Page posts via the Graph API (/{page-id}/feed). Needs a Meta app with pages_manage_posts
             (App Review) and a Page role allowing CREATE_CONTENT.
  instagram  Instagram professional accounts linked to a Page (Content Publishing API: /{ig-id}/media then
             /media_publish). Needs a public image URL; text-only posts are not possible on Instagram.
  linkedin   Posts API (POST /rest/posts) as the connected member (w_member_social, self-serve) or a Page
             (w_organization_social via the Community Management API, reviewed by LinkedIn).
  youtube    Not automated: uploading needs the YouTube Data API with an audited project for public videos.
             Publish on YouTube yourself, then mark the item published with its URL.

Tokens are encrypted with Fernet (MARKETING_TOKEN_KEY) and never leave the server. Every publish re-checks:
the item is approved/scheduled, the approved version is the current version, the account is connected,
not expired, has publishing permission and matches the platform.
"""
from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import ActivityLog, ContentItem, PublishingJob, SocialAccount
from app.services.marketing.common import now

log = logging.getLogger(__name__)
AUTOMATED = {"facebook", "instagram", "linkedin"}
META_SCOPES = ["pages_show_list", "pages_manage_posts", "pages_read_engagement", "instagram_basic", "instagram_content_publish",
               "business_management"]
LINKEDIN_SCOPES = ["openid", "profile", "w_member_social"]
PLATFORM_NOTES = {
    "facebook": "Graph API. Publishing needs pages_manage_posts (Meta App Review) and a Page task of CREATE_CONTENT. Page rate limit: 4,800 x engaged users per 24 h.",
    "instagram": "Content Publishing API for professional accounts linked to a Page. Needs a public image URL; 100 API-published posts per 24 h.",
    "linkedin": "Posts API. Member posting is self-serve (w_member_social); Page posting needs the Community Management API (LinkedIn review).",
    "youtube": "Upload is not automated: the YouTube Data API needs an audited project for public uploads. Publish manually and record the URL.",
}


class PublishError(RuntimeError):
    def __init__(self, msg: str, retryable: bool = False):
        super().__init__(msg)
        self.retryable = retryable


def http_client() -> httpx.Client:  # patched in tests
    return httpx.Client(timeout=get_settings().marketing_http_timeout)


# ------------------------------------------------------------------ token encryption
def _fernet() -> Fernet:
    key = get_settings().marketing_token_key
    if not key:
        raise PublishError("MARKETING_TOKEN_KEY is not set on the server, so account tokens cannot be stored safely.")
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as e:
        raise PublishError("MARKETING_TOKEN_KEY is not a valid Fernet key") from e


def encrypt(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def decrypt(blob: str | None) -> str:
    if not blob:
        raise PublishError("The account has no stored token; connect it again")
    try:
        return _fernet().decrypt(blob.encode()).decode()
    except InvalidToken as e:
        raise PublishError("Stored token cannot be decrypted (key changed?); connect the account again") from e


# ------------------------------------------------------------------ status
def configured(platform: str) -> bool:
    s = get_settings()
    if platform in ("facebook", "instagram"):
        return bool(s.meta_app_id and s.meta_app_secret and s.marketing_token_key)
    if platform == "linkedin":
        return bool(s.linkedin_client_id and s.linkedin_client_secret and s.marketing_token_key)
    return False


def status() -> list[dict]:
    s = get_settings()
    return [{"platform": p, "automated": p in AUTOMATED, "configured": configured(p), "note": PLATFORM_NOTES[p],
             "missing": ([] if configured(p) else
                         (["META_APP_ID", "META_APP_SECRET"] if p in ("facebook", "instagram") else
                          ["LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET"] if p == "linkedin" else ["not automated"])
                         + ([] if s.marketing_token_key or p == "youtube" else ["MARKETING_TOKEN_KEY"]))}
            for p in ("facebook", "instagram", "linkedin", "youtube")]


def redirect_uri(platform: str) -> str:
    oauth = "meta" if platform in ("facebook", "instagram") else platform
    return f"{get_settings().public_api_url.rstrip('/')}/api/v1/marketing/oauth/{oauth}/callback"


# ------------------------------------------------------------------ OAuth
def authorize_url(platform: str, state: str) -> str:
    s = get_settings()
    if platform in ("facebook", "instagram"):
        return f"https://www.facebook.com/{s.meta_graph_version}/dialog/oauth?" + urlencode(
            {"client_id": s.meta_app_id, "redirect_uri": redirect_uri("facebook"), "state": state, "scope": ",".join(META_SCOPES),
             "response_type": "code"})
    if platform == "linkedin":
        return "https://www.linkedin.com/oauth/v2/authorization?" + urlencode(
            {"response_type": "code", "client_id": s.linkedin_client_id, "redirect_uri": redirect_uri("linkedin"), "state": state,
             "scope": " ".join(LINKEDIN_SCOPES)})
    raise PublishError(f"{platform} accounts cannot be connected in this phase")


def new_state() -> str:
    return secrets.token_urlsafe(32)


def _json(r: httpx.Response, what: str) -> dict:
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code >= 400:
        err = body.get("error") if isinstance(body, dict) else None
        msg = (err.get("message") if isinstance(err, dict) else body.get("message") or body.get("error_description")) if isinstance(body, dict) else None
        raise PublishError(f"{what} failed ({r.status_code}): {msg or r.text[:200]}", retryable=r.status_code in (429,) or r.status_code >= 500)
    return body


def meta_callback(db, pending: SocialAccount, code: str) -> list[SocialAccount]:
    """Exchange the code, list the Pages the user manages and their linked Instagram accounts."""
    s = get_settings()
    g = f"https://graph.facebook.com/{s.meta_graph_version}"
    with http_client() as c:
        tok = _json(c.get(f"{g}/oauth/access_token", params={"client_id": s.meta_app_id, "client_secret": s.meta_app_secret,
                                                               "redirect_uri": redirect_uri("facebook"), "code": code}), "Token exchange")
        user_token = tok["access_token"]
        perms = _json(c.get(f"{g}/me/permissions", params={"access_token": user_token}), "Permission check").get("data", [])
        granted = sorted(p["permission"] for p in perms if p.get("status") == "granted")
        pages = _json(c.get(f"{g}/me/accounts", params={"access_token": user_token,
                                                         "fields": "id,name,access_token,tasks,instagram_business_account{id,username}"}),
                      "Listing Pages").get("data", [])
    if not pages:
        raise PublishError("No Facebook Pages were shared with the app. Choose at least one Page when connecting.")
    made = []
    for pg in pages:
        tasks = pg.get("tasks") or []
        can_fb = "pages_manage_posts" in granted and "CREATE_CONTENT" in tasks
        targets = [("facebook", pg["id"], pg.get("name") or pg["id"], can_fb, "pages_manage_posts" if not can_fb else None)]
        ig = pg.get("instagram_business_account")
        if ig:
            can_ig = "instagram_content_publish" in granted and "CREATE_CONTENT" in tasks
            targets.append(("instagram", ig["id"], "@" + (ig.get("username") or ig["id"]), can_ig, None if can_ig else "instagram_content_publish"))
        for platform, ext, name, can, missing in targets:
            acct = db.scalar(select(SocialAccount).where(SocialAccount.client_id == pending.client_id, SocialAccount.platform == platform,
                                                         SocialAccount.external_id == ext))
            if acct is None:
                acct = SocialAccount(tenant_id=pending.tenant_id, client_id=pending.client_id, platform=platform, external_id=ext, account_name=name)
                db.add(acct)
            acct.account_name, acct.status, acct.token_encrypted = name, "connected", encrypt(pg["access_token"])
            acct.scopes, acct.connected_by, acct.connected_at, acct.last_error, acct.token_expires_at = granted, pending.connected_by, now(), None, None
            acct.permissions = {"can_publish": can, "can_read_insights": "pages_read_engagement" in granted, "page_tasks": tasks,
                                "missing": [m for m in [missing] if m], "checked_at": now().isoformat()}
            made.append(acct)
    db.delete(pending)
    return made


def linkedin_callback(db, pending: SocialAccount, code: str) -> list[SocialAccount]:
    s = get_settings()
    with http_client() as c:
        tok = _json(c.post("https://www.linkedin.com/oauth/v2/accessToken", data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri("linkedin"),
            "client_id": s.linkedin_client_id, "client_secret": s.linkedin_client_secret}), "Token exchange")
        me = _json(c.get("https://api.linkedin.com/v2/userinfo", headers={"Authorization": f"Bearer {tok['access_token']}"}), "Profile lookup")
    scopes = sorted((tok.get("scope") or "").replace(",", " ").split())
    urn = f"urn:li:person:{me['sub']}"
    acct = db.scalar(select(SocialAccount).where(SocialAccount.client_id == pending.client_id, SocialAccount.platform == "linkedin",
                                                 SocialAccount.external_id == urn))
    if acct is None:
        acct = pending
    else:
        db.delete(pending)
    acct.platform, acct.external_id, acct.account_name = "linkedin", urn, me.get("name") or "LinkedIn member"
    acct.status, acct.token_encrypted, acct.scopes, acct.oauth_state = "connected", encrypt(tok["access_token"]), scopes, None
    acct.token_expires_at = now() + timedelta(seconds=int(tok.get("expires_in") or 0)) if tok.get("expires_in") else None
    acct.connected_at, acct.last_error = now(), None
    acct.permissions = {"can_publish": "w_member_social" in scopes, "can_read_insights": False,
                        "missing": [] if "w_member_social" in scopes else ["w_member_social"], "checked_at": now().isoformat(),
                        "note": "Analytics need the Community Management API."}
    return [acct]


# ------------------------------------------------------------------ publishing
def _li_escape(text: str) -> str:
    return re.sub(r"([\\|{}@\[\]()<>#*_~])", r"\\\1", text)


def compose(item: ContentItem) -> str:
    tags = " ".join((item.data or {}).get("hashtags") or [])
    cta = (item.data or {}).get("cta")
    return "\n\n".join(x for x in [item.body or item.title, cta, tags] if x)


def publish(acct: SocialAccount, item: ContentItem) -> tuple[str, str | None]:
    """Returns (external_post_id, url). Raises PublishError."""
    s = get_settings()
    token = decrypt(acct.token_encrypted)
    text = compose(item)
    with http_client() as c:
        if acct.platform == "facebook":
            payload = {"message": text, "access_token": token}
            link = (item.data or {}).get("link")
            if link:
                payload["link"] = link
            body = _json(c.post(f"https://graph.facebook.com/{s.meta_graph_version}/{acct.external_id}/feed", data=payload), "Facebook post")
            pid = body.get("id")
            return pid, f"https://www.facebook.com/{pid}" if pid else None
        if acct.platform == "instagram":
            image = (item.data or {}).get("image_url")
            if not image or not str(image).startswith("https://"):
                raise PublishError("Instagram needs a public https image URL on the item (data.image_url) from an approved asset")
            g = f"https://graph.facebook.com/{s.meta_graph_version}/{acct.external_id}"
            cont = _json(c.post(f"{g}/media", data={"image_url": image, "caption": text[:2200], "access_token": token}), "Instagram media")
            body = _json(c.post(f"{g}/media_publish", data={"creation_id": cont["id"], "access_token": token}), "Instagram publish")
            return body.get("id"), None
        if acct.platform == "linkedin":
            r = c.post("https://api.linkedin.com/rest/posts", headers={
                "Authorization": f"Bearer {token}", "Linkedin-Version": s.linkedin_api_version, "X-Restli-Protocol-Version": "2.0.0",
                "Content-Type": "application/json"}, json={
                "author": acct.external_id, "commentary": _li_escape(text[:3000]), "visibility": "PUBLIC",
                "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
                "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False})
            if r.status_code != 201:
                _json(r, "LinkedIn post")
                raise PublishError(f"LinkedIn post failed ({r.status_code})")
            urn = r.headers.get("x-restli-id")
            return urn, f"https://www.linkedin.com/feed/update/{urn}/" if urn else None
    raise PublishError(f"Publishing to {acct.platform} is not automated")


def check_ready(item: ContentItem, acct: SocialAccount | None) -> None:
    if item.status not in ("approved", "scheduled"):
        raise PublishError(f"Only approved content can be published (this item is {item.status.replace('_', ' ')})")
    if not item.approved_at:
        raise PublishError("This item has no recorded approval")
    if acct is None:
        raise PublishError("Choose a connected account")
    want = "facebook" if item.platform == "facebook" else item.platform
    if acct.platform != want:
        raise PublishError(f"This item is for {item.platform}; the account is {acct.platform}")
    if acct.platform not in AUTOMATED:
        raise PublishError(f"Publishing to {acct.platform} is not automated; publish it yourself and mark it published")
    if acct.status != "connected":
        raise PublishError(f"The {acct.platform} account is {acct.status.replace('_', ' ')}; connect it again")
    if acct.token_expires_at and acct.token_expires_at.replace(tzinfo=acct.token_expires_at.tzinfo or timezone.utc) <= now():
        raise PublishError("The account token has expired; connect it again")
    if not (acct.permissions or {}).get("can_publish"):
        missing = ", ".join((acct.permissions or {}).get("missing") or []) or "publishing permission"
        raise PublishError(f"The account lacks permission to publish ({missing})")


def run_publishing_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        run_job(db, job_id)
    finally:
        db.close()


def run_job(db, job_id: str) -> PublishingJob | None:
    job = db.get(PublishingJob, job_id)
    if job is None or job.status not in ("queued",):
        return job
    item = db.get(ContentItem, job.content_item_id)
    acct = db.get(SocialAccount, job.social_account_id) if job.social_account_id else None
    job.status, job.attempts = "publishing", job.attempts + 1
    item.publishing_status = "publishing"
    db.commit()
    try:
        if item.version != job.content_version:
            raise PublishError("The content changed after it was approved; it needs approval again")
        check_ready(item, acct)
        pid, url = publish(acct, item)
        job.status, job.external_post_id, job.external_url, job.published_at, job.error = "published", pid, url, now(), None
        item.status, item.publishing_status, item.published_at = "published", "published", now()
        item.data = {**(item.data or {}), "external_url": url, "external_post_id": pid}
        db.add(ActivityLog(tenant_id=job.tenant_id, user_id=job.requested_by, action="marketing.published", entity_type="content",
                           entity_id=item.id, summary=f"Published '{item.title}' to {job.platform}", meta={"client_id": item.client_id, "url": url}))
    except PublishError as e:
        job.status, job.error = "failed", str(e)[:1000]
        item.status, item.publishing_status = "failed", "failed"
        if acct and ("expired" in str(e) or "401" in str(e) or "190" in str(e)):
            acct.status, acct.last_error = "expired", str(e)[:500]
        db.add(ActivityLog(tenant_id=job.tenant_id, user_id=job.requested_by, action="marketing.publish_failed", entity_type="content",
                           entity_id=item.id, summary=f"Publishing '{item.title}' failed: {str(e)[:150]}", meta={"client_id": item.client_id}))
    except httpx.HTTPError as e:
        job.status, job.error = "failed", f"Network error: {type(e).__name__}"
        item.status, item.publishing_status = "failed", "failed"
    db.commit()
    return job


def due_jobs(db) -> list[PublishingJob]:
    return list(db.scalars(select(PublishingJob).where(PublishingJob.status == "queued", PublishingJob.scheduled_at.is_not(None),
                                                       PublishingJob.scheduled_at <= datetime.now(timezone.utc))).all())
