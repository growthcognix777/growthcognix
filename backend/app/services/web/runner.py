"""Runs a CrawlJob on the RQ worker: crawl, then either the audit pipeline (client site) or the
competitor pipeline (snapshot + change detection). Pages are committed per batch, so a failure or a
restart keeps progress and a retry resumes from the saved frontier."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import ActivityLog, CrawledPage, CrawlJob, SEOFinding, WebsiteAudit
from app.services.web import competitor_analyser, competitor_monitor, crawler_service, pagespeed_service, seo_analyser, website_audit

log = logging.getLogger(__name__)


def _now():
    return datetime.now(timezone.utc)


def run_crawl_job(job_id: str, crawler=None) -> None:
    db = SessionLocal()
    try:
        _run(db, job_id, crawler)
    finally:
        db.close()


def _fail(db, job: CrawlJob, msg: str) -> None:
    job.status, job.error, job.completed_at = "failed", msg[:2000], _now()
    db.add(ActivityLog(tenant_id=job.tenant_id, user_id=job.created_by, action="crawl.failed", entity_type="crawl",
                       entity_id=job.id, summary=f"Crawl failed: {msg[:200]}", meta={"client_id": job.client_id}))
    db.commit()


def _run(db, job_id: str, crawler) -> None:
    job = db.get(CrawlJob, job_id)
    if job is None or job.status not in ("queued", "running"):
        return
    job.status, job.started_at, job.error, job.stage = "running", job.started_at or _now(), None, "crawl"
    db.commit()
    try:
        summary = crawler_service.run_crawl(db, job, crawler)
    except Exception as e:  # noqa: BLE001 - record and keep the frontier for a retry
        log.exception("crawl %s failed", job_id)
        db.rollback()
        job = db.get(CrawlJob, job_id)
        _fail(db, job, f"Crawl stopped: {type(e).__name__}: {e}")
        return
    db.refresh(job)
    if job.status == "cancelled":
        job.summary = summary
        db.commit()
        return
    if job.pages_crawled == 0:
        reason = (job.robots or {}).get("note") or "No page could be fetched"
        if job.pages_blocked:
            reason = "Every page is disallowed by robots.txt; nothing was crawled"
        first = db.scalar(select(CrawledPage).where(CrawledPage.crawl_job_id == job.id, CrawledPage.error.is_not(None)).limit(1))
        if first and not job.pages_blocked:
            reason += f" ({first.error})"
        job.summary = summary
        _fail(db, job, reason)
        return
    try:
        if job.kind == "competitor":
            job.stage = "snapshot"
            snap = competitor_analyser.run(db, job, summary)
            job.stage = "changes"
            summary["changes"] = competitor_monitor.run(db, snap)
            summary["snapshot_id"] = snap.id
        else:
            job.stage = "audit"
            audit = WebsiteAudit(tenant_id=job.tenant_id, client_id=job.client_id, website_id=job.website_id, crawl_job_id=job.id)
            db.add(audit)
            db.flush()
            summary.update(website_audit.run(db, job, audit))
            job.stage = "seo"
            summary.update(seo_analyser.run(db, job, audit))
            if pagespeed_service.configured():
                job.stage = "pagespeed"
                from app.models import Website
                target = db.get(Website, job.website_id).url
                results = [pagespeed_service.measure(target, s) for s in ("mobile", "desktop")] if target else []
                audit.pagespeed = {"results": results}
                for r in results:
                    for check, sev, msg, val in pagespeed_service.findings(r):
                        db.add(SEOFinding(tenant_id=job.tenant_id, client_id=job.client_id, audit_id=audit.id, page_url=r.get("url"),
                                          check=check, category="performance", severity=sev, message=msg, observed_value=val,
                                          source="pagespeed", measured=True))
            else:
                audit.pagespeed = {"skipped": "PAGESPEED_API_KEY is not configured; no performance metrics were measured."}
            summary["audit_id"] = audit.id
        job.stage, job.status, job.progress, job.completed_at, job.summary = None, "completed", 100, _now(), summary
        db.add(ActivityLog(tenant_id=job.tenant_id, user_id=job.created_by, action="crawl.completed", entity_type="crawl",
                           entity_id=job.id, summary=f"{'Competitor' if job.kind == 'competitor' else 'Website'} crawl completed: "
                           f"{job.pages_crawled} pages", meta={"client_id": job.client_id}))
        db.commit()
    except Exception as e:  # noqa: BLE001
        log.exception("post-crawl stage failed for %s", job_id)
        db.rollback()
        job = db.get(CrawlJob, job_id)
        _fail(db, job, f"{job.stage or 'analysis'} failed: {type(e).__name__}: {e}")
