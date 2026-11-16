from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select

from app.deps import Ctx, get_ctx
from app.models import AnalysisJob, Client, ResearchJob
from app.services.ai.providers import ProviderNotConfigured, get_provider
from app.schemas import JobCreate, JobOut, Page
from app.services.activity import log
from app.services.agents import AGENTS
from app.services.tenancy import get_owned, scoped

router = APIRouter(prefix="/api/v1/jobs", tags=["research jobs"])
agents_router = APIRouter(prefix="/api/v1/agents", tags=["agents"])

# Job types with a real executor. Empty in Phase 1: jobs can be queued and tracked but no worker runs them yet.
EXECUTABLE_JOB_TYPES: set[str] = set()


@router.get("", response_model=Page[JobOut])
def list_jobs(ctx: Ctx = Depends(get_ctx), client_id: str | None = None, status: str | None = None,
              agent_key: str | None = None, limit: int = Query(default=50, ge=1, le=200)):
    stmt = scoped(ctx, ResearchJob)
    if client_id:
        stmt = stmt.where(ResearchJob.client_id == client_id)
    if status:
        stmt = stmt.where(ResearchJob.status == status)
    if agent_key:
        stmt = stmt.where(ResearchJob.agent_key == agent_key)
    total = ctx.db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = ctx.db.scalars(stmt.order_by(ResearchJob.created_at.desc()).limit(limit)).all()
    return Page[JobOut](items=rows, total=total or 0)


@router.post("", response_model=JobOut, status_code=201)
def create_job(body: JobCreate, ctx: Ctx = Depends(get_ctx)):
    if body.client_id:
        get_owned(ctx, Client, body.client_id, "Client")
    if body.job_type not in EXECUTABLE_JOB_TYPES:
        raise HTTPException(409, f"'{body.job_type}' has no worker yet. It becomes available in a later phase.")
    job = ResearchJob(tenant_id=ctx.tenant_id, created_by=ctx.user.id, **body.model_dump())
    ctx.db.add(job)
    ctx.db.flush()
    log(ctx, "job.created", "job", job.id, f"Research job {job.job_type} queued")
    ctx.db.commit()
    return job


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str, ctx: Ctx = Depends(get_ctx)):
    return get_owned(ctx, ResearchJob, job_id, "Job")


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: str, ctx: Ctx = Depends(get_ctx)):
    job = get_owned(ctx, ResearchJob, job_id, "Job")
    if job.status in ("completed", "failed", "cancelled"):
        raise HTTPException(400, f"Job is already {job.status}")
    job.status = "cancelled"
    job.completed_at = datetime.now(timezone.utc)
    log(ctx, "job.cancelled", "job", job.id, f"Research job {job.job_type} cancelled")
    ctx.db.commit()
    return job


@agents_router.get("")
def list_agents(ctx: Ctx = Depends(get_ctx)):
    try:
        get_provider("analysis")
        ai_ready = True
    except ProviderNotConfigured:
        ai_ready = False
    out = []
    for a in AGENTS:
        if a["key"] == "business_analyst":  # Phase 2: runs as the Client Intelligence analysis
            jobs = scoped(ctx, AnalysisJob)
            order = AnalysisJob.created_at.desc()
            status = "active" if ai_ready else "needs_setup"
        else:
            jobs = scoped(ctx, ResearchJob).where(ResearchJob.agent_key == a["key"])
            order = ResearchJob.created_at.desc()
            status = "planned"
        total = ctx.db.scalar(select(func.count()).select_from(jobs.subquery())) or 0
        last = ctx.db.scalar(jobs.order_by(order).limit(1))
        out.append({**a, "status": status, "total_jobs": total,
                    "last_job_at": last.created_at if last else None})
    return out
