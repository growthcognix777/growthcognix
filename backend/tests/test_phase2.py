"""Phase 2 acceptance tests: Client Intelligence Engine.

A scripted fake provider stands in for Gemini/Groq. It deliberately returns some invented values
(a certification and a price with no supporting quote, an application for a product of another
client) so the tests prove the guardrails drop them.
"""
import io
import re

import docx
import pytest

from app.services.ai import providers
from app.services.ai.providers import ProviderError
from app.services.intelligence.website_analyser import UnsafeURL, check_url
from tests.conftest import register

DOC_TEXT = ("AquaPure Systems was founded in 2009 and is headquartered in Hubballi, Karnataka. "
            "The RO Plant 500 LPH is built with SS304 stainless steel frame and has a minimum order of 1 unit. "
            "It is used for drinking water purification in food processing plants.")


def make_docx(text: str) -> bytes:
    d = docx.Document()
    d.add_paragraph(text)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


class FakeProvider:
    name, model, max_context_chars = "fake", "fake-1", 50_000

    def __init__(self, fail_on: set[str] | None = None, invalid_on: set[str] | None = None):
        self.fail_on, self.invalid_on, self.calls = set(fail_on or ()), set(invalid_on or ()), []

    def generate_json(self, system, prompt):
        kind = ("profile" if "company profile" in prompt else "product" if "product intelligence" in prompt
                else "apps" if "DIRECT applications" in prompt else "personas" if "buyer personas" in prompt
                else "markets" if "target markets" in prompt else "opps")
        self.calls.append(kind)
        if kind in self.fail_on:
            self.fail_on.discard(kind)
            raise ProviderError("Simulated quota error")
        if kind in self.invalid_on:
            return {"oops": True, "personas": "not a list"}
        doc = re.search(r"source_id=(doc:[\w-]+)", prompt)
        doc = doc.group(1) if doc else "client"
        pid = re.search(r"Valid product ids: ([\w-]+)", prompt)
        pid = pid.group(1) if pid else None
        ev = lambda q: [{"source_id": doc, "quote": q}]  # noqa: E731
        if kind == "profile":
            return {"summary": "AquaPure Systems makes reverse-osmosis water purification plants.",
                    "evidence": ev("founded in 2009 and is headquartered in Hubballi"), "confidence": 0.8,
                    "facts": {"founded": {"value": "2009", "evidence": ev("was founded in 2009")},
                              "employees": {"value": "250", "evidence": ev("has 250 employees")}}}  # invented
        if kind == "product":
            return {"products": [{"product_id": pid, "facts": [
                {"field": "materials", "value": "SS304 stainless steel frame", "evidence": ev("SS304 stainless steel frame"), "confidence": 0.9},
                {"field": "moq", "value": "1 unit", "evidence": ev("has a minimum order of 1 unit")},
                {"field": "certifications", "value": "ISO 9001", "evidence": ev("ISO 9001 certified")},  # invented
                {"field": "pricing", "value": "₹4.5 lakh", "evidence": []},  # invented
                {"field": "target_buyer_types", "value": "Food processors", "evidence": ev("food processing plants")},
            ]}]}
        if kind == "apps":
            return {"applications": [
                {"product_id": pid, "application": "Drinking water purification", "application_type": "direct",
                 "industry": "Food processing", "pain_points": "Hard water", "evidence": ev("used for drinking water purification")},
                {"product_id": pid, "application": "Boiler feed water", "application_type": "indirect",
                 "industry": "Textiles", "evidence": ev("RO Plant 500 LPH")},
                {"product_id": "someone-elses-product", "application": "Should be dropped", "evidence": []},
            ]}
        if kind == "personas":
            return {"personas": [{"product_id": pid, "name": "Plant head, food processing", "job_titles": ["Plant Head"],
                                  "evidence": ev("food processing plants"), "confidence": "70"}]}
        if kind == "markets":
            return {"markets": [
                {"scope": "state", "name": "Karnataka", "rationale": "Home state and existing base.", "priority": "High",
                 "evidence": ev("Hubballi, Karnataka")},
                {"scope": "City", "name": "Pune", "parent": "Maharashtra", "rationale": "Food processing cluster."},
                {"scope": "export", "name": "GCC", "rationale": "Water-scarce region."}]}
        return {"insights": [{"category": "gap", "title": "No pricing on record",
                              "detail": "Pricing is missing from all sources; ask the client."}]}


@pytest.fixture
def fake():
    p = FakeProvider()
    for purpose in ("analysis", "fast"):
        providers.set_override(purpose, p)
    yield p
    for purpose in ("analysis", "fast"):
        providers.set_override(purpose, None)


def setup_client(api, h, name="AquaPure Systems"):
    cid = api.post("/api/v1/clients", headers=h, json={"company_name": name, "target_markets": ["Karnataka"]}).json()["id"]
    pid = api.post("/api/v1/products", headers=h, json={"client_id": cid, "name": "RO Plant 500 LPH"}).json()["id"]
    r = api.post("/api/v1/documents", headers=h, data={"client_id": cid, "product_id": pid},
                 files={"file": ("brochure.docx", make_docx(DOC_TEXT),
                                 "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
    assert r.status_code == 201, r.text
    return cid, pid, r.json()["id"]


def findings(api, h, cid, t, **params):
    r = api.get(f"/api/v1/clients/{cid}/intelligence/findings/{t}", headers=h, params=params)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def test_no_provider_configured_is_refused(api):
    h = register(api)
    cid, _, _ = setup_client(api, h)
    r = api.post(f"/api/v1/clients/{cid}/intelligence/analyses", headers=h, json={})
    assert r.status_code == 409 and "GEMINI_API_KEY" in r.json()["detail"]
    # extraction alone needs no AI
    r = api.post(f"/api/v1/clients/{cid}/intelligence/analyses", headers=h, json={"stages": ["extract_documents"]})
    assert r.status_code == 201
    job = api.get(f"/api/v1/intelligence/analyses/{r.json()['id']}", headers=h).json()
    assert job["status"] == "completed"
    assert api.get(f"/api/v1/documents?client_id={cid}", headers=h).json()["items"][0]["extraction_status"] == "completed"


def test_full_analysis_guardrails_and_evidence(api, fake):
    h = register(api)
    cid, pid, did = setup_client(api, h)
    r = api.post(f"/api/v1/clients/{cid}/intelligence/analyses", headers=h, json={})
    assert r.status_code == 201, r.text
    job = api.get(f"/api/v1/intelligence/analyses/{r.json()['id']}", headers=h).json()
    assert job["status"] == "completed", job
    assert {s["key"]: s["status"] for s in job["stages"]}["fetch_website"] == "completed"  # no website: skipped quietly

    prof = findings(api, h, cid, "profile")[0]
    assert prof["verification_status"] == "needs_review"  # quoted evidence, awaiting a human
    assert prof["data"]["facts"] == {"founded": "2009"}  # invented employee count dropped → stays unknown
    assert any(e["document_id"] == did and e["quote_matched"] for e in prof["evidence"])

    facts = {f["data"]["field"]: f for f in findings(api, h, cid, "insight", category="product_fact")}
    assert set(facts) == {"materials", "moq", "target_buyer_types"}  # no invented certification or price
    assert facts["moq"]["verification_status"] == "needs_review"
    assert facts["target_buyer_types"]["verification_status"] == "ai_hypothesis"
    assert all(f["data"]["product_id"] == pid for f in facts.values())

    apps = findings(api, h, cid, "application")
    assert {a["data"]["application"] for a in apps} == {"Drinking water purification", "Boiler feed water"}
    assert all(a["data"]["product_id"] == pid for a in apps)
    indirect = next(a for a in apps if a["data"]["application_type"] == "indirect")
    assert indirect["verification_status"] == "ai_hypothesis" and indirect["is_inferred"]
    assert next(a for a in apps if a["data"]["application_type"] == "direct")["data"]["pain_points"] == ["Hard water"]

    persona = findings(api, h, cid, "persona")[0]
    assert persona["verification_status"] == "ai_hypothesis" and persona["confidence"] == 0.7
    assert any(e["source_type"] == "ai_inference" for e in persona["evidence"])

    markets = findings(api, h, cid, "market")
    assert {m["data"]["scope"] for m in markets} == {"state", "district_city", "export_market"}
    rep = api.get(f"/api/v1/clients/{cid}/intelligence", headers=h).json()
    assert rep["status_counts"]["verified"] == 0 and rep["products"][0]["name"] == "RO Plant 500 LPH"
    md = api.get(f"/api/v1/clients/{cid}/intelligence/report.md", headers=h).text
    assert "AI hypothesis" in md and "ISO 9001" not in md

    # re-running replaces unreviewed AI findings instead of duplicating them
    api.post(f"/api/v1/clients/{cid}/intelligence/analyses", headers=h, json={})
    assert len(findings(api, h, cid, "persona")) == 1 and len(findings(api, h, cid, "application")) == 2


def test_documents_of_other_client_not_used(api, fake):
    h = register(api)
    cid, _, _ = setup_client(api, h)
    other, _, other_doc = setup_client(api, h, "Other Client")
    api.post(f"/api/v1/clients/{cid}/intelligence/analyses", headers=h, json={})
    for t in ("profile", "application", "persona", "market", "insight"):
        for f in findings(api, h, cid, t):
            assert all(e["document_id"] != other_doc for e in f["evidence"])
    assert findings(api, h, other, "profile") == []


def test_failed_stage_is_retryable(api):
    h = register(api)
    cid, _, _ = setup_client(api, h)
    p = FakeProvider(fail_on={"personas"})
    providers.set_override("analysis", p)
    providers.set_override("fast", p)
    try:
        jid = api.post(f"/api/v1/clients/{cid}/intelligence/analyses", headers=h, json={}).json()["id"]
        job = api.get(f"/api/v1/intelligence/analyses/{jid}", headers=h).json()
        assert job["status"] == "failed" and "Buyer personas" in job["error"]
        st = {s["key"]: s for s in job["stages"]}
        assert st["personas"]["status"] == "failed" and "quota" in st["personas"]["error"]
        assert st["markets"]["status"] == "completed"  # later stages still ran
        assert findings(api, h, cid, "persona") == []
        calls_before = len(p.calls)
        r = api.post(f"/api/v1/intelligence/analyses/{jid}/retry", headers=h)
        assert r.status_code == 200
        job = api.get(f"/api/v1/intelligence/analyses/{jid}", headers=h).json()
        assert job["status"] == "completed" and job["attempts"] == 2
        assert p.calls[calls_before:] == ["personas"]  # only the failed stage re-ran
        assert len(findings(api, h, cid, "persona")) == 1
        assert api.post(f"/api/v1/intelligence/analyses/{jid}/retry", headers=h).status_code == 400
    finally:
        providers.set_override("analysis", None)
        providers.set_override("fast", None)


def test_invalid_ai_output_fails_validation(api):
    h = register(api)
    cid, _, _ = setup_client(api, h)
    p = FakeProvider(invalid_on={"personas"})
    providers.set_override("analysis", p)
    providers.set_override("fast", p)
    try:
        jid = api.post(f"/api/v1/clients/{cid}/intelligence/analyses", headers=h,
                       json={"stages": ["personas"]}).json()["id"]
        job = api.get(f"/api/v1/intelligence/analyses/{jid}", headers=h).json()
        st = {s["key"]: s for s in job["stages"]}
        assert st["personas"]["status"] == "failed" and "schema validation" in st["personas"]["error"]
        assert p.calls == ["personas", "personas"]  # one corrective retry, then give up
        assert st["business_profile"]["status"] == "skipped"
    finally:
        providers.set_override("analysis", None)
        providers.set_override("fast", None)


def test_review_edit_reject(api, fake):
    h = register(api)
    cid, _, _ = setup_client(api, h)
    api.post(f"/api/v1/clients/{cid}/intelligence/analyses", headers=h, json={})
    moq = next(f for f in findings(api, h, cid, "insight") if f["data"]["field"] == "moq")
    persona = findings(api, h, cid, "persona")[0]

    r = api.post(f"/api/v1/intelligence/findings/insight/{moq['id']}/review", headers=h, json={"action": "approve"})
    assert r.json()["verification_status"] == "verified" and r.json()["reviewed_at"]
    r = api.post(f"/api/v1/intelligence/findings/persona/{persona['id']}/review", headers=h, json={"action": "approve"})
    assert r.json()["verification_status"] == "ai_hypothesis" and r.json()["approved"]  # inference never "verified"

    r = api.patch(f"/api/v1/intelligence/findings/insight/{moq['id']}", headers=h, json={"data": {"detail": "2 units"}})
    assert r.json()["data"]["detail"] == "2 units" and r.json()["edited"]
    assert r.json()["verification_status"] == "needs_review" and not r.json()["approved"]
    assert api.patch(f"/api/v1/intelligence/findings/insight/{moq['id']}", headers=h,
                     json={"data": {"secret": 1}}).status_code == 422

    r = api.post(f"/api/v1/intelligence/findings/persona/{persona['id']}/review", headers=h,
                 json={"action": "reject", "note": "Not our buyer"})
    assert r.json()["verification_status"] == "rejected"
    assert findings(api, h, cid, "persona") == []
    assert len(findings(api, h, cid, "persona", include_rejected=True)) == 1

    # staff can edit but not approve
    api.post("/api/v1/users", headers=h, json={"full_name": "Staff One", "email": "staff@acme.example.com",
                                              "password": "Passw0rd!", "role": "staff"})
    t = api.post("/api/v1/auth/login", json={"email": "staff@acme.example.com", "password": "Passw0rd!"}).json()
    sh = {"Authorization": f"Bearer {t['access_token']}"}
    assert api.post(f"/api/v1/intelligence/findings/insight/{moq['id']}/review", headers=sh,
                    json={"action": "approve"}).status_code == 403

    # manual finding by a human
    r = api.post(f"/api/v1/clients/{cid}/intelligence/findings/market", headers=h,
                 json={"data": {"scope": "country", "name": "Kenya", "rationale": "Distributor enquiry"},
                       "note": "Client mentioned on call"})
    assert r.status_code == 201 and r.json()["origin"] == "user" and r.json()["is_inferred"]
    assert api.post(f"/api/v1/clients/{cid}/intelligence/findings/market", headers=h,
                    json={"data": {"scope": "planet", "name": "Mars"}}).status_code == 422


def test_intelligence_tenant_isolation(api, fake):
    a = register(api, "Agency A", "a@a.example.com")
    b = register(api, "Agency B", "b@b.example.com")
    cid, pid, _ = setup_client(api, a)
    jid = api.post(f"/api/v1/clients/{cid}/intelligence/analyses", headers=a, json={}).json()["id"]
    fid = findings(api, a, cid, "persona")[0]["id"]
    assert api.get(f"/api/v1/clients/{cid}/intelligence", headers=b).status_code == 404
    assert api.get(f"/api/v1/clients/{cid}/intelligence/findings/persona", headers=b).status_code == 404
    assert api.get(f"/api/v1/intelligence/analyses/{jid}", headers=b).status_code == 404
    assert api.post(f"/api/v1/intelligence/analyses/{jid}/retry", headers=b).status_code == 404
    assert api.post(f"/api/v1/clients/{cid}/intelligence/analyses", headers=b, json={}).status_code == 404
    assert api.post(f"/api/v1/intelligence/findings/persona/{fid}/review", headers=b,
                    json={"action": "approve"}).status_code == 404
    assert api.patch(f"/api/v1/intelligence/findings/persona/{fid}", headers=b,
                     json={"data": {"name": "Hijack"}}).status_code == 404
    # B cannot attach a finding to A's product through B's own client
    bcid = api.post("/api/v1/clients", headers=b, json={"company_name": "B Client"}).json()["id"]
    assert api.post(f"/api/v1/clients/{bcid}/intelligence/findings/application", headers=b,
                    json={"data": {"product_id": pid, "application": "x"}}).status_code == 404


def test_one_running_analysis_per_client(api, fake, monkeypatch):
    from app.routers import intelligence
    monkeypatch.setattr(intelligence, "_enqueue", lambda *a, **k: None)  # leave the job queued
    h = register(api)
    cid, _, _ = setup_client(api, h)
    assert api.post(f"/api/v1/clients/{cid}/intelligence/analyses", headers=h, json={}).status_code == 201
    assert api.post(f"/api/v1/clients/{cid}/intelligence/analyses", headers=h, json={}).status_code == 409


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://localhost:8000/", "http://10.0.0.5/", "file:///etc/passwd",
                                 "http://169.254.169.254/latest/meta-data/", "http://user:pw@example.com/",
                                 "ftp://example.com/"])
def test_ssrf_guard(url):
    with pytest.raises(UnsafeURL):
        check_url(url)


def test_provider_http_adapters(monkeypatch):
    """Gemini and Groq adapters build the right request and parse JSON (incl. fenced) replies."""
    import httpx
    from app.services.ai.providers import GeminiProvider, GroqProvider
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen["url"], seen["headers"], seen["body"] = url, headers, json
        if "groq" in url:
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": 1}'}}]})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": '```json\n{"ok": 2}\n```'}]}}]})

    monkeypatch.setattr(httpx, "post", fake_post)
    assert GroqProvider("k1", "m", 5).generate_json("sys", "hi") == {"ok": 1}
    assert seen["headers"]["Authorization"] == "Bearer k1" and seen["body"]["response_format"]["type"] == "json_object"
    assert GeminiProvider("k2", "gm", 5).generate_json("sys", "hi") == {"ok": 2}
    assert seen["headers"]["x-goog-api-key"] == "k2" and "gm:generateContent" in seen["url"]
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(429, text="quota"))
    with pytest.raises(ProviderError):
        GroqProvider("k", "m", 5).generate_json("s", "p")
