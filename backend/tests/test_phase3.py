"""Phase 3 acceptance tests: crawler, technical audit, PageSpeed, competitors, monitoring, opportunities.

All HTTP goes to an in-memory fake web (httpx.MockTransport); no real site is contacted and every
asserted value comes from the fake pages, so nothing here is invented audit data."""
import json

import httpx
import pytest

from app.core.config import get_settings
from app.services.intelligence.website_analyser import UnsafeURL, check_url
from app.services.web import competitor_discovery, crawler_service, opencrawl_adapter, pagespeed_service
from tests.conftest import register

H = "<!doctype html>"


def page(title, body, *, meta=None, viewport=True, lang="en", extra_head=""):
    head = f"<title>{title}</title>" if title is not None else ""
    if meta:
        head += f'<meta name="description" content="{meta}">'
    if viewport:
        head += '<meta name="viewport" content="width=device-width">'
    return f'{H}<html{f" lang={lang}" if lang else ""}><head>{head}{extra_head}</head><body>{body}</body></html>'


LONG = " ".join(["Industrial water pumps for agriculture irrigation and municipal supply."] * 30)


class FakeWeb:
    def __init__(self):
        self.hits: dict[str, int] = {}
        self.rival_version = 1
        self.sites = {
            "https://acme.example.com/robots.txt": (200, "text/plain", "User-agent: *\nDisallow: /private\nCrawl-delay: 2\n"
                                                    "Sitemap: https://acme.example.com/sitemap.xml\n"),
            "https://acme.example.com/sitemap.xml": (200, "application/xml",
                                                     "<urlset><url><loc>https://acme.example.com/</loc></url>"
                                                     "<url><loc>https://acme.example.com/products/pump</loc></url>"
                                                     "<url><loc>https://acme.example.com/orphan</loc></url></urlset>"),
            "https://acme.example.com/": (200, "text/html", page("Acme Pumps",
                '<h1>Acme Pumps</h1><img src="a.png"><a href="/products/pump">Pump</a><a href="/about">About</a>'
                '<a href="/broken">Old</a><a href="/private/x">Secret</a><a href="/old">Legacy</a><a href="/flaky">Flaky</a>'
                '<a href="/brochure.pdf">PDF</a><a href="https://elsewhere.example.org/">Out</a>' + LONG,
                meta="Acme makes industrial water pumps for farms and towns across India.", viewport=False)),
            "https://acme.example.com/products/pump": (200, "text/html", page("Acme Pumps", "<h1>Solar Pump 5HP</h1><p>Five horsepower.</p>")),
            "https://acme.example.com/about": (200, "text/html", page("About Acme Pumps Ltd",
                "<h1>About us</h1><h2>Quality</h2><p>We are ISO 9001 certified.</p>" + LONG,
                meta="About Acme: forty years of pump engineering in Pune, ISO 9001 certified.",
                extra_head='<link rel="canonical" href="https://acme.example.com/about">'
                           '<script type="application/ld+json">{"@type": "Organization", "name": "Acme"}</script>')),
            "https://acme.example.com/broken": (404, "text/html", "not found"),
            "https://acme.example.com/old": (301, "/mid", ""),
            "https://acme.example.com/mid": (301, "/about", ""),
            "https://acme.example.com/orphan": (200, "text/html", page("Orphan page", "<h1>Orphan</h1>" + LONG, meta="x" * 70)),
            "https://acme.example.com/flaky": "FLAKY",
            "https://acme.example.com/private/x": (200, "text/html", page("Private", "secret")),
            "https://rival.example.com/robots.txt": (404, "text/plain", ""),
        }

    def rival(self, url):
        v = self.rival_version
        home = page("Rival Pumps", f'<h1>{"Rival water pumps" if v == 1 else "Rival solar pumps for every farm"}</h1>'
                    '<a href="/products/solar-pump">Solar</a><a href="/contact">Contact</a>'
                    + ('<a href="/products/new-pump">New</a>' if v == 2 else "") + "<p>Solar irrigation experts in Gujarat.</p>")
        pages = {
            "https://rival.example.com/": home,
            "https://rival.example.com/products/solar-pump": page("Solar irrigation pump",
                f"<h1>Solar irrigation pump</h1><p>Price ₹{'45,000' if v == 1 else '42,500'} per unit. CE certified.</p>"
                + ("<p>Festive offer: 10% off</p>" if v == 2 else "")),
            "https://rival.example.com/contact": page("Contact Rival", "<h1>Contact</h1><p>sales@rival.example.com "
                                                       "john.doe@rival.example.com +91 98450 12345 Ahmedabad, Gujarat</p>"),
        }
        if v == 2:
            pages["https://rival.example.com/products/new-pump"] = page("Solar irrigation kit", "<h1>New solar irrigation kit</h1>")
        return pages.get(url)

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.hits[url] = self.hits.get(url, 0) + 1
        if url.startswith("https://rival.example.com/") and not url.endswith("robots.txt"):
            body = self.rival(url)
            return httpx.Response(200 if body else 404, headers={"content-type": "text/html"}, text=body or "nope")
        item = self.sites.get(url)
        if item == "FLAKY":
            if self.hits[url] == 1:
                return httpx.Response(503, headers={"content-type": "text/html"}, text="busy")
            return httpx.Response(200, headers={"content-type": "text/html"}, text=page("Flaky but fine", "<h1>Recovered</h1>" + LONG, meta="m" * 80))
        if item is None:
            return httpx.Response(404, headers={"content-type": "text/html"}, text="nope")
        status, ctype, body = item
        if status in (301, 302):
            return httpx.Response(status, headers={"location": ctype})
        return httpx.Response(status, headers={"content-type": ctype}, text=body)


@pytest.fixture
def web(monkeypatch):
    fw = FakeWeb()
    monkeypatch.setattr(opencrawl_adapter, "make_client",
                        lambda: httpx.Client(transport=httpx.MockTransport(fw.handler), follow_redirects=False))

    def fake_check(url):
        host = httpx.URL(url).host
        if host in ("127.0.0.1", "localhost", "169.254.169.254", "10.0.0.5"):
            raise UnsafeURL(f"{host} resolves to a non-public address")
        return url
    monkeypatch.setattr(opencrawl_adapter, "check_url", fake_check)
    monkeypatch.setattr(competitor_discovery, "check_url", fake_check)
    sleeps = []
    monkeypatch.setattr(crawler_service, "_sleep", lambda s: sleeps.append(s))
    fw.sleeps = sleeps
    return fw


def setup_client(api, h, website="https://acme.example.com"):
    c = api.post("/api/v1/clients", headers=h, json={"company_name": "Acme Pumps", "website": website}).json()
    return c["id"]


def audit(api, h, cid, **cfg):
    r = api.post(f"/api/v1/clients/{cid}/website-audits", headers=h, json={"crawl_config": {"delay_seconds": 0.5, **cfg}})
    assert r.status_code == 201, r.text
    job = api.get(f"/api/v1/crawls/{r.json()['id']}", headers=h).json()
    return job


def test_crawl_audit_robots_limits_retries(api, web):
    h = register(api)
    cid = setup_client(api, h)
    job = audit(api, h, cid)
    assert job["status"] == "completed", job["error"]
    assert job["robots"]["found"] and job["robots"]["crawl_delay"] == 2.0
    # robots crawl-delay (2s) overrides the configured 0.5s, and requests are spaced by it
    assert job["summary"]["delay_seconds"] == 2.0 and web.sleeps and set(web.sleeps) == {2.0}
    assert "https://acme.example.com/private/x" not in web.hits  # disallowed: never requested
    assert job["pages_blocked"] == 1
    assert "https://acme.example.com/brochure.pdf" not in web.hits  # not an HTML page
    assert not any("elsewhere.example.org" in u for u in web.hits)  # external links not crawled
    assert web.hits["https://acme.example.com/flaky"] == 2  # 503 retried once, then succeeded
    pages = api.get(f"/api/v1/crawls/{job['id']}/pages", headers=h).json()["items"]
    by = {p["url"]: p for p in pages}
    assert by["https://acme.example.com/broken"]["status_code"] == 404
    old = by["https://acme.example.com/old"]
    assert old["final_url"] == "https://acme.example.com/about" and len(old["redirect_chain"]) == 2
    assert by["https://acme.example.com/about"]["structured_data"] == ["Organization"]
    assert by["https://acme.example.com/"]["images_missing_alt"] == 1

    a = api.get(f"/api/v1/clients/{cid}/website", headers=h).json()["latest_audit"]
    fs = api.get(f"/api/v1/website-audits/{a['id']}/findings", headers=h).json()["items"]
    checks = {(f["check"], f["page_url"]) for f in fs}
    assert ("broken_link", "https://acme.example.com/") in checks
    assert ("redirect_chain", "https://acme.example.com/old") in checks
    assert ("title_duplicate", "https://acme.example.com/products/pump") in checks
    assert ("meta_description_missing", "https://acme.example.com/products/pump") in checks
    assert ("viewport_missing", "https://acme.example.com/") in checks
    assert ("img_alt_missing", "https://acme.example.com/") in checks
    assert ("orphan_page", "https://acme.example.com/orphan") in checks
    assert ("blocked_by_robots", "https://acme.example.com/private/x") in checks
    assert all(not f["measured"] for f in fs)  # crawler observations only; no PageSpeed key
    assert "not configured" in a["pagespeed"]["skipped"]
    assert 0 <= a["health_score"] <= 100 and "Not a ranking" in a["summary"]["score_basis"]
    topics = api.get(f"/api/v1/website-audits/{a['id']}/topics", headers=h).json()
    assert any(t["topic"] == "pumps" for t in topics["items"])
    md = api.get(f"/api/v1/website-audits/{a['id']}/report.md", headers=h).text
    assert "Website Audit — Acme Pumps" in md and "broken" in md.lower() and "PAGESPEED_API_KEY" in md
    csv_head = api.get(f"/api/v1/website-audits/{a['id']}/findings.csv", headers=h).text.splitlines()[0]
    assert csv_head.startswith("severity,category,check")


def test_max_pages_and_patterns(api, web):
    h = register(api)
    cid = setup_client(api, h)
    job = audit(api, h, cid, max_pages=3, use_sitemap=False, exclude=["/old*"])
    assert job["status"] == "completed"
    assert job["pages_crawled"] + job["pages_failed"] + job["pages_blocked"] <= 3
    assert "https://acme.example.com/old" not in web.hits
    assert job["summary"]["limit_reached"] is True
    assert api.post(f"/api/v1/clients/{cid}/website-audits", headers=h,
                    json={"crawl_config": {"max_pages": 0}}).status_code == 422


def test_resume_after_failure(api, web, monkeypatch):
    h = register(api)
    cid = setup_client(api, h)
    calls = {"n": 0}
    from app.services.web import website_audit
    original = website_audit.run

    def boom(*a, **k):  # the worker dies after the pages were stored
        calls["n"] += 1
        raise RuntimeError("worker lost")
    monkeypatch.setattr(website_audit, "run", boom)
    job = audit(api, h, cid)
    assert job["status"] == "failed" and "worker lost" in job["error"]
    crawled_first = job["pages_crawled"]
    monkeypatch.setattr(website_audit, "run", original)
    before = dict(web.hits)
    r = api.post(f"/api/v1/crawls/{job['id']}/retry", headers=h)
    assert r.status_code == 200
    job2 = api.get(f"/api/v1/crawls/{job['id']}", headers=h).json()
    assert job2["status"] == "completed" and job2["attempts"] == 2 and job2["pages_crawled"] == crawled_first
    # resumed: pages already stored were not fetched again
    assert web.hits["https://acme.example.com/about"] == before["https://acme.example.com/about"]
    assert calls["n"] == 1


def test_ssrf_blocked(api, web):
    with pytest.raises(UnsafeURL):
        check_url("http://127.0.0.1/admin")
    with pytest.raises(UnsafeURL):
        check_url("http://10.0.0.1/")
    with pytest.raises(UnsafeURL):
        check_url("http://user:pw@example.com/")
    with pytest.raises(UnsafeURL):
        check_url("http://example.com:8080/")
    # a redirect to a private address is checked on the hop and blocked
    web.sites["https://acme.example.com/old"] = (302, "http://169.254.169.254/latest/meta-data", "")
    r = opencrawl_adapter.NativeCrawler().fetch("https://acme.example.com/old")
    assert r.error and "SSRF" in r.error and "169.254.169.254/latest" not in web.hits
    h = register(api)
    cid = api.post("/api/v1/clients", headers=h, json={"company_name": "Local", "website": "http://localhost"}).json()["id"]
    job = audit(api, h, cid)
    assert job["status"] == "failed"


def test_pagespeed_measured_when_key_set(api, web, monkeypatch):
    monkeypatch.setattr(get_settings(), "pagespeed_api_key", "test-key")
    psi = {"lighthouseResult": {"finalUrl": "https://acme.example.com/", "fetchTime": "2026-11-16T10:00:00Z",
                                "categories": {"performance": {"score": 0.42}, "seo": {"score": 0.9}},
                                "audits": {"largest-contentful-paint": {"numericValue": 5200.0},
                                           "cumulative-layout-shift": {"numericValue": 0.05}}}}
    seen = []

    def h_psi(req):
        seen.append(req.url.params.get("strategy"))
        assert req.url.params.get("key") == "test-key"
        return httpx.Response(200, json=psi)
    monkeypatch.setattr(pagespeed_service, "make_client", lambda: httpx.Client(transport=httpx.MockTransport(h_psi)))
    h = register(api)
    cid = setup_client(api, h)
    audit(api, h, cid)
    a = api.get(f"/api/v1/clients/{cid}/website", headers=h).json()["latest_audit"]
    assert sorted(seen) == ["desktop", "mobile"]
    assert a["pagespeed"]["results"][0]["scores"]["performance"] == 42
    measured = api.get(f"/api/v1/website-audits/{a['id']}/findings", headers=h, params={"source": "pagespeed"}).json()["items"]
    assert measured and all(f["measured"] for f in measured)
    assert {f["check"] for f in measured} >= {"psi_performance_mobile", "psi_lcp_ms_mobile"}
    assert not any("cls" in f["check"] for f in measured)  # 0.05 is good: no finding invented


def test_competitors_snapshot_changes_opportunities(api, web):
    h = register(api)
    cid = setup_client(api, h)
    # manual entry with validation
    assert api.post(f"/api/v1/clients/{cid}/competitors", headers=h, json={"name": "Self", "website": "acme.example.com"}).status_code == 400
    assert api.post(f"/api/v1/clients/{cid}/competitors", headers=h, json={"name": "Bad", "website": "http://10.0.0.5"}).status_code == 422
    assert api.post(f"/api/v1/clients/{cid}/competitors", headers=h,
                    json={"name": "X", "relevance": {"keyword": "pumps"}}).status_code == 422
    comp = api.post(f"/api/v1/clients/{cid}/competitors", headers=h, json={
        "name": "Rival Pumps", "website": "rival.example.com", "category": "direct",
        "relevance": {"product": "solar pumps", "geography": "Gujarat"}}).json()
    assert comp["domain"] == "rival.example.com" and comp["domain_valid"] is True
    assert api.post(f"/api/v1/clients/{cid}/competitors", headers=h,
                    json={"name": "Dup", "website": "https://www.rival.example.com"}).status_code == 409

    r = api.post(f"/api/v1/competitors/{comp['id']}/analyse", headers=h, json={"crawl_config": {"delay_seconds": 0}})
    assert r.status_code == 201
    prof = api.get(f"/api/v1/competitors/{comp['id']}", headers=h).json()
    assert prof["latest_crawl"]["status"] == "completed", prof["latest_crawl"]["error"]
    s = prof["latest_snapshot"]
    assert any("₹45,000 per unit" in p["text"] for p in s["prices"])  # copied as published
    assert {c["name"] for c in s["certifications"]} == {"CE certified"}
    assert s["contact"]["emails"] == ["sales@rival.example.com"]  # personal address not kept
    assert {x["name"] for x in s["locations"]} >= {"Gujarat", "Ahmedabad"}
    assert prof["competitor"]["positioning"] is None  # no AI key: no AI interpretation invented
    assert api.get(f"/api/v1/competitors/{comp['id']}/changes", headers=h).json()["items"] == []  # first snapshot

    web.rival_version = 2
    api.post(f"/api/v1/competitors/{comp['id']}/analyse", headers=h, json={"crawl_config": {"delay_seconds": 0}})
    ch = api.get(f"/api/v1/competitors/{comp['id']}/changes", headers=h).json()["items"]
    types = {c["change_type"]: c for c in ch}
    assert {"price_changed", "page_added", "homepage_messaging", "product_added", "promotion_added"} <= set(types)
    pc = types["price_changed"]
    assert "45,000" in pc["old_value"] and "42,500" in pc["new_value"] and pc["url"].endswith("/products/solar-pump")
    assert types["homepage_messaging"]["old_value"] == "Rival water pumps" and pc["observed_at"]

    audit(api, h, cid, delay_seconds=0)
    cmp_ = api.get(f"/api/v1/clients/{cid}/competitors/comparison", headers=h).json()["items"]
    assert cmp_[0]["is_client"] and cmp_[0]["health_score"] is not None and cmp_[1]["health_score"] is None
    res = api.post(f"/api/v1/clients/{cid}/opportunities/analyse", headers=h).json()
    assert res["created"] > 0
    opps = api.get(f"/api/v1/clients/{cid}/opportunities", headers=h).json()["items"]
    kinds = {o["kind"] for o in opps}
    assert "missing_product_info" in kinds and "differentiation" in kinds  # prices/CE vs client's ISO 9001
    assert all(o["evidence"] and o["is_inferred"] and o["verification_status"] == "needs_review" for o in opps)
    assert not any(w in json.dumps(opps).lower() for w in ("revenue", "market share", "traffic of", "ad spend"))
    # re-running does not duplicate
    assert api.post(f"/api/v1/clients/{cid}/opportunities/analyse", headers=h).json()["created"] == 0
    o = api.post(f"/api/v1/opportunities/{opps[0]['id']}/review", headers=h, json={"action": "approve"}).json()
    assert o["approved"] and o["verification_status"] != "verified"


def test_scheduled_monitoring(api, web):
    from app.core.db import SessionLocal
    from app.services.web.competitor_monitor import due_jobs
    h = register(api)
    cid = setup_client(api, h)
    comp = api.post(f"/api/v1/clients/{cid}/competitors", headers=h, json={
        "name": "Rival", "website": "rival.example.com", "relevance": {"product": "pumps"}, "monitor_interval_days": 7}).json()
    api.post(f"/api/v1/competitors/{comp['id']}/analyse", headers=h, json={})
    db = SessionLocal()
    try:
        assert due_jobs(db) == []  # analysed just now
        from datetime import datetime, timedelta, timezone
        jobs = due_jobs(db, datetime.now(timezone.utc) + timedelta(days=8))
        assert len(jobs) == 1 and jobs[0].trigger == "scheduled" and jobs[0].kind == "competitor"
    finally:
        db.close()


def test_ai_suggestions_need_key_and_are_filtered(api, web):
    from app.services.ai import providers
    h = register(api)
    cid = setup_client(api, h)
    assert api.post(f"/api/v1/clients/{cid}/competitors/suggest", headers=h).status_code == 409

    class Fake:
        name, model, max_context_chars = "fake", "fake-1", 10000

        def generate_json(self, system, prompt):
            return {"competitors": [
                {"name": "Rival Pumps", "website": "rival.example.com", "relevance": {"product": "solar pumps"}},
                {"name": "Keyword Only", "website": "kw.example.com", "relevance": {}},
                {"name": "Private Net", "website": "http://10.0.0.5", "relevance": {"geography": "India"}},
                {"name": "Acme itself", "website": "acme.example.com", "relevance": {"product": "pumps"}}]}
    providers.set_override("fast", Fake())
    try:
        res = api.post(f"/api/v1/clients/{cid}/competitors/suggest", headers=h).json()
    finally:
        providers.set_override("fast", None)
    assert res["created"] == 1 and res["dropped"] == {"no_relevance": 1, "invalid_domain": 1, "duplicate": 1}
    items = api.get(f"/api/v1/clients/{cid}/competitors", headers=h).json()["items"]
    assert items[0]["status"] == "suggested" and items[0]["origin"] == "ai"
    assert api.post(f"/api/v1/competitors/{items[0]['id']}/analyse", headers=h, json={}).status_code == 400  # accept first
    assert api.post(f"/api/v1/competitors/{items[0]['id']}/review", headers=h, json={"action": "accept"}).json()["status"] == "active"


def test_tenant_isolation(api, web):
    h1 = register(api)
    cid = setup_client(api, h1)
    job = audit(api, h1, cid, delay_seconds=0)
    comp = api.post(f"/api/v1/clients/{cid}/competitors", headers=h1, json={"name": "Rival", "website": "rival.example.com",
                                                                             "relevance": {"product": "pumps"}}).json()
    a = api.get(f"/api/v1/clients/{cid}/website", headers=h1).json()["latest_audit"]
    h2 = register(api, agency="Other Agency", email="b@other.example.com")
    for url in (f"/api/v1/crawls/{job['id']}", f"/api/v1/crawls/{job['id']}/pages", f"/api/v1/website-audits/{a['id']}",
                f"/api/v1/website-audits/{a['id']}/findings", f"/api/v1/competitors/{comp['id']}",
                f"/api/v1/clients/{cid}/competitors", f"/api/v1/clients/{cid}/opportunities"):
        assert api.get(url, headers=h2).status_code == 404, url
    assert api.post(f"/api/v1/competitors/{comp['id']}/analyse", headers=h2, json={}).status_code == 404
    assert api.post(f"/api/v1/clients/{cid}/website-audits", headers=h2, json={}).status_code == 404


def test_only_client_site_and_staff_limits(api, web):
    h = register(api)
    cid = setup_client(api, h)
    assert api.put(f"/api/v1/clients/{cid}/website", headers=h, json={"url": "https://rival.example.com"}).status_code == 400
    r = api.put(f"/api/v1/clients/{cid}/website", headers=h, json={"crawl_config": {"max_pages": 10, "exclude": ["/blog/*"]},
                                                                    "crawl_interval_days": 30})
    assert r.status_code == 200 and r.json()["crawl_config"]["max_pages"] == 10
    agents = {a["key"]: a for a in api.get("/api/v1/agents", headers=h).json()}
    assert agents["website_auditor"]["status"] == "active"
