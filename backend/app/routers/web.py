"""Phase 3 API: website crawl & audit, competitors, change monitoring, opportunities.
Every route resolves the tenant from the verified token and loads rows through scoped()/get_owned()."""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import delete, func, select

from app.core.config import get_settings
from app.deps import ROLE_RANK, Ctx, get_ctx
from app.models import (Client, Competitor, CompetitorChange, CompetitorSnapshot, CrawledPage, CrawlJob, EvidenceSource,
                        KeywordTopic, Opportunity, SEOFinding, Website, WebsiteAudit)
from app.services.activity import log
from app.services.ai.providers import ProviderNotConfigured, get_provider
from app.services.tenancy import get_owned, scoped
from app.services.web import competitor_discovery, opportunity_analyser, pagespeed_service
from app.services.web.crawler_service import CrawlConfig, domain_of
from app.services.web.runner import run_crawl_job

router = APIRouter(tags=["website & competitor intelligence"])
MAX_COMPETITORS = 30


def _need(ctx: Ctx, role: str) -> None:
    if ROLE_RANK[ctx.user.role] < ROLE_RANK[role]:
        raise HTTPException(403, f"Requires {role} role or higher")


def _now():
    return datetime.now(timezone.utc)


def _enqueue(job: CrawlJob, background: BackgroundTasks, ctx: Ctx) -> None:
    if get_settings().analysis_inline:
        background.add_task(run_crawl_job, job.id)
        return
    try:
        from app.worker import queue
        queue().enqueue(run_crawl_job, job.id, job_timeout=3600)
    except Exception as e:  # noqa: BLE001 - Redis down: say so instead of pretending the crawl runs
        job.status, job.error = "failed", f"Job queue unavailable ({type(e).__name__}). Start Redis and the worker, then retry."
        job.completed_at = _now()
        ctx.db.commit()


def _clean_url(url: str | None) -> str | None:
    try:
        return competitor_discovery.clean_website(url)
    except ValueError as e:
        raise HTTPException(422, str(e))


def _config(raw: dict | None) -> dict:
    try:
        return CrawlConfig.model_validate(raw or {}).model_dump()
    except ValidationError as e:
        raise HTTPException(422, "Invalid crawl settings: " + "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()))


# ------------------------------------------------------------------ serializers
def job_out(j: CrawlJob) -> dict:
    return {k: getattr(j, k) for k in ("id", "client_id", "website_id", "competitor_id", "kind", "trigger", "status", "progress",
                                       "provider", "config", "pages_discovered", "pages_crawled", "pages_failed", "pages_blocked",
                                       "robots", "attempts", "stage", "error", "summary", "started_at", "completed_at", "created_at")}


def site_out(s: Website) -> dict:
    return {k: getattr(s, k) for k in ("id", "client_id", "competitor_id", "url", "domain", "is_client_site", "crawl_config",
                                       "crawl_interval_days", "last_crawled_at", "created_at")}


def page_out(p: CrawledPage, full: bool = False) -> dict:
    keys = ["id", "url", "final_url", "depth", "status_code", "redirect_chain", "content_type", "response_ms", "title",
            "meta_description", "h1", "h2", "canonical", "robots_meta", "lang", "has_viewport", "structured_data", "word_count",
            "external_links_count", "images_total", "images_missing_alt", "page_type", "blocked_by_robots", "retries", "error",
            "discovered_at", "fetched_at"]
    d = {k: getattr(p, k) for k in keys}
    d["internal_links_count"] = len(p.internal_links or [])
    if full:
        d["internal_links"] = p.internal_links
        d["text_preview"] = (p.text or "")[:1500]
    return d


def audit_out(a: WebsiteAudit) -> dict:
    return {k: getattr(a, k) for k in ("id", "client_id", "website_id", "crawl_job_id", "health_score", "summary", "pagespeed",
                                       "page_scores", "recommendations", "created_at")}


def finding_out(f: SEOFinding) -> dict:
    return {k: getattr(f, k) for k in ("id", "page_url", "check", "category", "severity", "message", "observed_value", "source",
                                       "measured", "created_at")}


def comp_out(c: Competitor) -> dict:
    return {k: getattr(c, k) for k in ("id", "client_id", "name", "website", "domain", "category", "relevance", "geography", "notes",
                                       "origin", "status", "domain_valid", "monitor_interval_days", "last_analysed_at",
                                       "positioning", "created_at", "updated_at")}


def snap_out(s: CompetitorSnapshot | None) -> dict | None:
    if not s:
        return None
    return {k: getattr(s, k) for k in ("id", "competitor_id", "crawl_job_id", "captured_at", "homepage", "products", "prices",
                                       "certifications", "locations", "contact", "topics", "seo")} | {"pages_count": len(s.pages or {})}


def change_out(c: CompetitorChange) -> dict:
    return {k: getattr(c, k) for k in ("id", "competitor_id", "snapshot_id", "previous_snapshot_id", "change_type", "url",
                                       "old_value", "new_value", "observed_at")}


def opp_out(ctx: Ctx, rows: list[Opportunity]) -> list[dict]:
    ev: dict[str, list] = {r.id: [] for r in rows}
    if rows:
        for e in ctx.db.scalars(select(EvidenceSource).where(EvidenceSource.tenant_id == ctx.tenant_id,
                                EvidenceSource.finding_type == "opportunity", EvidenceSource.finding_id.in_(list(ev)))).all():
            ev[e.finding_id].append({"id": e.id, "source_type": e.source_type, "source_url": e.source_url, "excerpt": e.excerpt,
                                     "created_at": e.created_at})
    keys = ("id", "client_id", "kind", "title", "description", "rationale", "priority", "next_action", "source_refs", "confidence",
            "origin", "verification_status", "approved", "is_inferred", "edited", "reviewed_by", "reviewed_at", "review_note",
            "created_at", "updated_at")
    return [{k: getattr(r, k) for k in keys} | {"evidence": ev[r.id]} for r in rows]


# ------------------------------------------------------------------ crawler status
@router.get("/api/v1/crawler/status")
def crawler_status(ctx: Ctx = Depends(get_ctx)):
    s = get_settings()
    return {"provider": s.crawler_provider, "firecrawl_configured": bool(s.firecrawl_api_url),
            "pagespeed_configured": pagespeed_service.configured(), "max_pages_limit": s.crawl_max_pages_limit,
            "defaults": CrawlConfig().model_dump(), "competitor_max_pages": s.competitor_max_pages}


# ------------------------------------------------------------------ client website + audits
class WebsiteIn(BaseModel):
    url: str | None = Field(default=None, max_length=500)
    crawl_config: dict | None = None
    crawl_interval_days: int | None = Field(default=None, ge=1, le=365)


def _client_site(ctx: Ctx, client: Client) -> Website | None:
    return ctx.db.scalar(scoped(ctx, Website).where(Website.client_id == client.id, Website.is_client_site.is_(True)))


@router.get("/api/v1/clients/{client_id}/website")
def get_client_website(client_id: str, ctx: Ctx = Depends(get_ctx)):
    client = get_owned(ctx, Client, client_id, "Client")
    site = _client_site(ctx, client)
    job = site and ctx.db.scalar(scoped(ctx, CrawlJob).where(CrawlJob.website_id == site.id).order_by(CrawlJob.created_at.desc()).limit(1))
    audit = site and ctx.db.scalar(scoped(ctx, WebsiteAudit).where(WebsiteAudit.website_id == site.id)
                                   .order_by(WebsiteAudit.created_at.desc()).limit(1))
    return {"website": site_out(site) if site else None, "client_website": client.website,
            "latest_crawl": job_out(job) if job else None, "latest_audit": audit_out(audit) if audit else None}


@router.put("/api/v1/clients/{client_id}/website")
def put_client_website(client_id: str, body: WebsiteIn, ctx: Ctx = Depends(get_ctx)):
    client = get_owned(ctx, Client, client_id, "Client")
    url = _clean_url(body.url) if body.url else None
    if not url and not client.website:
        raise HTTPException(422, "Add the client's website first")
    url = url or _clean_url(client.website)
    if client.website and domain_of(url) != domain_of(client.website):
        raise HTTPException(400, "Only the client's own website can be audited. Update the client's website first.")
    site = _client_site(ctx, client)
    if site is None:
        site = Website(tenant_id=ctx.tenant_id, client_id=client.id, is_client_site=True, url=url, domain=domain_of(url))
        ctx.db.add(site)
    site.url, site.domain = url, domain_of(url)
    if body.crawl_config is not None:
        site.crawl_config = _config(body.crawl_config)
    if "crawl_interval_days" in body.model_fields_set:
        site.crawl_interval_days = body.crawl_interval_days
    ctx.db.flush()
    log(ctx, "website.configured", "website", site.id, f"Crawl settings saved for {site.domain}", client_id=client.id)
    ctx.db.commit()
    return site_out(site)


class StartAudit(BaseModel):
    crawl_config: dict | None = None


@router.post("/api/v1/clients/{client_id}/website-audits", status_code=201)
def start_audit(client_id: str, body: StartAudit, background: BackgroundTasks, ctx: Ctx = Depends(get_ctx)):
    client = get_owned(ctx, Client, client_id, "Client")
    if client.archived_at:
        raise HTTPException(400, "Client is archived")
    site = _client_site(ctx, client)
    if site is None:
        if not client.website:
            raise HTTPException(422, "Add the client's website first")
        url = _clean_url(client.website)
        site = Website(tenant_id=ctx.tenant_id, client_id=client.id, is_client_site=True, url=url, domain=domain_of(url),
                       crawl_config=_config({}))
        ctx.db.add(site)
        ctx.db.flush()
    if ctx.db.scalar(scoped(ctx, CrawlJob).where(CrawlJob.website_id == site.id, CrawlJob.status.in_(("queued", "running")))):
        raise HTTPException(409, "A crawl is already running for this website")
    cfg = _config({**(site.crawl_config or {}), **(body.crawl_config or {})})
    job = CrawlJob(tenant_id=ctx.tenant_id, client_id=client.id, website_id=site.id, kind="audit", config=cfg,
                   provider=get_settings().crawler_provider, created_by=ctx.user.id)
    ctx.db.add(job)
    ctx.db.flush()
    log(ctx, "crawl.started", "crawl", job.id, f"Website audit started for {site.domain}", client_id=client.id)
    ctx.db.commit()
    _enqueue(job, background, ctx)
    return job_out(job)


@router.get("/api/v1/clients/{client_id}/crawls")
def list_crawls(client_id: str, ctx: Ctx = Depends(get_ctx), kind: str | None = None, limit: int = Query(20, ge=1, le=100)):
    get_owned(ctx, Client, client_id, "Client")
    q = scoped(ctx, CrawlJob).where(CrawlJob.client_id == client_id)
    if kind:
        q = q.where(CrawlJob.kind == kind)
    return {"items": [job_out(j) for j in ctx.db.scalars(q.order_by(CrawlJob.created_at.desc()).limit(limit)).all()]}


@router.get("/api/v1/crawls/{job_id}")
def get_crawl(job_id: str, ctx: Ctx = Depends(get_ctx)):
    return job_out(get_owned(ctx, CrawlJob, job_id, "Crawl"))


@router.post("/api/v1/crawls/{job_id}/cancel")
def cancel_crawl(job_id: str, ctx: Ctx = Depends(get_ctx)):
    job = get_owned(ctx, CrawlJob, job_id, "Crawl")
    if job.status not in ("queued", "running"):
        raise HTTPException(400, f"Crawl is already {job.status}")
    job.status, job.completed_at = "cancelled", _now()
    log(ctx, "crawl.cancelled", "crawl", job.id, "Crawl cancelled", client_id=job.client_id)
    ctx.db.commit()
    return job_out(job)


@router.post("/api/v1/crawls/{job_id}/retry")
def retry_crawl(job_id: str, background: BackgroundTasks, ctx: Ctx = Depends(get_ctx)):
    """Resume an interrupted crawl and re-fetch pages that failed with a timeout, network error or 5xx."""
    job = get_owned(ctx, CrawlJob, job_id, "Crawl")
    if job.status not in ("failed", "cancelled"):
        raise HTTPException(400, f"Only failed or cancelled crawls can be retried (this one is {job.status})")
    failed = ctx.db.scalars(scoped(ctx, CrawledPage).where(CrawledPage.crawl_job_id == job.id, CrawledPage.blocked_by_robots.is_(False),
                            (CrawledPage.status_code.is_(None)) | (CrawledPage.status_code >= 500))).all()
    frontier = list(job.frontier or []) + [[p.url, p.depth, 0] for p in failed]
    for p in failed:
        ctx.db.delete(p)
    job.pages_failed = max(0, job.pages_failed - len(failed))
    job.frontier, job.status, job.error, job.completed_at = frontier, "queued", None, None
    job.attempts += 1
    log(ctx, "crawl.retried", "crawl", job.id, f"Crawl resumed (attempt {job.attempts}, {len(failed)} failed pages re-queued)",
        client_id=job.client_id)
    ctx.db.commit()
    _enqueue(job, background, ctx)
    return job_out(job)


@router.get("/api/v1/crawls/{job_id}/pages")
def crawl_pages(job_id: str, ctx: Ctx = Depends(get_ctx), status: Literal["ok", "failed", "blocked", "redirected"] | None = None,
                page_type: str | None = None, q: str | None = None, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    job = get_owned(ctx, CrawlJob, job_id, "Crawl")
    stmt = scoped(ctx, CrawledPage).where(CrawledPage.crawl_job_id == job.id)
    if status == "ok":
        stmt = stmt.where(CrawledPage.status_code < 400, CrawledPage.blocked_by_robots.is_(False))
    elif status == "failed":
        stmt = stmt.where(CrawledPage.blocked_by_robots.is_(False), (CrawledPage.status_code.is_(None)) | (CrawledPage.status_code >= 400))
    elif status == "blocked":
        stmt = stmt.where(CrawledPage.blocked_by_robots.is_(True))
    if page_type:
        stmt = stmt.where(CrawledPage.page_type == page_type)
    if q:
        stmt = stmt.where(CrawledPage.url.ilike(f"%{q[:100]}%") | CrawledPage.title.ilike(f"%{q[:100]}%"))
    rows = ctx.db.scalars(stmt.order_by(CrawledPage.depth, CrawledPage.url)).all()
    if status == "redirected":
        rows = [r for r in rows if r.redirect_chain]
    return {"items": [page_out(p) for p in rows[offset:offset + limit]], "total": len(rows)}


@router.get("/api/v1/crawled-pages/{page_id}")
def crawled_page(page_id: str, ctx: Ctx = Depends(get_ctx)):
    return page_out(get_owned(ctx, CrawledPage, page_id, "Page"), full=True)


@router.get("/api/v1/clients/{client_id}/website-audits")
def list_audits(client_id: str, ctx: Ctx = Depends(get_ctx)):
    get_owned(ctx, Client, client_id, "Client")
    rows = ctx.db.scalars(scoped(ctx, WebsiteAudit).where(WebsiteAudit.client_id == client_id)
                          .order_by(WebsiteAudit.created_at.desc()).limit(50)).all()
    return {"items": [audit_out(a) for a in rows]}


@router.get("/api/v1/website-audits/{audit_id}")
def get_audit(audit_id: str, ctx: Ctx = Depends(get_ctx)):
    return audit_out(get_owned(ctx, WebsiteAudit, audit_id, "Audit"))


@router.get("/api/v1/website-audits/{audit_id}/findings")
def audit_findings(audit_id: str, ctx: Ctx = Depends(get_ctx), category: str | None = None, severity: str | None = None,
                   source: str | None = None, page_url: str | None = None):
    a = get_owned(ctx, WebsiteAudit, audit_id, "Audit")
    stmt = scoped(ctx, SEOFinding).where(SEOFinding.audit_id == a.id)
    for col, val in ((SEOFinding.category, category), (SEOFinding.severity, severity), (SEOFinding.source, source),
                     (SEOFinding.page_url, page_url)):
        if val:
            stmt = stmt.where(col == val)
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    rows = sorted(ctx.db.scalars(stmt).all(), key=lambda f: (order.get(f.severity, 9), f.check, f.page_url or ""))
    return {"items": [finding_out(f) for f in rows], "total": len(rows)}


@router.get("/api/v1/website-audits/{audit_id}/topics")
def audit_topics(audit_id: str, ctx: Ctx = Depends(get_ctx)):
    a = get_owned(ctx, WebsiteAudit, audit_id, "Audit")
    rows = ctx.db.scalars(scoped(ctx, KeywordTopic).where(KeywordTopic.audit_id == a.id).order_by(KeywordTopic.pages.desc())).all()
    return {"items": [{"topic": t.topic, "pages": t.pages, "occurrences": t.occurrences, "in_titles": t.in_titles,
                       "example_urls": t.example_urls} for t in rows],
            "basis": "Counted from page titles and headings. Not search volume or rankings."}


def _report(ctx: Ctx, a: WebsiteAudit) -> str:
    site = ctx.db.get(Website, a.website_id)
    client = ctx.db.get(Client, a.client_id)
    job = ctx.db.get(CrawlJob, a.crawl_job_id)
    fs = audit_findings(a.id, ctx)["items"]
    s = a.summary or {}
    L = [f"# Website Audit — {client.company_name}", "", f"Site: {site.url}  ", f"Crawled: {job.completed_at or job.created_at:%d %b %Y %H:%M} UTC "
         f"with the {job.provider} crawler ({job.pages_crawled} pages fetched, {job.pages_failed} failed, {job.pages_blocked} disallowed by robots.txt)", "",
         f"**Technical health score:** {a.health_score if a.health_score is not None else '—'}/100 (crawler-observed; not a ranking or traffic metric)", "",
         "## Summary", "",
         f"- HTTPS: {'yes' if s.get('https') else 'no'} · robots.txt: {'found' if s.get('robots_found') else 'not found'} · sitemap: {'found' if s.get('sitemap_found') else 'not found'}",
         f"- Broken links: {s.get('broken_links', 0)} · redirect chains: {s.get('redirect_chains', 0)} · duplicate titles: {s.get('duplicate_titles', 0)} · missing meta descriptions: {s.get('missing_meta', 0)}", ""]
    ps = a.pagespeed or {}
    L += ["## Performance (measured by Google PageSpeed Insights)", ""]
    if ps.get("results"):
        for r in ps["results"]:
            if r.get("error"):
                L.append(f"- {r['strategy']}: {r['error']}")
            else:
                L.append(f"- {r['strategy']}: performance {r['scores'].get('performance', '—')}, SEO {r['scores'].get('seo', '—')}, "
                         f"accessibility {r['scores'].get('accessibility', '—')}; LCP {r['lab'].get('lcp_ms', '—')} ms, CLS {r['lab'].get('cls', '—')}, TBT {r['lab'].get('tbt_ms', '—')} ms")
    else:
        L.append(f"- — {ps.get('skipped', 'Not measured')}")
    L += ["", "## Findings", ""]
    for sev in ("high", "medium", "low", "info"):
        group = [f for f in fs if f["severity"] == sev]
        if group:
            L += [f"### {sev.title()} ({len(group)})", ""]
            for f in group[:200]:
                L.append(f"- [{f['category']}] {f['message']}" + (f" — {f['page_url']}" if f["page_url"] else "") +
                         (f" (`{f['observed_value'][:120]}`)" if f["observed_value"] else "") + (" *(measured)*" if f["measured"] else ""))
            L.append("")
    L += ["## Recommendations", ""] + ([f"- **{r['title']}** ({r['priority']}): {r['detail']}" for r in a.recommendations] or ["- —"])
    cal = s.get("content_calendar") or []
    L += ["", "## Content calendar (suggestions)", ""] + ([f"- Week {c['week']}: {c['topic']}" for c in cal] or ["- —"])
    return "\n".join(L) + "\n"


@router.get("/api/v1/website-audits/{audit_id}/report.md", response_class=PlainTextResponse)
def audit_report(audit_id: str, ctx: Ctx = Depends(get_ctx)):
    return _report(ctx, get_owned(ctx, WebsiteAudit, audit_id, "Audit"))


@router.get("/api/v1/website-audits/{audit_id}/findings.csv", response_class=PlainTextResponse)
def audit_csv(audit_id: str, ctx: Ctx = Depends(get_ctx)):
    a = get_owned(ctx, WebsiteAudit, audit_id, "Audit")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["severity", "category", "check", "message", "page_url", "observed_value", "source", "measured"])
    for f in audit_findings(a.id, ctx)["items"]:
        w.writerow([f["severity"], f["category"], f["check"], f["message"], f["page_url"] or "", f["observed_value"] or "", f["source"], f["measured"]])
    return PlainTextResponse(buf.getvalue(), media_type="text/csv")


# ------------------------------------------------------------------ competitors
class CompetitorIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    website: str | None = Field(default=None, max_length=300)
    category: Literal["direct", "indirect", "substitute", "aspirational"] = "direct"
    relevance: dict[str, str] = Field(default_factory=dict)
    geography: list[str] = Field(default_factory=list, max_length=20)
    notes: str | None = Field(default=None, max_length=2000)
    monitor_interval_days: int | None = Field(default=None, ge=1, le=365)

    @field_validator("relevance")
    @classmethod
    def _rel(cls, v: dict) -> dict:
        bad = set(v) - set(competitor_discovery.RELEVANCE_KEYS)
        if bad:
            raise ValueError(f"relevance keys must be {', '.join(competitor_discovery.RELEVANCE_KEYS)}")
        return {k: s.strip()[:300] for k, s in v.items() if s and s.strip()}


class CompetitorPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    website: str | None = Field(default=None, max_length=300)
    category: Literal["direct", "indirect", "substitute", "aspirational"] | None = None
    relevance: dict[str, str] | None = None
    geography: list[str] | None = None
    notes: str | None = None
    monitor_interval_days: int | None = Field(default=None, ge=1, le=365)
    status: Literal["active", "archived"] | None = None


def _set_website(ctx: Ctx, c: Competitor, client: Client, website: str | None) -> None:
    try:
        site = competitor_discovery.clean_website(website)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if site and client.website and domain_of(site) == domain_of(client.website):
        raise HTTPException(400, "That is the client's own website")
    if site:
        dup = ctx.db.scalar(scoped(ctx, Competitor).where(Competitor.client_id == client.id, Competitor.domain == domain_of(site),
                                                          Competitor.id != c.id))
        if dup:
            raise HTTPException(409, f"{dup.name} already uses that domain")
    c.website, c.domain = site, domain_of(site) if site else None
    c.domain_valid, reason = competitor_discovery.validate_domain(site)
    if c.domain_valid is False:
        raise HTTPException(422, f"Domain check failed: {reason}")


@router.get("/api/v1/clients/{client_id}/competitors")
def list_competitors(client_id: str, ctx: Ctx = Depends(get_ctx), status: str | None = None):
    get_owned(ctx, Client, client_id, "Client")
    stmt = scoped(ctx, Competitor).where(Competitor.client_id == client_id)
    stmt = stmt.where(Competitor.status == status) if status else stmt.where(Competitor.status.in_(("active", "suggested")))
    return {"items": [comp_out(c) for c in ctx.db.scalars(stmt.order_by(Competitor.created_at)).all()]}


@router.post("/api/v1/clients/{client_id}/competitors", status_code=201)
def add_competitor(client_id: str, body: CompetitorIn, ctx: Ctx = Depends(get_ctx)):
    client = get_owned(ctx, Client, client_id, "Client")
    n = ctx.db.scalar(select(func.count()).select_from(Competitor).where(Competitor.tenant_id == ctx.tenant_id,
                      Competitor.client_id == client.id, Competitor.status == "active"))
    if n >= MAX_COMPETITORS:
        raise HTTPException(400, f"A client can track up to {MAX_COMPETITORS} competitors")
    c = Competitor(tenant_id=ctx.tenant_id, client_id=client.id, name=body.name.strip(), category=body.category,
                   relevance=body.relevance, geography=[g.strip()[:100] for g in body.geography if g.strip()], notes=body.notes,
                   monitor_interval_days=body.monitor_interval_days, origin="user", status="active", created_by=ctx.user.id)
    _set_website(ctx, c, client, body.website)
    ctx.db.add(c)
    ctx.db.flush()
    log(ctx, "competitor.added", "competitor", c.id, f"Competitor {c.name} added to {client.company_name}", client_id=client.id)
    ctx.db.commit()
    return comp_out(c)


@router.patch("/api/v1/competitors/{comp_id}")
def edit_competitor(comp_id: str, body: CompetitorPatch, ctx: Ctx = Depends(get_ctx)):
    c = get_owned(ctx, Competitor, comp_id, "Competitor")
    client = ctx.db.get(Client, c.client_id)
    data = body.model_dump(exclude_unset=True)
    if "website" in data:
        _set_website(ctx, c, client, data.pop("website"))
    if "relevance" in data and data["relevance"] is not None:
        data["relevance"] = CompetitorIn(name="xx", relevance=data["relevance"]).relevance
    for k, v in data.items():
        setattr(c, k, v)
    log(ctx, "competitor.edited", "competitor", c.id, f"Competitor {c.name} updated", client_id=c.client_id)
    ctx.db.commit()
    return comp_out(c)


@router.delete("/api/v1/competitors/{comp_id}", status_code=204)
def delete_competitor(comp_id: str, ctx: Ctx = Depends(get_ctx)):
    _need(ctx, "manager")
    c = get_owned(ctx, Competitor, comp_id, "Competitor")
    log(ctx, "competitor.deleted", "competitor", c.id, f"Competitor {c.name} deleted", client_id=c.client_id)
    ctx.db.delete(c)
    ctx.db.commit()


class CompReview(BaseModel):
    action: Literal["accept", "reject"]


@router.post("/api/v1/competitors/{comp_id}/review")
def review_competitor(comp_id: str, body: CompReview, ctx: Ctx = Depends(get_ctx)):
    _need(ctx, "manager")
    c = get_owned(ctx, Competitor, comp_id, "Competitor")
    if body.action == "accept":
        n = ctx.db.scalar(select(func.count()).select_from(Competitor).where(Competitor.tenant_id == ctx.tenant_id,
                          Competitor.client_id == c.client_id, Competitor.status == "active"))
        if c.status != "active" and n >= MAX_COMPETITORS:
            raise HTTPException(400, f"A client can track up to {MAX_COMPETITORS} competitors")
        c.status = "active"
    else:
        c.status = "rejected"
    log(ctx, f"competitor.{body.action}ed", "competitor", c.id, f"Competitor suggestion {c.name} {body.action}ed", client_id=c.client_id)
    ctx.db.commit()
    return comp_out(c)


@router.post("/api/v1/clients/{client_id}/competitors/suggest")
def suggest_competitors(client_id: str, ctx: Ctx = Depends(get_ctx)):
    client = get_owned(ctx, Client, client_id, "Client")
    try:
        get_provider("fast")
    except ProviderNotConfigured as e:
        raise HTTPException(409, str(e))
    try:
        res = competitor_discovery.suggest(ctx.db, ctx.tenant_id, client)
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    log(ctx, "competitor.suggested", "client", client.id, f"{res['created']} competitor suggestions added for {client.company_name}",
        client_id=client.id, dropped=res["dropped"])
    ctx.db.commit()
    return res


@router.post("/api/v1/competitors/{comp_id}/analyse", status_code=201)
def analyse_competitor(comp_id: str, body: StartAudit, background: BackgroundTasks, ctx: Ctx = Depends(get_ctx)):
    c = get_owned(ctx, Competitor, comp_id, "Competitor")
    if c.status != "active":
        raise HTTPException(400, "Accept the competitor before analysing it")
    if not c.website:
        raise HTTPException(422, "Add the competitor's website first")
    site = ctx.db.scalar(scoped(ctx, Website).where(Website.competitor_id == c.id))
    if site is None:
        site = Website(tenant_id=ctx.tenant_id, client_id=c.client_id, competitor_id=c.id, is_client_site=False, url=c.website,
                       domain=c.domain, crawl_config=_config({"max_pages": get_settings().competitor_max_pages, "max_depth": 2}))
        ctx.db.add(site)
        ctx.db.flush()
    site.url, site.domain = c.website, c.domain
    if ctx.db.scalar(scoped(ctx, CrawlJob).where(CrawlJob.website_id == site.id, CrawlJob.status.in_(("queued", "running")))):
        raise HTTPException(409, "An analysis is already running for this competitor")
    cfg = _config({**(site.crawl_config or {}), **(body.crawl_config or {})})
    cfg["max_pages"] = min(cfg["max_pages"], get_settings().competitor_max_pages * 4)
    job = CrawlJob(tenant_id=ctx.tenant_id, client_id=c.client_id, website_id=site.id, competitor_id=c.id, kind="competitor",
                   config=cfg, provider=get_settings().crawler_provider, created_by=ctx.user.id)
    ctx.db.add(job)
    ctx.db.flush()
    log(ctx, "competitor.analysis_started", "competitor", c.id, f"Competitor analysis started for {c.name}", client_id=c.client_id)
    ctx.db.commit()
    _enqueue(job, background, ctx)
    return job_out(job)


def _latest_snap(ctx: Ctx, comp_id: str) -> CompetitorSnapshot | None:
    return ctx.db.scalar(scoped(ctx, CompetitorSnapshot).where(CompetitorSnapshot.competitor_id == comp_id)
                         .order_by(CompetitorSnapshot.captured_at.desc()).limit(1))


@router.get("/api/v1/competitors/{comp_id}")
def competitor_profile(comp_id: str, ctx: Ctx = Depends(get_ctx)):
    c = get_owned(ctx, Competitor, comp_id, "Competitor")
    job = ctx.db.scalar(scoped(ctx, CrawlJob).where(CrawlJob.competitor_id == c.id).order_by(CrawlJob.created_at.desc()).limit(1))
    n = ctx.db.scalar(select(func.count()).select_from(CompetitorSnapshot).where(CompetitorSnapshot.tenant_id == ctx.tenant_id,
                      CompetitorSnapshot.competitor_id == c.id))
    return {"competitor": comp_out(c), "latest_snapshot": snap_out(_latest_snap(ctx, c.id)), "snapshots": n,
            "latest_crawl": job_out(job) if job else None}


@router.get("/api/v1/competitors/{comp_id}/changes")
def competitor_changes(comp_id: str, ctx: Ctx = Depends(get_ctx)):
    c = get_owned(ctx, Competitor, comp_id, "Competitor")
    rows = ctx.db.scalars(scoped(ctx, CompetitorChange).where(CompetitorChange.competitor_id == c.id)
                          .order_by(CompetitorChange.observed_at.desc()).limit(500)).all()
    return {"items": [change_out(r) for r in rows]}


@router.get("/api/v1/clients/{client_id}/competitor-changes")
def client_competitor_changes(client_id: str, ctx: Ctx = Depends(get_ctx), change_type: str | None = None):
    get_owned(ctx, Client, client_id, "Client")
    stmt = scoped(ctx, CompetitorChange).where(CompetitorChange.client_id == client_id)
    if change_type:
        stmt = stmt.where(CompetitorChange.change_type == change_type)
    names = {c.id: c.name for c in ctx.db.scalars(scoped(ctx, Competitor).where(Competitor.client_id == client_id)).all()}
    rows = ctx.db.scalars(stmt.order_by(CompetitorChange.observed_at.desc()).limit(500)).all()
    return {"items": [change_out(r) | {"competitor_name": names.get(r.competitor_id)} for r in rows]}


@router.get("/api/v1/clients/{client_id}/competitors/comparison")
def comparison(client_id: str, ctx: Ctx = Depends(get_ctx)):
    """Side by side, from crawler observations only (no traffic, ranking or revenue)."""
    client = get_owned(ctx, Client, client_id, "Client")
    audit, pages = opportunity_analyser.latest_client_audit(ctx.db, ctx.tenant_id, client.id)
    from app.services.web.competitor_analyser import extract
    me = extract(pages, domain_of(client.website) if client.website else None) if pages else None
    rows = []
    if me:
        rows.append({"id": None, "name": client.company_name, "is_client": True, "website": client.website,
                     "captured_at": audit.created_at, "pages": me["seo"]["pages"], "product_pages": me["seo"]["product_pages"],
                     "prices_published": len(me["prices"]), "certifications": [c["name"] for c in me["certifications"]],
                     "locations": [x["name"] for x in me["locations"]], "schema_types": me["seo"]["schema_types"],
                     "avg_words": me["seo"]["avg_words"], "https": me["seo"]["https"], "health_score": audit.health_score,
                     "topics": me["topics"][:15]})
    for c, s in opportunity_analyser.latest_snapshots(ctx.db, ctx.tenant_id, client.id):
        seo = s.seo or {}
        rows.append({"id": c.id, "name": c.name, "is_client": False, "website": c.website, "captured_at": s.captured_at,
                     "pages": seo.get("pages"), "product_pages": seo.get("product_pages"), "prices_published": len(s.prices or []),
                     "certifications": [x["name"] for x in s.certifications or []], "locations": [x["name"] for x in s.locations or []],
                     "schema_types": seo.get("schema_types") or [], "avg_words": seo.get("avg_words"), "https": seo.get("https"),
                     "health_score": None, "topics": (s.topics or [])[:15]})
    client_topics = set(me["topics"]) if me else set()
    for r in rows:
        r["shared_topics"] = sorted(set(r["topics"]) & client_topics) if not r["is_client"] else []
    return {"items": rows, "basis": "Crawler observations of public pages. Health score is only computed for the client's audited site."}


# ------------------------------------------------------------------ opportunities
@router.post("/api/v1/clients/{client_id}/opportunities/analyse")
def analyse_opportunities(client_id: str, ctx: Ctx = Depends(get_ctx)):
    client = get_owned(ctx, Client, client_id, "Client")
    res = opportunity_analyser.run(ctx.db, ctx.tenant_id, client)
    log(ctx, "opportunities.analysed", "client", client.id, f"{res['created']} new opportunities for {client.company_name}",
        client_id=client.id)
    ctx.db.commit()
    return res


@router.get("/api/v1/clients/{client_id}/opportunities")
def list_opportunities(client_id: str, ctx: Ctx = Depends(get_ctx), status: str | None = None, kind: str | None = None,
                       include_rejected: bool = False):
    get_owned(ctx, Client, client_id, "Client")
    stmt = scoped(ctx, Opportunity).where(Opportunity.client_id == client_id)
    if status == "approved":
        stmt = stmt.where(Opportunity.approved.is_(True))
    elif status:
        stmt = stmt.where(Opportunity.verification_status == status)
    elif not include_rejected:
        stmt = stmt.where(Opportunity.verification_status != "rejected")
    if kind:
        stmt = stmt.where(Opportunity.kind == kind)
    order = {"high": 0, "medium": 1, "low": 2}
    rows = sorted(ctx.db.scalars(stmt).all(), key=lambda o: (order.get(o.priority, 3), o.created_at))
    return {"items": opp_out(ctx, rows), "total": len(rows)}


class OppReview(BaseModel):
    action: Literal["approve", "reject", "needs_review"]
    note: str | None = Field(default=None, max_length=2000)


class OppPatch(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=300)
    description: str | None = Field(default=None, max_length=4000)
    priority: Literal["high", "medium", "low"] | None = None
    next_action: str | None = Field(default=None, max_length=2000)


@router.post("/api/v1/opportunities/{opp_id}/review")
def review_opportunity(opp_id: str, body: OppReview, ctx: Ctx = Depends(get_ctx)):
    _need(ctx, "manager")
    o = get_owned(ctx, Opportunity, opp_id, "Opportunity")
    # Recommendations are never facts: approval means "approved to act on", status stays a hypothesis.
    if body.action == "approve":
        o.approved, o.verification_status = True, "ai_hypothesis" if o.origin == "ai" else "needs_review"
    elif body.action == "reject":
        o.approved, o.verification_status = False, "rejected"
    else:
        o.approved, o.verification_status = False, "needs_review"
    o.reviewed_by, o.reviewed_at, o.review_note = ctx.user.id, _now(), body.note
    log(ctx, f"opportunity.{body.action}", "opportunity", o.id, f"Opportunity “{o.title[:80]}” {body.action.replace('_', ' ')}",
        client_id=o.client_id)
    ctx.db.commit()
    return opp_out(ctx, [o])[0]


@router.patch("/api/v1/opportunities/{opp_id}")
def edit_opportunity(opp_id: str, body: OppPatch, ctx: Ctx = Depends(get_ctx)):
    o = get_owned(ctx, Opportunity, opp_id, "Opportunity")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(o, k, v)
    o.edited, o.approved = True, False
    if o.verification_status == "rejected":
        o.verification_status = "needs_review"
    log(ctx, "opportunity.edited", "opportunity", o.id, "Opportunity edited", client_id=o.client_id)
    ctx.db.commit()
    return opp_out(ctx, [o])[0]


@router.delete("/api/v1/opportunities/{opp_id}", status_code=204)
def delete_opportunity(opp_id: str, ctx: Ctx = Depends(get_ctx)):
    _need(ctx, "admin")
    o = get_owned(ctx, Opportunity, opp_id, "Opportunity")
    ctx.db.execute(delete(EvidenceSource).where(EvidenceSource.finding_type == "opportunity", EvidenceSource.finding_id == o.id))
    ctx.db.delete(o)
    log(ctx, "opportunity.deleted", "opportunity", opp_id, "Opportunity deleted", client_id=o.client_id)
    ctx.db.commit()
