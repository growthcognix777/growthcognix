<p align="center"><img src="docs/logo.png" alt="GrowthCognix" width="420"></p>

# GrowthCognix

A multi-tenant AI business growth and marketing intelligence platform for digital marketing agencies.
**Discover → Analyse → Market → Acquire → Sell → Retain → Grow.**

**Live preview:** https://growthcognix777.github.io/growthcognix/ — runs in *browser sandbox* mode (see below).

> Status: **Phase 1 — Foundation** (this release). Local development foundation, not a production SaaS release.

## Roadmap (7 phases)

| Phase | Module | Status |
|---|---|---|
| 1 | Foundation: auth, agency dashboard, clients, products, documents, agent centre, research jobs, activity log | ✅ Released |
| 2 | Client Intelligence Engine (document extraction, business profiles, applications, personas, markets, evidence & review) | ✅ This release |
| 3 | Website Audit & Competitor Intelligence (Firecrawl + OpenCrawl/Scrapy, PageSpeed) | Planned |
| 4 | Global Buyer Discovery & Lead Intelligence (India + export markets, 100-pt lead score) | Planned |
| 5 | AI Marketing Strategy & Campaign Automation (human approval before publishing/spend) | Planned |
| 6 | CRM, Sales & Outreach (pipeline, Gmail/Outlook, WhatsApp Business, quotations) | Planned |
| 7 | Customer Success & Business Growth Intelligence | Planned |

## Free stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | Next.js 15 (static export), React 19, TypeScript, Tailwind CSS 3, lucide icons | Free, fast, deploys to GitHub Pages |
| Backend | FastAPI, SQLAlchemy 2, Pydantic 2, Alembic | Typed, validated, migration-first |
| Auth | JWT (PyJWT) + bcrypt, role-based access (owner/admin/manager/staff) | No paid identity provider |
| Data | PostgreSQL 16, Redis 7 + RQ worker | Open source, Docker Compose |
| AI (Phase 2+) | Gemini API free tier, Groq free tier, optional Ollama; provider-swappable via env | No large local model on a 16 GB Intel iMac |
| Hosting | GitHub Pages (preview), Docker Compose (local). Free options later: Render/Koyeb, Neon, Upstash, Cloudflare Tunnel | $0 |

## Run locally (Docker Compose)

```bash
git clone https://github.com/growthcognix777/growthcognix.git
cd growthcognix
cp backend/.env.example backend/.env       # then set JWT_SECRET
docker compose up --build
```

- App: http://localhost:3000
- API: http://localhost:8000 · Swagger docs: http://localhost:8000/docs
- Migrations run automatically on backend start (`alembic upgrade head`).

### Without Docker (development)

```bash
# backend
cd backend && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql+psycopg://growth:growth@localhost:5432/growthcognix JWT_SECRET=dev-secret UPLOAD_DIR=./uploads
alembic upgrade head && uvicorn app.main:app --reload

# frontend
cd frontend && npm install && npm run dev      # http://localhost:3000
```

## Data modes

| Mode | `NEXT_PUBLIC_DATA_MODE` | Where data lives |
|---|---|---|
| API | `api` (default) | PostgreSQL via FastAPI |
| Browser sandbox | `local` | This browser's IndexedDB only — used for the GitHub Pages preview, where no server runs |

Both modes share one typed `DataDriver` contract (`frontend/src/lib/api/contract.ts`) and the same validation, tenant scoping, roles and activity log. The sandbox never seeds sample data; every record is one you created. It is **not** a security boundary — don't enter confidential data there.

## Tests

```bash
cd backend && pytest -q          # 10 tests: auth, validation, CRUD, archive, tenant isolation, roles, uploads, no-fake-data
cd frontend && npm test          # 11 tests: validators + browser-sandbox driver (isolation, uploads, agents)
cd frontend && npm run typecheck
```

API collection: `docs/api-requests.http` · OpenAPI spec: `docs/openapi.json` · CI: `.github/workflows/ci.yml`.

## Phase 1 features

- **Auth:** agency registration (creates tenant + owner), login/logout, JWT, protected routes, roles owner/admin/manager/staff.
- **Tenant isolation:** `tenant_id` comes only from the verified token; every tenant-owned query goes through `scoped()`; other tenants' ids return 404.
- **Dashboard:** sidebar, top bar, client search, notifications (recent activity), profile menu, responsive layout, live counts only.
- **Clients:** create, view, edit, search, archive/restore; permanent delete only after archiving (admin+).
- **Products & services:** many per client, all brief fields; images/spec sheets attach through Documents.
- **Documents:** PDF/DOCX/JPG/PNG, extension + magic-byte checks, 20 MB cap, tenant-checked streaming download, storage paths never exposed. Extraction interface stubbed for Phase 2 (`backend/app/services/extraction.py`).
- **AI agent centre:** 8 agents shown as *planned* with real job counts (zero). No fake results.
- **Research jobs:** list/status/progress/errors/results/cancel API + UI. Creating jobs returns 409 until a worker exists.
- **Market research & buyer discovery workspaces:** structure only, execution disabled, KPI tiles show "—".
- **Activity history:** registration, sign-in/out, client create/update/archive/delete, product and document events, team and role changes.

## Honest limitations (Phase 1)

- No AI analysis, crawling, research or buyer discovery runs yet (Phases 2–4).
- No refresh tokens; access token is held in `sessionStorage` (local prototype).
- Registration is open; team members are added by admins with a temporary password (no email invites yet).
- Uploaded files are not virus-scanned.
- GitHub Pages preview has no backend; it runs the browser sandbox.

## Phase 2: Client Intelligence Engine

- **Tables (migration `0002`):** business_profiles, product_applications, target_markets, buyer_personas, business_insights, evidence_sources, analysis_jobs, document_extractions, website_snapshots. Every row carries `tenant_id`.
- **AI providers:** Gemini (long analysis) and Groq (fast calls), free tiers, chosen by env vars (`AI_ANALYSIS_PROVIDER`, `AI_FAST_PROVIDER`, `GEMINI_API_KEY`, `GROQ_API_KEY`). Keys stay on the server.
- **Pipeline (RQ worker, resumable):** document extraction (PDF/DOCX text; images via Gemini) → website read (SSRF-guarded) → company profile → product intelligence → applications & industries → buyer personas → target markets (India, states, cities, countries, export) → opportunities, risks & gaps. Per-stage status, cancel, retry of failed stages only.
- **Anti-fabrication rules:** facts, specs, prices, MOQ, capacity and certifications are stored only with an exact quote found in a source; otherwise they're dropped and stay "—". Personas, markets, indirect uses and opportunities are always AI hypotheses and can never be shown as Verified.
- **Review:** manager+ approve / reject / send back; any edit clears approval; admin+ can delete (reject keeps the audit trail). Team members can add findings by hand with a source note.
- **UI:** client → Intelligence tab with AI analysis status, Overview, Products & applications, Buyer personas, Target markets, Opportunities, Evidence, History, and a Markdown report download.
- **API:** `GET /api/v1/intelligence/providers`, `POST|GET /api/v1/clients/{id}/intelligence/analyses`, `POST /api/v1/intelligence/analyses/{id}/retry|cancel`, `GET /api/v1/clients/{id}/intelligence`, `GET .../intelligence/report.md`, `GET|POST .../intelligence/findings/{type}`, `PATCH|DELETE /api/v1/intelligence/findings/{type}/{id}`, `POST .../review`, `POST /api/v1/documents/{id}/extract`, `GET /api/v1/documents/{id}/text`.

### Honest limitations (Phase 2)

- AI stages need your own free Gemini and/or Groq key; without one they return 409 and nothing is generated. Extraction still runs.
- The GitHub Pages preview has no server, so it cannot run AI analysis; findings there are added and reviewed by hand and stay in the browser.
- Scanned PDFs without a text layer are marked `no_text` (no OCR yet); image OCR needs the Gemini key.
- The website SSRF guard checks DNS before fetching but is not immune to DNS rebinding; block private egress at the network level in production.
- Free-tier rate limits apply (Gemini/Groq per-minute and per-day caps); long catalogues are truncated to the model's context budget.

## Before any public/VPS deployment

Database backups, rate limiting, secure refresh-token handling (httpOnly cookies), invitation-controlled registration, file scanning (ClamAV), HTTPS, secret management, and security testing.

## Repository layout

```
backend/   FastAPI app (app/), Alembic migrations, pytest suite, Dockerfile
frontend/  Next.js app (src/app), components, typed API layer (src/lib/api), vitest suite
docs/      API collection, OpenAPI spec, logo
docker-compose.yml
```
