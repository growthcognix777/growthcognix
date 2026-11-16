from tests.conftest import register

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def test_register_login_me(api):
    register(api)
    r = api.post("/api/v1/auth/login", json={"email": "owner@acme.example.com", "password": "Passw0rd!"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "owner"
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert api.get("/api/v1/auth/me", headers=h).status_code == 200


def test_bad_login_and_missing_token(api):
    register(api)
    assert api.post("/api/v1/auth/login", json={"email": "owner@acme.example.com", "password": "wrong"}).status_code == 401
    assert api.get("/api/v1/clients").status_code == 401
    assert api.get("/api/v1/clients", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_weak_password_rejected(api):
    r = api.post("/api/v1/auth/register", json={"agency_name": "X Co", "full_name": "A B",
                                                "email": "a@b.example.com", "password": "aaaaaaaa"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "password"


def test_client_crud_search_archive(api):
    h = register(api)
    r = api.post("/api/v1/clients", headers=h, json={
        "company_name": "AquaPure Systems", "website": "aquapure.example", "industry": "Water treatment",
        "target_markets": ["Karnataka", "UAE"], "marketing_budget": 150000, "contact_email": ""})
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["website"].startswith("https://") and c["target_markets"] == ["Karnataka", "UAE"]
    assert api.get("/api/v1/clients?q=aqua", headers=h).json()["total"] == 1
    r = api.patch(f"/api/v1/clients/{c['id']}", headers=h, json={"industry": "Industrial water"})
    assert r.json()["industry"] == "Industrial water"
    assert api.delete(f"/api/v1/clients/{c['id']}", headers=h).status_code == 400  # must archive first
    assert api.post(f"/api/v1/clients/{c['id']}/archive", headers=h).status_code == 200
    assert api.get("/api/v1/clients", headers=h).json()["total"] == 0
    assert api.get("/api/v1/clients?archived=true", headers=h).json()["total"] == 1


def test_client_validation(api):
    h = register(api)
    r = api.post("/api/v1/clients", headers=h, json={"company_name": "A", "contact_email": "not-an-email"})
    assert r.status_code == 422
    fields = {e["field"] for e in r.json()["errors"]}
    assert {"company_name", "contact_email"} <= fields


def test_tenant_isolation(api):
    a = register(api, "Agency A", "a@a.example.com")
    b = register(api, "Agency B", "b@b.example.com")
    cid = api.post("/api/v1/clients", headers=a, json={"company_name": "Secret Client"}).json()["id"]
    assert api.get(f"/api/v1/clients/{cid}", headers=b).status_code == 404
    assert api.get("/api/v1/clients", headers=b).json()["total"] == 0
    assert api.patch(f"/api/v1/clients/{cid}", headers=b, json={"industry": "x"}).status_code == 404
    assert api.post("/api/v1/products", headers=b, json={"client_id": cid, "name": "Hack"}).status_code == 404
    assert api.get("/api/v1/activity", headers=b).json()["items"][0]["action"] == "agency.registered"


def test_products_and_documents(api):
    h = register(api)
    cid = api.post("/api/v1/clients", headers=h, json={"company_name": "AquaPure"}).json()["id"]
    p = api.post("/api/v1/products", headers=h, json={
        "client_id": cid, "name": "RO Plant 500 LPH", "category": "Purification",
        "min_order_quantity": "1 unit", "target_industries": ["Food processing", "Pharma"]}).json()
    assert api.get(f"/api/v1/products?client_id={cid}", headers=h).json()["total"] == 1
    r = api.post("/api/v1/documents", headers=h, data={"client_id": cid, "product_id": p["id"]},
                 files={"file": ("catalogue.pdf", PDF, "application/pdf")})
    assert r.status_code == 201, r.text
    doc = r.json()
    assert "storage_key" not in doc and doc["file_ext"] == "pdf"
    assert api.get(f"/api/v1/documents/{doc['id']}/download", headers=h).content == PDF
    bad = api.post("/api/v1/documents", headers=h, data={"client_id": cid},
                   files={"file": ("evil.pdf", b"MZ\x90\x00", "application/pdf")})
    assert bad.status_code == 415
    exe = api.post("/api/v1/documents", headers=h, data={"client_id": cid},
                   files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert exe.status_code == 415


def test_roles_enforced(api):
    h = register(api)
    r = api.post("/api/v1/users", headers=h, json={"full_name": "Staff Sam", "email": "sam@acme.example.com",
                                                   "password": "Passw0rd!", "role": "staff"})
    assert r.status_code == 201
    sh = {"Authorization": "Bearer " + api.post("/api/v1/auth/login", json={
        "email": "sam@acme.example.com", "password": "Passw0rd!"}).json()["access_token"]}
    cid = api.post("/api/v1/clients", headers=sh, json={"company_name": "Staff Client"}).json()["id"]
    assert api.post(f"/api/v1/clients/{cid}/archive", headers=sh).status_code == 403
    assert api.patch("/api/v1/agency", headers=sh, json={"name": "Hijack"}).status_code == 403


def test_jobs_agents_dashboard_no_fake_data(api):
    h = register(api)
    agents = api.get("/api/v1/agents", headers=h).json()
    assert len(agents) == 8 and all(a["total_jobs"] == 0 for a in agents)
    live = {"business_analyst", "website_auditor", "competitor_analyst"}  # Phase 2 and 3 agents run
    assert all(a["status"] == "planned" for a in agents if a["key"] not in live)
    assert all(a["status"] == "active" for a in agents if a["key"] in ("website_auditor", "competitor_analyst"))
    assert next(a for a in agents if a["key"] == "business_analyst")["status"] == "needs_setup"  # no AI key in tests
    assert api.post("/api/v1/jobs", headers=h, json={"job_type": "market_research"}).status_code == 409
    s = api.get("/api/v1/dashboard/summary", headers=h).json()
    assert s == {"active_clients": 0, "archived_clients": 0, "products": 0, "documents": 0,
                 "team_members": 1, "jobs_running": 0}


def test_activity_log_records_actions(api):
    h = register(api)
    cid = api.post("/api/v1/clients", headers=h, json={"company_name": "Logged Co"}).json()["id"]
    api.patch(f"/api/v1/clients/{cid}", headers=h, json={"industry": "Steel"})
    actions = [a["action"] for a in api.get("/api/v1/activity", headers=h).json()["items"]]
    assert actions[:2] == ["client.updated", "client.created"]
