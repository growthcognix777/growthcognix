<p align="center"><img src="docs/logo.png" alt="GrowthCognix" width="420"></p>

# GrowthCognix

A multi-tenant AI business growth and marketing intelligence platform for digital marketing agencies.
**Discover → Analyse → Market → Acquire → Sell → Retain → Grow.**

**Live preview:** https://growthcognix777.github.io/growthcognix/ — runs in *browser sandbox* mode (see below).

> Status: **Phase 4 — Global Buyer Discovery & Lead Intelligence** (this release). Local development build, not a production SaaS release.

## Roadmap (7 phases)

| Phase | Module | Status |
|---|---|---|
| 1 | Foundation: auth, agency dashboard, clients, products, documents, agent centre, research jobs, activity log | ✅ Released |
| 2 | Client Intelligence Engine (document extraction, business profiles, applications, personas, markets, evidence & review) | ✅ Released |
| 3 | Website Audit & Competitor Intelligence (native crawler or Firecrawl, PageSpeed, monitoring, opportunities) | ✅ Released |
| 4 | Global Buyer Discovery & Lead Intelligence (India + export markets, 100-pt lead score) | ✅ This release |
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

## Phase 3: Website Audit & Competitor Intelligence

- **Tables (migration `0003`):** websites, crawl_jobs, crawled_pages, website_audits, seo_findings, keyword_topics, competitors, competitor_snapshots, competitor_changes, opportunities. Opportunity evidence reuses Phase 2's `evidence_sources` (one evidence store, no duplicate ResearchSource table).
- **Crawler (`app/services/web/`):** one interface, two adapters: `opencrawl_adapter.py` (built-in, free, default) and `firecrawl_adapter.py` (self-hosted Firecrawl or cloud via `FIRECRAWL_API_URL`/`FIRECRAWL_API_KEY`, `CRAWLER_PROVIDER=firecrawl`). Obeys robots.txt (Crawl-delay raises our delay; an inaccessible robots.txt means no crawl), sitemap seeding, max pages/depth, delay + concurrency rate limit, include/exclude globs, retries for timeouts/5xx, cancel, resume from the saved frontier, scheduled re-crawls.
- **Security:** SSRF guard on every URL and every redirect hop (public DNS only, ports 80/443, no credentials), HTML/XML/text only, size and time caps, no logins/paywall/anti-bot bypassing, keys server-side only.
- **Technical audit:** HTTPS, availability, viewport, titles/meta (missing, length, duplicates), H1/H2, canonical, noindex, robots.txt, sitemap, broken internal links, redirect chains, image alt, duplicate content, thin content, orphan pages, lang, schema.org (JSON-LD + microdata). Crawler-observed health score 0–100, explicitly not a ranking metric.
- **PageSpeed Insights:** mobile + desktop Lighthouse scores and Core Web Vitals (lab, plus CrUX field data when Google has it), stored as *measured*; skipped, not faked, without `PAGESPEED_API_KEY`.
- **SEO & content:** page scores, topic coverage from titles/headings (not search volume), product-page, industry, location and local-SEO recommendations, a suggested content calendar.
- **Competitors:** manual entry (relevance by product/application/customer/geography required, domain validated, max 30 active), AI suggestions (Groq/Gemini) stored as *suggested* until accepted, crawling, snapshots of published products, prices (copied as published), certifications, locations, role-based business contacts, topics, optional AI positioning (labelled).
- **Monitoring:** snapshot diff → page added/removed, title/description changes, homepage messaging, product added/removed, price changes, promotions, certifications, locations, contact changes, each with old value, new value, source URL and date. `scheduler` service queues due re-crawls hourly.
- **Opportunities:** rule-based from the client audit vs competitor snapshots vs Phase 2 intelligence: content gaps, missing prices/certifications, differentiation, industry and location pages, underserved segments, conversion paths. Each has rationale, evidence, sources, priority, confidence, next action; reviewed by managers; never states competitor revenue, customers, traffic, market share or ad spend.
- **UI:** client → Website & competitors with 12 screens: overview, crawl settings, pages, technical audit, performance, keywords & content, competitors, competitor profile, comparison, change history, opportunities, report (Markdown + CSV export).

### Honest limitations (Phase 3)

- Crawling needs the backend; the GitHub Pages preview can only store competitors.
- No JavaScript rendering in the native crawler (single-page apps show little text); use the Firecrawl adapter for those.
- Broken links are detected among crawled pages only; links beyond the page limit are not checked. External links are not checked.
- Topic coverage is not keyword research: no search volumes or rankings until Search Console is connected (later phase).
- PageSpeed needs a free Google API key and measures the home page only.
- Location and certification detection uses pattern lists; unusual names may be missed.
- Same DNS-rebinding caveat as Phase 2: block private egress at the network level in production.

## Phase 4: Global Buyer Discovery & Lead Intelligence

- **Tables (migration `0004`):** geographic_areas, discovery_campaigns, discovery_targets, prospect_companies, prospect_product_fits, business_contacts, lead_scores, lead_verifications, lead_assignments, trade_market_insights, suppression_entries. Buyer profiles extend the Phase 2 `buyer_personas` table (buyer type, direct/indirect industry, applications, company types, problems solved, substitutes, geography, rationale). Lead evidence reuses `evidence_sources` (now with field, provider, observed_at).
- **Buyer profiles:** add by hand, or generate with Gemini/Groq from the client's products, documents and Phase 2 applications. AI profiles are hypotheses until a manager approves them; campaigns only use approved or team-added profiles.
- **Research areas:** Global > Country > State > District > City > Industrial area. Countries and Indian states/UTs are validated against official names; districts, cities and clusters are added by the team (optionally with the source list URL). Nothing else is pre-filled.
- **Discovery campaigns (RQ worker):** profile × area × source searches. Sources: SearXNG (self-hosted, free), Google Programmable Search (~100 free queries/day), Brave Search API (metered, $5/month credit, card required), and public directory/association pages you supply (robots-aware). Daily limits per source, retry with backoff, pause/resume/cancel, idempotent resume, per-target progress. Bing (retired Aug 2025), IndiaMART/TradeIndia (terms), GeM, MCA and ITC Trade Map are manual-only and listed as such.
- **Prospects:** deduplicated by normalised domain; marketplace/social/listing sites, the client's own site, its competitors and do-not-contact domains are skipped. A search hit only makes a company `discovered`; the worker then reads up to 3 pages of its own site (robots-aware, SSRF-guarded) and records application/industry terms, buying signals (tenders, RFQs, procurement notices, explicit supplier requests, expansion), capacity signals, places named and published role contacts, each with page URL and excerpt. Personal email addresses are never collected.
- **Verification:** discovered → company → website → industry → product relevance → contact verified, plus needs review / rejected. Only "website" can be set by the system (it fetched the site); every other field needs a person with a note or source URL, and every decision is logged.
- **Lead score (0–100):** fit 30, need 25, intent & timing 20, capacity 15, contact 10 (weights editable, must total 100). Classes: very high 80+, high 65+, medium 40+, low. Search appearance earns nothing; intent is 0 without real evidence. A separate confidence score reflects verification depth and freshness (reduced after 180 days, zero when rejected). Every point has a written reason; history is kept.
- **Assignment, approval, export, CRM:** assign prospects to team members; approve only after a person verified the company; export approved prospects as CSV or Excel (formula-injection guarded, suppressed contacts removed); hand approved prospects to the CRM (Phase 6 reads them). Nothing contacts anyone.
- **Trade data:** UN Comtrade public preview (no key, 500 rows per call) stored as *historical trade*, never as current demand or obtainable revenue; manual insights for tariffs, certifications, regulations, logistics, trade agreements and demand signals, each with a source URL.
- **UI:** client → Buyer discovery with 12 screens: overview, buyer profiles, market explorer, India districts & clusters, international markets, campaigns, prospect database, prospect detail & evidence, lead scoring, verification queue, assignment, export & CRM. The sidebar "Buyer discovery" page lists every client's numbers.

### Honest limitations (Phase 4)

- Discovery needs the backend and at least one configured search source (`SEARXNG_URL`, `GOOGLE_PSE_KEY` + `GOOGLE_PSE_CX`, or `BRAVE_API_KEY`). The GitHub Pages preview stores profiles, areas and prospects you add yourself, and refuses campaigns, site checks, AI profiles, Comtrade and Excel export (409) rather than simulating them.
- Search results reflect the search engine, not a complete list of companies in an area. Small firms without websites are found only through directories or manual entry.
- Site checks read up to 3 pages without JavaScript rendering; term matching is literal and can miss synonyms.
- Industry, location and company facts are never inferred from search results; a person verifies them.
- Comtrade figures are annual and lag by one or two years; the public preview returns at most 500 rows per call.
- Overlaps to reconcile in Phase 6: prospect companies/contacts vs CRM companies/contacts; the suppression list is shared with outreach.

## Before any public/VPS deployment

Database backups, rate limiting, secure refresh-token handling (httpOnly cookies), invitation-controlled registration, file scanning (ClamAV), HTTPS, secret management, and security testing.

## Repository layout

```
backend/   FastAPI app (app/), Alembic migrations, pytest suite, Dockerfile
frontend/  Next.js app (src/app), components, typed API layer (src/lib/api), vitest suite
docs/      API collection, OpenAPI spec, logo
docker-compose.yml
```
