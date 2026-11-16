"""Runs an AnalysisJob stage by stage. Called by the RQ worker (never inside an HTTP request unless
ANALYSIS_INLINE=true for local development/tests).

Each stage commits on success, so a failure keeps earlier results. A retry re-runs only the stages
that failed or never ran.
"""
from __future__ import annotations

import logging
import traceback

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import ActivityLog, AnalysisJob, Client, Product
from app.services.ai.providers import ProviderNotConfigured, get_provider
from app.services.intelligence import (buyer_persona_generator, document_extractor, industry_mapper,
                                       intelligence_report, market_analyser, product_analyser, website_analyser)
from app.services.intelligence.common import Context, StageError, build_sources, now

log = logging.getLogger(__name__)

STAGES: list[tuple[str, str, object, bool]] = [
    # key, label, runner, needs_ai
    ("extract_documents", "Extract documents", document_extractor.run, False),
    ("fetch_website", "Read website", website_analyser.run, False),
    ("business_profile", "Company profile", intelligence_report.run_profile, True),
    ("product_intelligence", "Product intelligence", product_analyser.run, True),
    ("applications", "Applications & industries", industry_mapper.run, True),
    ("personas", "Buyer personas", buyer_persona_generator.run, True),
    ("markets", "Target markets", market_analyser.run, True),
    ("opportunities", "Opportunities & gaps", intelligence_report.run_opportunities, True),
    ("report", "Intelligence report", None, False),
]
STAGE_KEYS = [s[0] for s in STAGES]


def initial_stages(selected: list[str] | None) -> list[dict]:
    keys = selected or STAGE_KEYS
    return [{"key": k, "label": label, "status": "pending" if k in keys else "skipped", "error": None, "result": None}
            for k, label, _, _ in STAGES]


def needs_ai(stages: list[dict]) -> bool:
    ai = {k for k, _, _, a in STAGES if a}
    return any(s["key"] in ai and s["status"] in ("pending", "failed") for s in stages)


def _set(job: AnalysisJob, key: str, **kw) -> None:
    stages = [dict(s) for s in job.stages]
    for s in stages:
        if s["key"] == key:
            s.update(kw)
    job.stages = stages  # reassign so the JSON column is flagged dirty


def run_analysis(job_id: str) -> None:
    db = SessionLocal()
    try:
        _run(db, job_id)
    finally:
        db.close()


def _run(db, job_id: str) -> None:
    job = db.get(AnalysisJob, job_id)
    if job is None or job.status not in ("queued", "running"):
        return
    client = db.get(Client, job.client_id)
    if client is None or client.tenant_id != job.tenant_id:
        job.status, job.error = "failed", "Client not found"
        db.commit()
        return
    job.status, job.started_at, job.error, job.completed_at = "running", now(), None, None
    if needs_ai(job.stages):
        try:
            p = get_provider("analysis")
            job.provider, job.model = p.name, p.model
        except ProviderNotConfigured as e:
            job.status, job.error, job.completed_at = "failed", str(e), now()
            db.commit()
            return
    db.commit()

    pq = select(Product).where(Product.tenant_id == job.tenant_id, Product.client_id == client.id)
    if job.params.get("product_ids"):
        pq = pq.where(Product.id.in_(job.params["product_ids"]))
    ctx = Context(db=db, job=job, client=client, products=list(db.scalars(pq)))

    todo = [s for s in STAGES if next(x for x in job.stages if x["key"] == s[0])["status"] in ("pending", "failed")]
    failed = []
    for i, (key, label, runner, _) in enumerate(todo):
        db.refresh(job)
        if job.status == "cancelled":
            return
        _set(job, key, status="running", error=None)
        db.commit()
        try:
            if key == "report":
                rep = intelligence_report.compile_report(db, job.tenant_id, client)
                result = {"status_counts": rep["status_counts"]}
                job.summary = rep["status_counts"] | {"sources": rep["sources"]}
            else:
                ctx.sources = build_sources(ctx)
                result = runner(ctx)
            _set(job, key, status="completed", result=result)
            db.commit()
        except (StageError, ProviderNotConfigured, RuntimeError, ValueError) as e:
            db.rollback()
            job = db.get(AnalysisJob, job_id)
            ctx.job = job
            _set(job, key, status="failed", error=str(e)[:800])
            failed.append(label)
            db.commit()
        except Exception as e:  # unexpected bug: keep the trace in logs, a short message for the user
            log.error("analysis stage %s crashed: %s", key, traceback.format_exc())
            db.rollback()
            job = db.get(AnalysisJob, job_id)
            ctx.job = job
            _set(job, key, status="failed", error=f"Internal error: {type(e).__name__}")
            failed.append(label)
            db.commit()
        job.progress = int(100 * (i + 1) / len(todo))
        db.commit()

    job.completed_at = now()
    job.progress = 100
    if failed:
        job.status, job.error = "failed", f"Failed stages: {', '.join(failed)}. You can retry them."
    else:
        job.status = "completed"
    db.add(ActivityLog(tenant_id=job.tenant_id, user_id=job.created_by, action=f"analysis.{job.status}",
                       entity_type="client", entity_id=client.id,
                       summary=f"Client intelligence analysis {job.status} for {client.company_name}",
                       meta={"analysis_job_id": job.id}))
    db.commit()
