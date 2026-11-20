"""Phase 5 acceptance tests: strategy, budget, content studios, approvals, brand assets, ads planner, OAuth,
publishing, analytics, reports, tenancy.

A scripted fake AI stands in for Gemini/Groq and deliberately returns things the guardrails must catch: a fact
with a quote that is not in the sources, a guarantee, an invented certification, too many hashtags, ad
headlines over the platform limit. Meta and LinkedIn are an in-memory fake (httpx.MockTransport); no real
account is contacted, and every metric asserted comes from the fake API's responses."""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from cryptography.fernet import Fernet

from app.core.config import get_settings
from app.services.ai import providers
from app.services.marketing import publishing_service
from tests.conftest import register

DESC = "AquaPure makes RO water purification plants for food processing units in Karnataka."


class FakeAI:
    name, model, max_context_chars = "fake", "fake-1", 50_000

    def __init__(self):
        self.calls = []

    def generate_json(self, system, prompt):
        if "marketing strategy" in prompt:
            self.calls.append("strategy")
            secs = [{"key": k, "summary": f"{k} summary", "assumptions": ["Sales team can follow up within 48 hours"],
                     "recommendations": [f"Do {k} well"]} for k in
                    ["executive_summary", "positioning", "brand_messaging", "target_audience", "channel_strategy", "seo", "social_media",
                     "paid_ads", "content", "lead_generation", "calendar", "budget_allocation", "kpis", "reporting"]]
            secs[0]["facts"] = [{"text": "Makes RO plants for food processors", "source_id": "client",
                                 "quote": "RO water purification plants for food processing units"},
                                {"text": "ISO 9001 certified", "source_id": "client", "quote": "ISO 9001 certified since 2001"}]
            secs[0]["recommendations"].append("This plan delivers guaranteed leads every month")
            secs.append({"key": "made_up_section", "summary": "x"})
            return {"sections": secs}
        if "campaign." in prompt and "Ads" in prompt:
            self.calls.append("ads")
            return {"name": "RO plants – food processors", "objective": "leads", "audience": {"industries": ["Food processing"]},
                    "headlines": ["Clean process water for food plants, guaranteed results", "RO plants for dairies"],
                    "ad_copy": ["Talk to AquaPure about RO plants for your food processing unit."], "bidding": "Maximise conversions",
                    "conversion_tracking": "Lead form submit", "ab_tests": ["Headline A vs B"]}
        self.calls.append("content")
        if "blog article" in prompt:
            return {"items": [{"title": "Choosing an RO plant for a food processing unit", "body": "## Why water quality matters\nText.",
                               "meta_title": "RO plants for food processing: a buyer's guide that is far too long for sixty chars",
                               "meta_description": "How to choose", "faqs": [{"q": "What size?", "a": "Depends on flow."}]}]}
        return {"items": [{"title": "RO plants for food processors",
                           "body": "AquaPure RO plants are ISO 9001 certified and trusted by 500 customers. Guaranteed results!",
                           "hashtags": [f"tag{i}" for i in range(40)], "cta": "Ask for a quote",
                           "slides": ["Problem", "Solution"], "claims_to_check": ["Plant capacity"]}]}


@pytest.fixture
def ai():
    p = FakeAI()
    for purpose in ("analysis", "fast"):
        providers.set_override(purpose, p)
    yield p
    for purpose in ("analysis", "fast"):
        providers.set_override(purpose, None)


class FakeSocial:
    def __init__(self):
        self.posts, self.headers = [], []
        self.tasks = ["CREATE_CONTENT", "ANALYZE"]
        self.fail_publish = False

    def handler(self, r: httpx.Request) -> httpx.Response:
        u = r.url
        if u.host == "graph.facebook.com":
            path = u.path.split("/", 2)[2] if u.path.count("/") >= 2 else ""
            if path == "oauth/access_token":
                assert u.params["code"] == "good-code" and u.params["client_secret"] == "meta-secret"
                return httpx.Response(200, json={"access_token": "USER-TOKEN"})
            if path == "me/permissions":
                return httpx.Response(200, json={"data": [{"permission": p, "status": "granted"} for p in
                                                          ("pages_show_list", "pages_manage_posts", "pages_read_engagement", "instagram_basic")]})
            if path == "me/accounts":
                return httpx.Response(200, json={"data": [{"id": "111", "name": "AquaPure Page", "access_token": "PAGE-TOKEN", "tasks": self.tasks,
                                                           "instagram_business_account": {"id": "999", "username": "aquapure"}}]})
            if path == "111/feed" and r.method == "POST":
                body = dict(x.split("=", 1) for x in r.content.decode().split("&"))
                assert body["access_token"] == "PAGE-TOKEN"
                if self.fail_publish:
                    return httpx.Response(400, json={"error": {"message": "(#200) Permissions error", "code": 200}})
                self.posts.append(("facebook", httpx.QueryParams(r.content.decode())["message"]))
                return httpx.Response(200, json={"id": "111_222"})
            if path == "111_222":
                return httpx.Response(200, json={"shares": {"count": 3}, "reactions": {"summary": {"total_count": 12}},
                                                 "comments": {"summary": {"total_count": 4}}})
        if u.host == "www.linkedin.com" and u.path == "/oauth/v2/accessToken":
            return httpx.Response(200, json={"access_token": "LI-TOKEN", "expires_in": 5184000, "scope": "openid,profile,w_member_social"})
        if u.host == "api.linkedin.com" and u.path == "/v2/userinfo":
            return httpx.Response(200, json={"sub": "abc123", "name": "Priya Rao"})
        if u.host == "api.linkedin.com" and u.path == "/rest/posts":
            self.headers.append(dict(r.headers))
            self.posts.append(("linkedin", json.loads(r.content)["commentary"]))
            return httpx.Response(201, headers={"x-restli-id": "urn:li:share:7"})
        return httpx.Response(404, json={"error": {"message": f"unexpected {u}"}})


@pytest.fixture
def social(monkeypatch):
    fs = FakeSocial()
    monkeypatch.setattr(publishing_service, "http_client", lambda: httpx.Client(transport=httpx.MockTransport(fs.handler)))
    s = get_settings()
    for k, v in {"meta_app_id": "meta-app", "meta_app_secret": "meta-secret", "linkedin_client_id": "li-app",
                 "linkedin_client_secret": "li-secret", "marketing_token_key": Fernet.generate_key().decode()}.items():
        monkeypatch.setattr(s, k, v)
    return fs


def setup(api, h, budget=100000):
    c = api.post("/api/v1/clients", headers=h, json={"company_name": "AquaPure", "description": DESC, "marketing_budget": budget}).json()
    pid = api.post("/api/v1/products", headers=h, json={"client_id": c["id"], "name": "RO Plant 500 LPH"}).json()["id"]
    return c["id"], pid


def approve(api, h, path, note="Claims checked against the product record"):
    assert api.post(f"{path}/review", headers=h, json={"action": "submit"}).status_code == 200
    r = api.post(f"{path}/review", headers=h, json={"action": "approve", "note": note})
    assert r.status_code == 200, r.text
    return r.json()


def test_strategy_grounded_and_reviewed(api, ai):
    h = register(api)
    cid, pid = setup(api, h)
    providers.set_override("analysis", None)
    providers.set_override("fast", None)
    assert api.post(f"/api/v1/clients/{cid}/marketing/strategies", headers=h, json={"title": "FY27 plan"}).status_code == 409
    providers.set_override("analysis", ai)
    r = api.post(f"/api/v1/clients/{cid}/marketing/strategies", headers=h, json={"title": "FY27 plan", "objectives": "More dealer enquiries",
                                                                                  "monthly_budget": 100000, "sales_capacity": "2 sales engineers"})
    assert r.status_code == 201
    s = api.get(f"/api/v1/marketing/strategies/{r.json()['id']}", headers=h).json()
    assert s["job_status"] == "completed" and s["status"] == "ai_generated", s["error"]
    ex = s["sections"]["executive_summary"]
    assert [f["text"] for f in ex["facts"]] == ["Makes RO plants for food processors"]  # quote checked against the client record
    assert any("Unverified" in a and "ISO 9001" in a for a in ex["assumptions"])  # invented fact demoted
    assert not any("guaranteed" in x.lower() for x in ex["recommendations"]) and "Removed outcome promises: guaranteed" in s["disclaimer"]
    assert "made_up_section" not in s["sections"] and len(s["sections"]) == 14
    assert "No revenue, lead or performance outcome is promised" in s["disclaimer"]
    path = f"/api/v1/marketing/strategies/{s['id']}"
    assert api.post(f"{path}/review", headers=h, json={"action": "approve"}).status_code == 409  # must be submitted first
    assert approve(api, h, path)["status"] == "approved"
    assert api.patch(path, headers=h, json={"sections": {"kpis": {"recommendations": ["We guarantee 50 leads"]}}}).status_code == 422
    e = api.patch(path, headers=h, json={"sections": {"kpis": {"summary": "Targets to agree with the client"}}, "note": "KPI wording"}).json()
    assert e["status"] == "internal_review" and e["version"] == 2 and e["approved_at"] is None
    hist = api.get(f"/api/v1/marketing/strategy/{s['id']}/history", headers=h).json()
    assert hist["revisions"][0]["note"] == "KPI wording" and any(a["status"] == "approved" for a in hist["approvals"])


def test_budget_planner(api):
    h = register(api)
    cid, _ = setup(api, h, budget=200000)
    b = api.post(f"/api/v1/clients/{cid}/marketing/budgets", headers=h, json={"name": "Q1"}).json()
    assert b["summary"]["monthly_total"] == 200000 and b["summary"]["quarterly_total"] == 600000
    assert b["summary"]["by_cost_kind"]["ad_spend"] == 70000  # paid search 20% + social ads 15%
    g = api.post(f"/api/v1/marketing/budgets/{b['id']}/scenario?scenario=growth", headers=h).json()
    assert g["summary"]["monthly_total"] == 280000 and g["scenario"] == "growth"
    c = api.post(f"/api/v1/marketing/budgets/{g['id']}/scenario?scenario=conservative", headers=h).json()
    assert c["summary"]["monthly_total"] == 140000
    lines = b["lines"]
    lines[0]["amount"] = -5
    assert api.patch(f"/api/v1/marketing/budgets/{b['id']}", headers=h, json={"lines": lines}).status_code == 422
    lines[0]["amount"] = 50000
    e = api.patch(f"/api/v1/marketing/budgets/{b['id']}", headers=h, json={"lines": lines, "quarterly_overrides": {"seo": 100000}}).json()
    assert e["scenario"] == "custom" and e["summary"]["monthly_total"] == 220000 and e["summary"]["quarterly_by_category"]["seo"] == 100000
    assert approve(api, h, f"/api/v1/marketing/budgets/{b['id']}")["status"] == "approved"
    t = api.get("/api/v1/marketing/budget-template?monthly_total=1000&categories=seo,paid_search", headers=h).json()
    assert sum(x["amount"] for x in t["lines"]) == 1000 and "Not derived" in t["basis"]


def test_content_generation_guardrails_and_approval(api, ai):
    h = register(api)
    cid, pid = setup(api, h)
    r = api.post(f"/api/v1/clients/{cid}/marketing/content/generate", headers=h, json={"studio": "social", "kind": "carousel",
                 "platform": "instagram", "product_id": pid, "topic": "water quality"})
    assert r.status_code == 201, r.text
    it = r.json()[0]
    assert it["status"] == "ai_generated" and it["origin"] == "ai"
    assert len(it["data"]["hashtags"]) == 30 and all(t.startswith("#") for t in it["data"]["hashtags"])
    assert "Guaranteed" not in it["body"] and it["data"]["removed_promises"]
    claims = " ".join(it["claims_to_check"])
    assert "ISO 9001" in claims and "500 customers" in claims and "Plant capacity" in claims
    assert api.post(f"/api/v1/clients/{cid}/marketing/content/generate", headers=h, json={"studio": "social", "kind": "carousel",
                    "platform": "youtube"}).status_code == 422
    seo = api.post(f"/api/v1/clients/{cid}/marketing/content/generate", headers=h, json={"studio": "seo", "kind": "blog_article"}).json()[0]
    assert seo["platform"] == "website" and len(seo["data"]["meta_title"]) <= 60 and seo["data"]["faqs"]

    path = f"/api/v1/marketing/content/{it['id']}"
    api.post(f"{path}/review", headers=h, json={"action": "submit"})
    assert api.post(f"{path}/review", headers=h, json={"action": "approve"}).status_code == 422  # claims need a note
    # client review required for this client
    assert api.put(f"/api/v1/clients/{cid}/marketing/calendar/settings", headers=h, json={"require_client_review": True}).status_code == 200
    a = api.post(f"{path}/review", headers=h, json={"action": "approve", "note": "ISO claim removed? no: checked certificate"}).json()
    assert a["status"] == "client_review"
    assert api.post(f"{path}/review", headers=h, json={"action": "client_approve", "note": "ok"}).status_code == 422  # who at the client
    a = api.post(f"{path}/review", headers=h, json={"action": "client_approve", "note": "Approved by email", "reviewer_name": "R. Shetty"}).json()
    assert a["status"] == "approved" and a["approved_at"]
    pend = api.get(f"/api/v1/clients/{cid}/marketing/approvals", headers=h).json()
    assert all(p["entity_id"] != it["id"] for p in pend) and any(p["entity_id"] == seo["id"] for p in pend) is False  # seo not submitted
    # moving the date keeps approval; editing the text does not
    when = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    m = api.patch(path, headers=h, json={"scheduled_at": when}).json()
    assert m["status"] == "approved" and m["scheduled_at"]
    cal = api.get(f"/api/v1/clients/{cid}/marketing/calendar?start={datetime.now(timezone.utc).date()}T00:00:00Z"
                  f"&end={(datetime.now(timezone.utc) + timedelta(days=10)).date()}T00:00:00Z", headers=h).json()
    assert [i["id"] for i in cal["items"]] == [it["id"]] and cal["settings"]["require_client_review"] is True
    e = api.patch(path, headers=h, json={"body": "New caption"}).json()
    assert e["status"] == "internal_review" and e["version"] == 2


def test_staff_cannot_approve(api, ai):
    h = register(api)
    cid, _ = setup(api, h)
    api.post("/api/v1/users", headers=h, json={"full_name": "Staff One", "email": "staff@acme.example.com", "password": "Passw0rd!", "role": "staff"})
    hs = {"Authorization": "Bearer " + api.post("/api/v1/auth/login", json={"email": "staff@acme.example.com", "password": "Passw0rd!"}).json()["access_token"]}
    it = api.post(f"/api/v1/clients/{cid}/marketing/content", headers=hs, json={"kind": "educational", "platform": "linkedin", "title": "Why RO",
                  "body": "Water quality matters in food processing."}).json()
    assert it["status"] == "draft" and it["claims_to_check"] == []
    assert api.post(f"/api/v1/marketing/content/{it['id']}/review", headers=hs, json={"action": "submit"}).status_code == 200
    assert api.post(f"/api/v1/marketing/content/{it['id']}/review", headers=hs, json={"action": "approve"}).status_code == 403
    assert api.post(f"/api/v1/clients/{cid}/marketing/content", headers=hs, json={"kind": "educational", "platform": "linkedin",
                    "title": "Results", "body": "Guaranteed leads in 30 days"}).status_code == 422


def connect_meta(api, h, cid, social):
    r = api.post(f"/api/v1/clients/{cid}/marketing/accounts/connect", headers=h, json={"platform": "facebook"})
    assert r.status_code == 200, r.text
    url = r.json()["authorize_url"]
    assert url.startswith("https://www.facebook.com/v27.0/dialog/oauth?") and "pages_manage_posts" in url
    state = httpx.URL(url).params["state"]
    cb = api.get(f"/api/v1/marketing/oauth/meta/callback?state={state}&code=good-code", follow_redirects=False)
    assert cb.status_code == 303 and "connected=2" in cb.headers["location"]
    return {a["platform"]: a for a in api.get(f"/api/v1/clients/{cid}/marketing/accounts", headers=h).json()["accounts"]}


def approved_item(api, h, cid, platform="facebook", **data):
    it = api.post(f"/api/v1/clients/{cid}/marketing/content", headers=h, json={"kind": "educational", "platform": platform,
                  "title": "Why water quality matters", "body": "Hard water damages food processing lines.", "data": {"hashtags": ["#water"], **data}}).json()
    approve(api, h, f"/api/v1/marketing/content/{it['id']}")
    return it


def test_oauth_publish_schedule_and_analytics(api, social):
    h = register(api)
    cid, _ = setup(api, h)
    accts = connect_meta(api, h, cid, social)
    fb, ig = accts["facebook"], accts["instagram"]
    assert fb["status"] == "connected" and fb["permissions"]["can_publish"] is True and "token_encrypted" not in fb
    assert ig["account_name"] == "@aquapure" and ig["permissions"]["can_publish"] is False  # instagram_content_publish not granted
    from app.core.db import SessionLocal
    from app.models import SocialAccount
    db = SessionLocal()
    stored = db.get(SocialAccount, fb["id"]).token_encrypted
    db.close()
    assert "PAGE-TOKEN" not in stored and publishing_service.decrypt(stored) == "PAGE-TOKEN"
    assert api.get("/api/v1/marketing/oauth/meta/callback?state=forged&code=x", follow_redirects=False).headers["location"].endswith("expired")

    draft = api.post(f"/api/v1/clients/{cid}/marketing/content", headers=h, json={"kind": "educational", "platform": "facebook", "title": "Draft",
                     "body": "Not approved yet"}).json()
    r = api.post(f"/api/v1/marketing/content/{draft['id']}/publish", headers=h, json={"account_id": fb["id"]})
    assert r.status_code == 409 and "approved" in r.json()["detail"] and social.posts == []

    it = approved_item(api, h, cid)
    assert api.post(f"/api/v1/marketing/content/{it['id']}/publish", headers=h, json={"account_id": ig["id"]}).status_code == 409  # wrong platform
    j = api.post(f"/api/v1/marketing/content/{it['id']}/publish", headers=h, json={"account_id": fb["id"]}).json()
    jobs = api.get(f"/api/v1/clients/{cid}/marketing/publishing-jobs", headers=h).json()
    assert jobs[0]["id"] == j["id"] and jobs[0]["status"] == "published" and jobs[0]["external_url"] == "https://www.facebook.com/111_222"
    assert social.posts == [("facebook", "Hard water damages food processing lines.\n\n#water")]
    assert api.get(f"/api/v1/marketing/content/{it['id']}", headers=h).json()["status"] == "published"
    assert api.patch(f"/api/v1/marketing/content/{it['id']}", headers=h, json={"body": "x"}).status_code == 409

    # schedule in the future, then edit: the job is cancelled and nothing is published
    it2 = approved_item(api, h, cid)
    later = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    j2 = api.post(f"/api/v1/marketing/content/{it2['id']}/publish", headers=h, json={"account_id": fb["id"], "scheduled_at": later}).json()
    assert j2["status"] == "queued" and api.get(f"/api/v1/marketing/content/{it2['id']}", headers=h).json()["status"] == "scheduled"
    api.patch(f"/api/v1/marketing/content/{it2['id']}", headers=h, json={"body": "Changed after approval"})
    assert api.get(f"/api/v1/clients/{cid}/marketing/publishing-jobs?status=cancelled", headers=h).json()[0]["id"] == j2["id"]

    # due scheduled job runs through the scheduler path
    it3 = approved_item(api, h, cid)
    j3 = api.post(f"/api/v1/marketing/content/{it3['id']}/publish", headers=h, json={"account_id": fb["id"], "scheduled_at": later}).json()
    db = SessionLocal()
    from app.models import PublishingJob
    assert publishing_service.due_jobs(db) == []
    db.get(PublishingJob, j3["id"]).scheduled_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    due = publishing_service.due_jobs(db)
    assert [x.id for x in due] == [j3["id"]]
    publishing_service.run_job(db, j3["id"])
    db.close()
    assert api.get(f"/api/v1/marketing/content/{it3['id']}", headers=h).json()["status"] == "published"

    # provider error -> failed, retry allowed while approval still matches
    social.fail_publish = True
    it4 = approved_item(api, h, cid)
    api.post(f"/api/v1/marketing/content/{it4['id']}/publish", headers=h, json={"account_id": fb["id"]})
    failed = api.get(f"/api/v1/clients/{cid}/marketing/publishing-jobs?status=failed", headers=h).json()[0]
    assert "Permissions error" in failed["error"] and api.get(f"/api/v1/marketing/content/{it4['id']}", headers=h).json()["status"] == "failed"
    social.fail_publish = False
    assert api.post(f"/api/v1/marketing/publishing-jobs/{failed['id']}/retry", headers=h).status_code == 200
    assert api.get(f"/api/v1/marketing/content/{it4['id']}", headers=h).json()["status"] == "published"

    # instagram needs an image and permission
    it5 = approved_item(api, h, cid, platform="instagram")
    assert "lacks permission" in api.post(f"/api/v1/marketing/content/{it5['id']}/publish", headers=h, json={"account_id": ig["id"]}).json()["detail"]

    # analytics: platform-reported values and a labelled calculation
    a = api.post(f"/api/v1/clients/{cid}/marketing/analytics/refresh", headers=h).json()
    assert a["posts_updated"] == 3 and "ROAS" in a["notes"]["ads"]
    an = api.get(f"/api/v1/clients/{cid}/marketing/analytics", headers=h).json()
    vals = {(m["entity_id"], m["metric"]): m["value"] for m in an["platform"]}
    assert vals[(it["id"], "reactions")] == 12 and vals[(it["id"], "shares")] == 3
    calc = [m for m in an["calculated"] if m["entity_id"] == it["id"]][0]
    assert calc["value"] == 19 and calc["formula"] == "reactions + comments + shares"

    # disconnect removes the token and blocks publishing
    api.post(f"/api/v1/marketing/accounts/{fb['id']}/disconnect", headers=h)
    it6 = approved_item(api, h, cid)
    assert api.post(f"/api/v1/marketing/content/{it6['id']}/publish", headers=h, json={"account_id": fb["id"]}).status_code == 409


def test_linkedin_and_manual_publish(api, social):
    h = register(api)
    cid, _ = setup(api, h)
    url = api.post(f"/api/v1/clients/{cid}/marketing/accounts/connect", headers=h, json={"platform": "linkedin"}).json()["authorize_url"]
    assert url.startswith("https://www.linkedin.com/oauth/v2/authorization?") and "w_member_social" in url
    api.get(f"/api/v1/marketing/oauth/linkedin/callback?state={httpx.URL(url).params['state']}&code=c", follow_redirects=False)
    li = api.get(f"/api/v1/clients/{cid}/marketing/accounts", headers=h).json()["accounts"][0]
    assert li["external_id"] == "urn:li:person:abc123" and li["permissions"]["can_publish"] and li["token_expires_at"]
    it = approved_item(api, h, cid, platform="linkedin")
    api.post(f"/api/v1/marketing/content/{it['id']}/publish", headers=h, json={"account_id": li["id"]})
    assert social.headers[0]["linkedin-version"] == "202610" and social.headers[0]["x-restli-protocol-version"] == "2.0.0"
    assert social.posts[-1] == ("linkedin", "Hard water damages food processing lines.\n\n\\#water")  # reserved chars escaped
    yt = api.post(f"/api/v1/clients/{cid}/marketing/content", headers=h, json={"kind": "long_video_script", "platform": "youtube",
                  "title": "RO explained", "body": "Script"}).json()
    assert api.post(f"/api/v1/marketing/content/{yt['id']}/mark-published", headers=h, json={"url": "https://youtu.be/abc"}).status_code == 409
    approve(api, h, f"/api/v1/marketing/content/{yt['id']}")
    m = api.post(f"/api/v1/marketing/content/{yt['id']}/mark-published", headers=h, json={"url": "https://youtu.be/abc"}).json()
    assert m["status"] == "published" and m["publishing_status"] == "manual"
    st = {p["platform"]: p for p in api.get("/api/v1/marketing/status", headers=h).json()["publishing"]}
    assert st["youtube"]["automated"] is False and st["facebook"]["configured"] is True


def test_not_configured_and_tenancy(api):
    h = register(api)
    cid, _ = setup(api, h)
    r = api.post(f"/api/v1/clients/{cid}/marketing/accounts/connect", headers=h, json={"platform": "facebook"})
    assert r.status_code == 409 and "META_APP_ID" in r.json()["detail"]
    it = api.post(f"/api/v1/clients/{cid}/marketing/content", headers=h, json={"kind": "educational", "platform": "facebook", "title": "Hello",
                  "body": "Text"}).json()
    h2 = register(api, agency="Other", email="o@other.example.com")
    assert api.get(f"/api/v1/marketing/content/{it['id']}", headers=h2).status_code == 404
    assert api.get(f"/api/v1/clients/{cid}/marketing/content", headers=h2).status_code == 404
    assert api.post(f"/api/v1/marketing/content/{it['id']}/review", headers=h2, json={"action": "submit"}).status_code == 404
    assert api.get(f"/api/v1/clients/{cid}/marketing/accounts", headers=h2).status_code == 404
    an = api.get(f"/api/v1/clients/{cid}/marketing/analytics", headers=h).json()
    assert an["platform"] == [] and an["calculated"] == []  # nothing connected, nothing shown


def test_ad_plans_and_spend_controls(api, ai):
    h = register(api)
    cid, pid = setup(api, h)
    r = api.post(f"/api/v1/clients/{cid}/marketing/ad-plans/generate", headers=h, json={"platform": "google", "product_id": pid,
                 "total_budget": 50000, "daily_budget": 2000, "landing_page": "aquapure.example.com/ro"})
    assert r.status_code == 201, r.text
    ad = r.json()
    assert all(len(x) <= 30 for x in ad["headlines"]) and not any("guaranteed" in x.lower() for x in ad["headlines"])
    assert ad["targets"]["removed_promises"] and ad["landing_page"] == "https://aquapure.example.com/ro" and ad["spend_approved"] is False
    path = f"/api/v1/marketing/ad-plans/{ad['id']}"
    assert api.post(f"{path}/spend-approval", headers=h, json={"approved": True, "spend_cap": 10000}).status_code == 409  # plan not approved
    approve(api, h, path)
    assert api.post(f"{path}/spend-approval", headers=h, json={"approved": True, "spend_cap": 90000}).status_code == 422  # over total
    s = api.post(f"{path}/spend-approval", headers=h, json={"approved": True, "spend_cap": 40000}).json()
    assert s["spend_approved"] and s["spend_cap"] == 40000 and "Not connected" in s["note"]
    e = api.patch(path, headers=h, json={"daily_budget": 3000}).json()
    assert e["spend_approved"] is False and e["status"] == "internal_review"


def test_assets_and_report(api, ai):
    h = register(api)
    cid, _ = setup(api, h)
    assert api.post(f"/api/v1/clients/{cid}/marketing/assets", headers=h, json={"kind": "colour", "name": "Navy", "value": "navy"}).status_code == 422
    col = api.post(f"/api/v1/clients/{cid}/marketing/assets", headers=h, json={"kind": "colour", "name": "Navy", "value": "#0b2a4a"}).json()
    assert col["value"] == "#0B2A4A" and col["approved"] is False
    assert api.post(f"/api/v1/clients/{cid}/marketing/assets", headers=h, json={"kind": "logo", "name": "Logo"}).status_code == 422
    it = api.post(f"/api/v1/clients/{cid}/marketing/content", headers=h, json={"kind": "educational", "platform": "facebook", "title": "Hi", "body": "x"}).json()
    assert api.patch(f"/api/v1/marketing/content/{it['id']}", headers=h, json={"asset_ids": [col["id"]]}).status_code == 409
    api.post(f"/api/v1/marketing/assets/{col['id']}/approve", headers=h)
    assert api.patch(f"/api/v1/marketing/content/{it['id']}", headers=h, json={"asset_ids": [col["id"]]}).json()["asset_ids"] == [col["id"]]
    today = datetime.now(timezone.utc).date()
    rep = api.post(f"/api/v1/clients/{cid}/marketing/reports", headers=h, json={"start": str(today - timedelta(days=30)), "end": str(today)}).json()
    md = rep["markdown"]
    assert "# Marketing report — AquaPure" in md and "No approved strategy yet." in md
    assert "— No connected platform has reported metrics yet." in md and "ROAS" in md
    assert api.get(f"/api/v1/marketing/reports/{rep['id']}/report.md", headers=h).text == md
    ov = api.get(f"/api/v1/clients/{cid}/marketing/overview", headers=h).json()
    assert ov["content"] == {"draft": 1} and ov["approved_budget"] is None
