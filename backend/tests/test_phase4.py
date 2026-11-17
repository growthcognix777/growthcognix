"""Phase 4 acceptance tests: buyer profiles, research areas, discovery campaigns, verification, scoring,
export, CRM hand-off, suppression, tenancy and UN Comtrade.

The search provider, company websites and Comtrade are an in-memory fake web (httpx.MockTransport). Every
company, contact and signal asserted here comes from those fake pages; the tests also check that nothing
else is ever created (no invented prospects, contacts or intent)."""
import io
import json

import httpx
import pytest

from app.core.config import get_settings
from app.services.intelligence.website_analyser import UnsafeURL
from app.services.leads import providers, scoring
from app.services.web import competitor_discovery, crawler_service, opencrawl_adapter
from tests.conftest import register


def html(title, body):
    return f"<!doctype html><html lang=en><head><title>{title}</title><meta name='description' content='{title} official site'></head><body>{body}</body></html>"


class FakeWeb:
    def __init__(self):
        self.hits: dict[str, int] = {}
        self.search_calls: list[str] = []
        self.search_mode = "ok"
        self.results = [
            {"title": "Dairy One Foods | Milk processing", "url": "https://dairyone.example.com/", "content": "Dairy processing plant in Belagavi"},
            {"title": "Dairy One on LinkedIn", "url": "https://www.linkedin.com/company/dairy-one", "content": "listing"},
            {"title": "Acme (our own client)", "url": "https://acme.example.com/", "content": "own site"},
            {"title": "Dairy One - About", "url": "https://dairyone.example.com/about", "content": "duplicate domain"},
            {"title": "Blocked Dairy", "url": "https://blocked.example.net/", "content": "robots says no"},
            {"title": "Down Dairy", "url": "https://down.example.org/", "content": "server error"},
            {"title": "Do Not Contact Ltd", "url": "https://dnc.example.com/", "content": "suppressed"},
        ]
        self.sites = {
            "https://dairyone.example.com/": html("Dairy One Foods", "<h1>Dairy One Foods</h1><p>We run a dairy processing plant in Belagavi, Karnataka "
                                                  "with CIP cleaning on every line. ISO 22000 certified. 450 employees.</p>"
                                                  "<a href='/contact'>Contact</a><a href='/tenders'>Tenders</a>"),
            "https://dairyone.example.com/contact": html("Contact Dairy One", "<h1>Contact</h1><p>sales@dairyone.example.com "
                                                         "ravi.kumar@dairyone.example.com +91 831 240 1234 Belagavi</p>"),
            "https://dairyone.example.com/tenders": html("Tenders", "<p>Notice inviting tender for boiler water treatment chemicals, closing 2026-12-15.</p>"),
            "https://blocked.example.net/robots.txt": "User-agent: *\nDisallow: /\n",
            "https://blocked.example.net/": html("Blocked", "<p>dairy processing plant</p>"),
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.hits[url] = self.hits.get(url, 0) + 1
        if request.url.host == "searx.test":
            self.search_calls.append(request.url.params.get("q"))
            if self.search_mode == "429":
                return httpx.Response(429, text="slow down")
            if self.search_mode == "bad_key":
                return httpx.Response(403, text="no")
            return httpx.Response(200, json={"results": self.results})
        if request.url.host == "comtradeapi.un.org":
            self.comtrade = dict(request.url.params)
            return httpx.Response(200, json={"error": "", "data": [{"period": "2023", "cmdCode": "8413", "flowCode": "M",
                                                                      "primaryValue": 1386703399.344, "qty": 0.0, "isReported": False}]})
        if request.url.host == "down.example.org":
            return httpx.Response(500, headers={"content-type": "text/html"}, text="err")
        body = self.sites.get(url)
        if body is None:
            return httpx.Response(404, headers={"content-type": "text/plain"}, text="")
        ctype = "text/plain" if url.endswith("robots.txt") else "text/html"
        return httpx.Response(200, headers={"content-type": ctype}, text=body)


@pytest.fixture
def web(monkeypatch):
    fw = FakeWeb()
    transport = httpx.MockTransport(fw.handler)
    monkeypatch.setattr(opencrawl_adapter, "make_client", lambda: httpx.Client(transport=transport, follow_redirects=False))
    monkeypatch.setattr(providers, "http_client", lambda: httpx.Client(transport=transport))

    def fake_check(url):
        if httpx.URL(url).host in ("127.0.0.1", "localhost", "169.254.169.254"):
            raise UnsafeURL("non-public address")
        return url
    monkeypatch.setattr(opencrawl_adapter, "check_url", fake_check)
    monkeypatch.setattr(competitor_discovery, "check_url", fake_check)
    monkeypatch.setattr(crawler_service, "_sleep", lambda s: None)
    monkeypatch.setattr(providers, "_sleep", lambda s: None)
    s = get_settings()
    monkeypatch.setattr(s, "searxng_url", "http://searx.test")
    monkeypatch.setattr(s, "discovery_daily_limit_searxng", 500)
    return fw


def setup(api, h):
    cid = api.post("/api/v1/clients", headers=h, json={"company_name": "Acme Water", "website": "https://acme.example.com"}).json()["id"]
    pid = api.post("/api/v1/products", headers=h, json={"client_id": cid, "name": "Boiler water treatment chemical"}).json()["id"]
    r = api.post(f"/api/v1/clients/{cid}/intelligence/findings/persona", headers=h, json={"data": {
        "product_id": pid, "name": "Dairy plants with boilers", "buyer_type": "end_user", "industry": "Dairy",
        "industry_relation": "indirect", "company_types": ["dairy processing plant"], "application_categories": ["CIP cleaning"],
        "problems_solved": ["boiler water treatment"], "rationale": "Dairies run steam boilers for pasteurisation"}})
    assert r.status_code == 201, r.text
    persona = r.json()
    assert persona["data"]["buyer_type"] == "end_user" and persona["data"]["company_types"] == ["dairy processing plant"]
    india = api.post(f"/api/v1/clients/{cid}/leads/geographies", headers=h, json={"level": "country", "name": "india"}).json()
    assert india["name"] == "India" and india["country_code"] == "IN"
    ka = api.post(f"/api/v1/clients/{cid}/leads/geographies", headers=h, json={"level": "state", "name": "Karnataka", "parent_id": india["id"]}).json()
    bgm = api.post(f"/api/v1/clients/{cid}/leads/geographies", headers=h, json={"level": "district", "name": "Belagavi", "parent_id": ka["id"]})
    assert bgm.status_code == 201 and bgm.json()["path"] == ["India", "Karnataka", "Belagavi"]
    return cid, pid, persona["id"], bgm.json()["id"]


def campaign(api, h, cid, persona_id, geo_id, **kw):
    r = api.post(f"/api/v1/clients/{cid}/leads/campaigns", headers=h, json={"name": "Belagavi dairies", "persona_ids": [persona_id],
                                                                           "geography_ids": [geo_id], "sources": ["searxng"], **kw})
    assert r.status_code == 201, r.text
    return r.json()


def test_geographies_validation(api, web):
    h = register(api)
    cid, _, _, _ = setup(api, h)
    geos = api.get(f"/api/v1/clients/{cid}/leads/geographies", headers=h).json()
    india = next(g for g in geos if g["level"] == "country")
    assert api.post(f"/api/v1/clients/{cid}/leads/geographies", headers=h, json={"level": "state", "name": "Karnatka", "parent_id": india["id"]}).status_code == 422
    assert api.post(f"/api/v1/clients/{cid}/leads/geographies", headers=h, json={"level": "district", "name": "Udupi"}).status_code == 422
    assert api.post(f"/api/v1/clients/{cid}/leads/geographies", headers=h, json={"level": "city", "name": "Pune", "parent_id": india["id"]}).status_code == 422
    assert api.post(f"/api/v1/clients/{cid}/leads/geographies", headers=h, json={"level": "country", "name": "India"}).status_code == 409
    ref = api.get("/api/v1/leads/geo/reference", headers=h).json()
    assert "Karnataka" in ref["india"]["states"] and len(ref["india"]["states"]) == 28 and len(ref["india"]["union_territories"]) == 8


def test_campaign_discovers_verifies_scores(api, web):
    h = register(api)
    cid, pid, persona_id, geo_id = setup(api, h)
    api.post("/api/v1/leads/suppression", headers=h, json={"kind": "domain", "value": "dnc.example.com", "reason": "asked not to be contacted"})
    c = campaign(api, h, cid, persona_id, geo_id)
    assert c["counts"]["planned_targets"] == 2  # two phrases (company type, application) x one area x one source
    r = api.post(f"/api/v1/leads/campaigns/{c['id']}/start", headers=h)
    assert r.status_code == 200
    c = api.get(f"/api/v1/leads/campaigns/{c['id']}", headers=h).json()
    assert c["status"] == "completed" and c["progress"] == 100, c
    assert web.search_calls == ["dairy processing plant Belagavi Karnataka", "CIP cleaning Belagavi Karnataka"]
    k = c["counts"]
    assert k["listing_skipped"] == 2 and k["own_or_competitor"] == 2 and k["suppressed"] == 2 and k["new_prospects"] == 3

    items = api.get(f"/api/v1/clients/{cid}/leads/prospects", headers=h).json()["items"]
    assert {p["domain"] for p in items} == {"dairyone.example.com", "blocked.example.net", "down.example.org"}
    by = {p["domain"]: p for p in items}
    one = by["dairyone.example.com"]
    assert one["verification_status"] == "website_verified" and one["searched_area"] == [["India", "Karnataka", "Belagavi"]]
    assert one["verified_fields"]["website"]["by"] == "system" and one["industry"] is None  # never guessed
    d = api.get(f"/api/v1/leads/prospects/{one['id']}", headers=h).json()
    terms = {t["term"] for t in d["signals"]["matched_terms"]}
    assert {"dairy processing plant", "cip cleaning", "boiler water treatment"} <= terms
    assert any(i["strength"] == "strong" and i["url"].endswith("/tenders") for i in d["signals"]["intent"])
    assert {c["value"] for c in d["contacts"]} >= {"sales@dairyone.example.com"}
    assert not any("ravi" in (c["value"] or "") for c in d["contacts"])  # personal address is never collected
    assert all(c["kind"] in ("role_email", "phone") and c["source_url"] for c in d["contacts"])
    assert d["fits"] and d["fits"][0]["product_id"] == pid and d["fits"][0]["origin"] == "observed"
    assert any(e["field"] == "discovery" and e["provider"] == "searxng" for e in d["evidence"])
    assert all(e["source_url"] for e in d["evidence"])
    s = d["score"]
    assert s["components"]["intent"]["points"] > 0 and s["total"] == one["score_total"] and len(s["explanation"]) == 5
    assert set(s["weights"]) == {"fit", "need", "intent", "capacity", "contact"} and sum(s["weights"].values()) == 100

    blocked = api.get(f"/api/v1/leads/prospects/{by['blocked.example.net']['id']}", headers=h).json()
    assert blocked["site_status"] == "blocked_by_robots" and blocked["verification_status"] == "discovered"
    assert "https://blocked.example.net/" not in web.hits
    down = api.get(f"/api/v1/leads/prospects/{by['down.example.org']['id']}", headers=h).json()
    assert down["score"]["total"] == 0 and down["contacts"] == [] and down["score"]["components"]["intent"]["points"] == 0
    assert "intent scores 0" in down["score"]["components"]["intent"]["reasons"][0]

    # filters
    assert api.get(f"/api/v1/clients/{cid}/leads/prospects?district=Belagavi", headers=h).json()["total"] == 3
    assert api.get(f"/api/v1/clients/{cid}/leads/prospects?district=Udupi", headers=h).json()["total"] == 0
    assert api.get(f"/api/v1/clients/{cid}/leads/prospects?product_id={pid}", headers=h).json()["total"] == 1
    assert api.get(f"/api/v1/clients/{cid}/leads/prospects?verification=website_verified", headers=h).json()["total"] == 1
    summ = api.get(f"/api/v1/clients/{cid}/leads/summary", headers=h).json()
    assert summ["prospects"] == 3 and summ["campaigns"] == {"completed": 1}

    # resume is idempotent: done targets are not searched again
    before = len(web.search_calls)
    assert api.post(f"/api/v1/leads/campaigns/{c['id']}/start", headers=h).status_code == 200
    assert len(web.search_calls) == before
    assert api.get(f"/api/v1/clients/{cid}/leads/prospects", headers=h).json()["total"] == 3


def test_provider_failure_retry_and_daily_limit(api, web, monkeypatch):
    h = register(api)
    cid, _, persona_id, geo_id = setup(api, h)
    web.search_mode = "429"
    c = campaign(api, h, cid, persona_id, geo_id)
    api.post(f"/api/v1/leads/campaigns/{c['id']}/start", headers=h)
    c2 = api.get(f"/api/v1/leads/campaigns/{c['id']}", headers=h).json()
    assert c2["status"] == "completed" and c2["targets"] == {"failed": 2} and c2["counts"]["failed_targets"] == 2
    assert len(web.search_calls) == 6  # each target: first try + 2 retries
    t = api.get(f"/api/v1/leads/campaigns/{c['id']}/targets", headers=h).json()
    assert "429" in t[0]["error"]
    assert api.get(f"/api/v1/clients/{cid}/leads/prospects", headers=h).json()["total"] == 0  # nothing invented
    web.search_mode = "ok"
    api.post(f"/api/v1/leads/campaigns/{c['id']}/start", headers=h)  # failed targets are retried
    assert api.get(f"/api/v1/leads/campaigns/{c['id']}", headers=h).json()["targets"] == {"done": 2}

    monkeypatch.setattr(get_settings(), "discovery_daily_limit_searxng", 3)  # 2 already used today
    c = campaign(api, h, cid, persona_id, geo_id, name="Second run")
    api.post(f"/api/v1/leads/campaigns/{c['id']}/start", headers=h)
    c3 = api.get(f"/api/v1/leads/campaigns/{c['id']}", headers=h).json()
    assert c3["status"] == "paused" and "Daily limit" in c3["error"] and c3["targets"] == {"done": 1, "pending": 1}


def test_pause_and_cancel(api, web, monkeypatch):
    h = register(api)
    cid, _, persona_id, geo_id = setup(api, h)
    c = campaign(api, h, cid, persona_id, geo_id)
    from app.core.db import SessionLocal
    from app.models import DiscoveryCampaign
    real = providers.SearXNG.search

    def pause_after(self, *a, **k):
        res = real(self, *a, **k)
        db = SessionLocal()
        db.get(DiscoveryCampaign, c["id"]).status = "paused"
        db.commit()
        db.close()
        return res
    monkeypatch.setattr(providers.SearXNG, "search", pause_after)
    api.post(f"/api/v1/leads/campaigns/{c['id']}/start", headers=h)
    st = api.get(f"/api/v1/leads/campaigns/{c['id']}", headers=h).json()
    assert st["status"] == "paused" and st["targets"] == {"done": 1, "pending": 1} and len(web.search_calls) == 1
    monkeypatch.setattr(providers.SearXNG, "search", real)
    api.post(f"/api/v1/leads/campaigns/{c['id']}/start", headers=h)
    assert api.get(f"/api/v1/leads/campaigns/{c['id']}", headers=h).json()["status"] == "completed"
    assert len(web.search_calls) == 2
    c = campaign(api, h, cid, persona_id, geo_id, name="To cancel")
    assert api.post(f"/api/v1/leads/campaigns/{c['id']}/cancel", headers=h).json()["status"] == "cancelled"
    assert api.post(f"/api/v1/leads/campaigns/{c['id']}/start", headers=h).status_code == 409


def test_campaign_guards(api, web, monkeypatch):
    h = register(api)
    cid, _, persona_id, geo_id = setup(api, h)
    from app.core.db import SessionLocal
    from app.models import BuyerPersona
    db = SessionLocal()
    ai = BuyerPersona(tenant_id=db.get(BuyerPersona, persona_id).tenant_id, client_id=cid, name="AI guess", origin="ai", is_inferred=True,
                      verification_status="ai_hypothesis", approved=False)
    db.add(ai)
    db.commit()
    ai_id = ai.id
    db.close()
    r = api.post(f"/api/v1/clients/{cid}/leads/campaigns", headers=h, json={"name": "xx", "persona_ids": [ai_id], "sources": ["searxng"]})
    assert r.status_code == 400 and "Approve" in r.json()["detail"]
    assert api.post(f"/api/v1/intelligence/findings/persona/{ai_id}/review", headers=h, json={"action": "approve"}).status_code == 200
    assert api.post(f"/api/v1/clients/{cid}/leads/campaigns", headers=h, json={"name": "xx", "persona_ids": [ai_id], "sources": ["searxng"]}).status_code == 201
    assert api.post(f"/api/v1/clients/{cid}/leads/campaigns", headers=h, json={"name": "xx", "persona_ids": [persona_id], "sources": ["bing"]}).status_code == 422
    assert api.post(f"/api/v1/clients/{cid}/leads/campaigns", headers=h, json={"name": "xx", "persona_ids": [persona_id], "sources": ["directory"]}).status_code == 422
    monkeypatch.setattr(get_settings(), "searxng_url", "")
    c = campaign(api, h, cid, persona_id, geo_id)
    r = api.post(f"/api/v1/leads/campaigns/{c['id']}/start", headers=h)
    assert r.status_code == 409 and "SEARXNG_URL" in r.json()["detail"]
    # AI buyer profiles need an AI key
    r = api.post(f"/api/v1/clients/{cid}/leads/buyer-profiles/generate", headers=h, json={})
    assert r.status_code == 409
    st = {p["key"]: p for p in api.get("/api/v1/leads/providers", headers=h).json()["providers"]}
    assert st["bing"]["status"] == "retired" and st["indiamart"]["status"] == "manual_only" and st["searxng"]["configured"] is False


def run_full(api, h, web):
    cid, pid, persona_id, geo_id = setup(api, h)
    c = campaign(api, h, cid, persona_id, geo_id)
    api.post(f"/api/v1/leads/campaigns/{c['id']}/start", headers=h)
    items = api.get(f"/api/v1/clients/{cid}/leads/prospects", headers=h).json()["items"]
    return cid, {p["domain"]: p for p in items}


def test_verification_approval_export_crm_suppression(api, web):
    h = register(api)
    cid, by = run_full(api, h, web)
    one = by["dairyone.example.com"]["id"]
    assert api.get(f"/api/v1/clients/{cid}/leads/export", headers=h).status_code == 404  # nothing approved
    r = api.post(f"/api/v1/clients/{cid}/leads/approve", headers=h, json={"prospect_ids": [one]}).json()
    assert r["updated"] == 0 and "verify the company" in r["blocked"][0]
    assert api.post(f"/api/v1/leads/prospects/{one}/verify", headers=h, json={"field": "company", "decision": "verified"}).status_code == 422
    p = api.post(f"/api/v1/leads/prospects/{one}/verify", headers=h, json={"field": "company", "decision": "verified",
                 "source_url": "https://www.mca.gov.in/x?cin=U123", "note": "CIN checked on MCA"}).json()
    assert p["verification_status"] == "website_verified"  # highest of company + website
    p = api.post(f"/api/v1/leads/prospects/{one}/verify", headers=h, json={"field": "industry", "decision": "verified", "note": "Dairy per site"}).json()
    assert p["verification_status"] == "industry_verified"
    q = api.get(f"/api/v1/clients/{cid}/leads/verification-queue", headers=h).json()
    assert one not in [x["id"] for x in q]
    assert api.post(f"/api/v1/clients/{cid}/leads/crm-handoff", headers=h, json={"prospect_ids": [one]}).json()["handed_off"] == 0
    assert api.post(f"/api/v1/clients/{cid}/leads/approve", headers=h, json={"prospect_ids": [one]}).json()["updated"] == 1

    csv_text = api.get(f"/api/v1/clients/{cid}/leads/export?format=csv", headers=h).text
    lines = csv_text.splitlines()
    assert lines[0].startswith("name,website,domain") and len(lines) == 2 and "sales@dairyone.example.com" in lines[1]
    x = api.get(f"/api/v1/clients/{cid}/leads/export?format=xlsx", headers=h)
    from openpyxl import load_workbook
    ws = load_workbook(io.BytesIO(x.content)).active
    assert ws.max_row == 2 and ws.cell(1, 1).value == "name"

    api.post("/api/v1/leads/suppression", headers=h, json={"kind": "email", "value": "Sales@DairyOne.example.com"})
    assert "sales@dairyone.example.com" not in api.get(f"/api/v1/clients/{cid}/leads/export", headers=h).text
    assert api.post(f"/api/v1/leads/prospects/{one}/contacts", headers=h, json={"kind": "role_email", "value": "sales@dairyone.example.com",
                    "source_url": "https://dairyone.example.com/contact"}).status_code == 409
    assert api.post(f"/api/v1/leads/prospects/{one}/contacts", headers=h, json={"kind": "person", "person_name": "R Kumar",
                    "source_url": "https://dairyone.example.com/team"}).status_code == 422  # role required

    r = api.post(f"/api/v1/clients/{cid}/leads/crm-handoff", headers=h, json={"prospect_ids": [one, by["down.example.org"]["id"]]}).json()
    assert r["handed_off"] == 1 and len(r["skipped"]) == 1
    assert api.get(f"/api/v1/leads/prospects/{one}", headers=h).json()["crm_status"] == "handed_off"

    # rejection drops the lead to zero confidence and out of the default list
    dn = by["down.example.org"]["id"]
    api.post(f"/api/v1/leads/prospects/{dn}/verify", headers=h, json={"field": "status", "decision": "rejected", "note": "Not a dairy"})
    assert api.get(f"/api/v1/leads/prospects/{dn}", headers=h).json()["confidence"] == 0
    assert dn not in [p["id"] for p in api.get(f"/api/v1/clients/{cid}/leads/prospects", headers=h).json()["items"]]


def test_intent_evidence_weights_and_assignment(api, web):
    h = register(api)
    cid, by = run_full(api, h, web)
    dn = by["down.example.org"]["id"]
    assert api.post(f"/api/v1/leads/prospects/{dn}/evidence", headers=h, json={"field": "intent", "excerpt": "GeM bid for boiler chemicals"}).status_code == 422
    d = api.post(f"/api/v1/leads/prospects/{dn}/evidence", headers=h, json={"field": "intent", "excerpt": "GeM bid for boiler chemicals",
                 "source_url": "https://bidplus.gem.gov.in/bid/123"}).json()
    assert d["score"]["components"]["intent"]["points"] == 10
    assert api.post(f"/api/v1/clients/{cid}/leads/rescore", headers=h, json={"weights": {"fit": 50}}).status_code == 422
    r = api.post(f"/api/v1/clients/{cid}/leads/rescore", headers=h, json={"weights": {"fit": 20, "need": 20, "intent": 40, "capacity": 10, "contact": 10}}).json()
    assert r["rescored"] == 4  # no suppression list in this test, so dnc.example.com is a prospect too
    assert api.get(f"/api/v1/leads/prospects/{dn}", headers=h).json()["score"]["components"]["intent"]["points"] == 20
    assert len(api.get(f"/api/v1/leads/prospects/{dn}/scores", headers=h).json()) >= 3
    me = api.get("/api/v1/auth/me", headers=h).json()
    uid = me.get("id") or me["user"]["id"]
    assert api.post(f"/api/v1/clients/{cid}/leads/assign", headers=h, json={"prospect_ids": [dn], "user_id": uid}).json()["updated"] == 1
    assert api.get(f"/api/v1/clients/{cid}/leads/prospects?assigned_to={uid}", headers=h).json()["total"] == 1


def test_manual_prospect_and_tenancy(api, web):
    h = register(api)
    cid, by = run_full(api, h, web)
    base = {"name": "Nandini Dairy Plant"}
    assert api.post(f"/api/v1/clients/{cid}/leads/prospects", headers=h, json=base).status_code == 422  # source required
    assert api.post(f"/api/v1/clients/{cid}/leads/prospects", headers=h, json={**base, "website": "https://www.indiamart.com/x",
                    "source_url": "https://www.indiamart.com/x"}).status_code == 422
    assert api.post(f"/api/v1/clients/{cid}/leads/prospects", headers=h, json={**base, "website": "dairyone.example.com",
                    "source_url": "https://kiadb.in/estates"}).status_code == 409  # same domain
    r = api.post(f"/api/v1/clients/{cid}/leads/prospects", headers=h, json={**base, "source_url": "https://kiadb.in/estates", "district": "Belagavi"})
    assert r.status_code == 201 and r.json()["verification_status"] == "discovered" and r.json()["origin"] == "manual"

    h2 = register(api, agency="Other", email="o@other.example.com")
    one = by["dairyone.example.com"]["id"]
    assert api.get(f"/api/v1/leads/prospects/{one}", headers=h2).status_code == 404
    assert api.get(f"/api/v1/clients/{cid}/leads/prospects", headers=h2).status_code == 404
    assert api.post(f"/api/v1/leads/prospects/{one}/verify", headers=h2, json={"field": "company", "decision": "verified", "note": "x"}).status_code == 404
    assert api.get(f"/api/v1/clients/{cid}/leads/export", headers=h2).status_code == 404
    assert api.get("/api/v1/leads/suppression", headers=h2).json() == []


def test_comtrade_historical_only(api, web):
    h = register(api)
    cid, pid, _, _ = setup(api, h)
    assert api.post(f"/api/v1/clients/{cid}/leads/market-insights/comtrade", headers=h, json={"hs_code": "84x", "reporter": "IN", "period": "2023"}).status_code == 422
    r = api.post(f"/api/v1/clients/{cid}/leads/market-insights/comtrade", headers=h, json={"hs_code": "8413", "reporter": "India", "period": "2023", "product_id": pid})
    assert r.status_code == 201, r.text
    row = r.json()[0]
    assert web.comtrade["reporterCode"] == "699" and web.comtrade["partnerCode"] == "0"
    assert row["kind"] == "historical_trade" and row["value_usd"] == pytest.approx(1386703399.344) and row["quantity"] is None
    assert "Not current demand" in row["detail"] and row["source"] == "un_comtrade"
    assert api.post(f"/api/v1/clients/{cid}/leads/market-insights", headers=h, json={"kind": "tariff", "title": "BCD 7.5%"}).status_code == 422


def test_scoring_rules():
    class P:
        verified_fields, signals, providers, site_status, last_verified_at, site_checked_at, verification_status = {}, {}, ["searxng"], None, None, None, "discovered"
    r = scoring.compute(P(), [], [])
    assert r["total"] == 0 and r["confidence"] == 0 and r["score_class"] == "low"
    with pytest.raises(ValueError):
        scoring.normalise_weights({"fit": 90})
    assert [scoring.classify(x) for x in (80, 65, 40, 39)] == ["very_high", "high", "medium", "low"]
    assert json.dumps(r)  # serialisable for LeadScore.components
