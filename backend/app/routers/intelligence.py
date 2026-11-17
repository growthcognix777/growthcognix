"""Phase 2 — Client Intelligence API. Every route is tenant-scoped through the verified token."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.deps import ROLE_RANK, Ctx, get_ctx
from app.models import FINDING_MODELS, AnalysisJob, Client, EvidenceSource, Product
from app.services.activity import log
from app.services.ai.providers import ProviderNotConfigured, get_provider, provider_status
from app.services.intelligence.intelligence_report import compile_report, report_markdown
from app.services.intelligence.pipeline import STAGE_KEYS, initial_stages, needs_ai, run_analysis
from app.services.tenancy import get_owned, scoped

router = APIRouter(tags=["client intelligence"])
FindingType = Literal["profile", "application", "market", "persona", "insight"]
Status = Literal["verified", "ai_hypothesis", "needs_review", "rejected"]

# Type-specific fields that are returned in `data` and may be edited by a human.
FIELDS: dict[str, dict[str, type]] = {
    "profile": {"summary": str, "value_proposition": str, "facts": dict},
    "application": {"product_id": str, "application": str, "application_type": str, "industry": str,
                    "description": str, "businesses_needing": list, "buyer_categories": list,
                    "pain_points": list, "purchase_reasons": list, "substitutes": list},
    "market": {"product_id": str, "scope": str, "name": str, "parent": str, "rationale": str, "priority": str},
    "persona": {"product_id": str, "name": str, "buyer_category": str, "industry": str, "company_size": str,
                "job_titles": list, "departments": list, "pain_points": list, "purchase_reasons": list,
                "description": str,
                # Phase 4 buyer-profile fields
                "buyer_type": str, "industry_relation": str, "application_categories": list, "company_types": list,
                "problems_solved": list, "substitutes": list, "geography": list, "rationale": str},
    "insight": {"product_id": str, "category": str, "field": str, "title": str, "detail": str},
}
REQUIRED = {"profile": ["summary"], "application": ["product_id", "application"], "market": ["scope", "name"],
            "persona": ["name"], "insight": ["category", "title"]}
ENUMS = {"application_type": {"direct", "indirect"},
         "buyer_type": {"end_user", "distributor", "importer", "dealer", "oem", "institutional", "project"},
         "industry_relation": {"direct", "indirect"}, "scope": {"india", "state", "district_city", "country", "export_market"},
         "priority": {"high", "medium", "low", None},
         "category": {"product_fact", "advantage", "differentiation", "industry_usage", "opportunity", "risk", "gap"}}
INFERRED_TYPES = {"persona", "market"}


# ------------------------------------------------------------------ schemas
class AnalysisStart(BaseModel):
    stages: list[str] | None = Field(default=None, max_length=len(STAGE_KEYS))
    product_ids: list[str] | None = Field(default=None, max_length=200)
    re_extract: bool = False


class AnalysisOut(BaseModel):
    id: str
    client_id: str
    status: str
    progress: int
    stages: list[dict]
    attempts: int
    provider: str | None
    model: str | None
    params: dict
    error: str | None
    summary: dict | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class FindingIn(BaseModel):
    data: dict
    note: str | None = Field(default=None, max_length=2000)


class FindingPatch(BaseModel):
    data: dict


class ReviewIn(BaseModel):
    action: Literal["approve", "reject", "needs_review"]
    note: str | None = Field(default=None, max_length=2000)


# ------------------------------------------------------------------ helpers
def _analysis_out(j: AnalysisJob) -> AnalysisOut:
    return AnalysisOut.model_validate(j, from_attributes=True)


def _evidence(ctx: Ctx, ftype: str, ids: list[str]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {i: [] for i in ids}
    if not ids:
        return out
    rows = ctx.db.scalars(select(EvidenceSource).where(
        EvidenceSource.tenant_id == ctx.tenant_id, EvidenceSource.finding_type == ftype,
        EvidenceSource.finding_id.in_(ids)).order_by(EvidenceSource.created_at)).all()
    for e in rows:
        out[e.finding_id].append({"id": e.id, "source_type": e.source_type, "source_url": e.source_url,
                                  "document_id": e.document_id, "excerpt": e.excerpt, "quote_matched": e.quote_matched,
                                  "created_at": e.created_at})
    return out


def _serialize(ctx: Ctx, ftype: str, rows: list) -> list[dict]:
    ev = _evidence(ctx, ftype, [r.id for r in rows])
    return [{
        "id": r.id, "type": ftype, "client_id": r.client_id,
        "verification_status": r.verification_status, "confidence": r.confidence, "is_inferred": r.is_inferred,
        "approved": r.approved, "origin": r.origin, "edited": r.edited, "analysis_job_id": r.analysis_job_id,
        "reviewed_by": r.reviewed_by, "reviewed_at": r.reviewed_at, "review_note": r.review_note,
        "created_at": r.created_at, "updated_at": r.updated_at,
        "data": {k: getattr(r, k) for k in FIELDS[ftype]},
        "evidence": ev[r.id],
    } for r in rows]


def _clean(ctx: Ctx, client: Client, ftype: str, data: dict, partial: bool) -> dict:
    spec = FIELDS[ftype]
    unknown = set(data) - set(spec)
    if unknown:
        raise HTTPException(422, f"Unknown fields: {', '.join(sorted(unknown))}")
    out = {}
    for k, v in data.items():
        t = spec[k]
        if v in ("", None):
            if k in REQUIRED[ftype]:
                raise HTTPException(422, f"{k} is required")
            out[k] = [] if t is list else ({} if t is dict else None)
            continue
        if t is str:
            if not isinstance(v, str):
                raise HTTPException(422, f"{k} must be text")
            v = v.strip()[:4000]
        elif t is list:
            if not isinstance(v, list):
                raise HTTPException(422, f"{k} must be a list")
            v = [str(x).strip()[:200] for x in v if str(x).strip()][:30]
        elif t is dict:
            if not isinstance(v, dict) or not all(isinstance(x, str) for x in v.values()):
                raise HTTPException(422, f"{k} must be an object of text values")
            v = {str(a)[:60]: b.strip()[:500] for a, b in v.items() if b.strip()}
        if k in ENUMS and v not in ENUMS[k]:
            raise HTTPException(422, f"{k} must be one of {', '.join(sorted(x for x in ENUMS[k] if x))}")
        out[k] = v
    if not partial:
        missing = [k for k in REQUIRED[ftype] if not out.get(k)]
        if missing:
            raise HTTPException(422, f"Missing required fields: {', '.join(missing)}")
    if out.get("product_id"):
        p = get_owned(ctx, Product, out["product_id"], "Product")
        if p.client_id != client.id:
            raise HTTPException(400, "Product does not belong to this client")
    return out


def _finding(ctx: Ctx, ftype: str, fid: str):
    model = FINDING_MODELS[ftype]
    return get_owned(ctx, model, fid, "Finding")


def _enqueue(job: AnalysisJob, background: BackgroundTasks, ctx: Ctx) -> None:
    if get_settings().analysis_inline:
        background.add_task(run_analysis, job.id)
        return
    try:
        from app.worker import queue
        queue().enqueue(run_analysis, job.id, job_timeout=1800)
    except Exception as e:  # Redis down: record it instead of pretending the job runs
        job.status, job.error = "failed", f"Job queue unavailable ({type(e).__name__}). Start Redis and the worker, then retry."
        job.completed_at = datetime.now(timezone.utc)
        ctx.db.commit()


def _require_ai(stages: list[dict]) -> None:
    if needs_ai(stages):
        try:
            get_provider("analysis")
        except ProviderNotConfigured as e:
            raise HTTPException(409, str(e))


# ------------------------------------------------------------------ routes
@router.get("/api/v1/intelligence/providers")
def providers(ctx: Ctx = Depends(get_ctx)):
    return {"providers": provider_status(), "stages": STAGE_KEYS}


@router.post("/api/v1/clients/{client_id}/intelligence/analyses", response_model=AnalysisOut, status_code=201)
def start_analysis(client_id: str, body: AnalysisStart, background: BackgroundTasks, ctx: Ctx = Depends(get_ctx)):
    client = get_owned(ctx, Client, client_id, "Client")
    if client.archived_at:
        raise HTTPException(400, "Client is archived")
    if body.stages:
        bad = set(body.stages) - set(STAGE_KEYS)
        if bad:
            raise HTTPException(422, f"Unknown stages: {', '.join(sorted(bad))}")
    if body.product_ids:
        for pid in body.product_ids:
            if get_owned(ctx, Product, pid, "Product").client_id != client.id:
                raise HTTPException(400, "Product does not belong to this client")
    running = ctx.db.scalar(scoped(ctx, AnalysisJob).where(AnalysisJob.client_id == client.id,
                                                           AnalysisJob.status.in_(("queued", "running"))))
    if running:
        raise HTTPException(409, "An analysis is already running for this client")
    stages = initial_stages(body.stages)
    _require_ai(stages)
    job = AnalysisJob(tenant_id=ctx.tenant_id, client_id=client.id, stages=stages, created_by=ctx.user.id,
                      params=body.model_dump(exclude_none=True))
    ctx.db.add(job)
    ctx.db.flush()
    log(ctx, "analysis.started", "client", client.id, f"Client intelligence analysis started for {client.company_name}",
        analysis_job_id=job.id)
    ctx.db.commit()
    _enqueue(job, background, ctx)
    return _analysis_out(job)


@router.get("/api/v1/clients/{client_id}/intelligence/analyses", response_model=list[AnalysisOut])
def list_analyses(client_id: str, ctx: Ctx = Depends(get_ctx), limit: int = Query(default=20, ge=1, le=100)):
    get_owned(ctx, Client, client_id, "Client")
    rows = ctx.db.scalars(scoped(ctx, AnalysisJob).where(AnalysisJob.client_id == client_id)
                          .order_by(AnalysisJob.created_at.desc()).limit(limit)).all()
    return [_analysis_out(j) for j in rows]


@router.get("/api/v1/intelligence/analyses/{job_id}", response_model=AnalysisOut)
def get_analysis(job_id: str, ctx: Ctx = Depends(get_ctx)):
    return _analysis_out(get_owned(ctx, AnalysisJob, job_id, "Analysis"))


@router.post("/api/v1/intelligence/analyses/{job_id}/retry", response_model=AnalysisOut)
def retry_analysis(job_id: str, background: BackgroundTasks, ctx: Ctx = Depends(get_ctx)):
    job = get_owned(ctx, AnalysisJob, job_id, "Analysis")
    if job.status not in ("failed", "cancelled"):
        raise HTTPException(400, f"Only failed or cancelled analyses can be retried (this one is {job.status})")
    stages = [dict(s, status="pending", error=None) if s["status"] in ("failed", "running", "pending") else s
              for s in job.stages]
    _require_ai(stages)
    job.stages, job.status, job.progress, job.error = stages, "queued", 0, None
    job.attempts += 1
    job.completed_at = None
    log(ctx, "analysis.retried", "client", job.client_id, f"Client intelligence analysis retried (attempt {job.attempts})",
        analysis_job_id=job.id)
    ctx.db.commit()
    _enqueue(job, background, ctx)
    return _analysis_out(job)


@router.post("/api/v1/intelligence/analyses/{job_id}/cancel", response_model=AnalysisOut)
def cancel_analysis(job_id: str, ctx: Ctx = Depends(get_ctx)):
    job = get_owned(ctx, AnalysisJob, job_id, "Analysis")
    if job.status not in ("queued", "running"):
        raise HTTPException(400, f"Analysis is already {job.status}")
    job.status, job.completed_at = "cancelled", datetime.now(timezone.utc)
    log(ctx, "analysis.cancelled", "client", job.client_id, "Client intelligence analysis cancelled", analysis_job_id=job.id)
    ctx.db.commit()
    return _analysis_out(job)


@router.get("/api/v1/clients/{client_id}/intelligence")
def client_intelligence(client_id: str, ctx: Ctx = Depends(get_ctx)):
    client = get_owned(ctx, Client, client_id, "Client")
    rep = compile_report(ctx.db, ctx.tenant_id, client)
    last = ctx.db.scalar(scoped(ctx, AnalysisJob).where(AnalysisJob.client_id == client.id)
                         .order_by(AnalysisJob.created_at.desc()).limit(1))
    rep["last_analysis"] = _analysis_out(last).model_dump() if last else None
    return rep


@router.get("/api/v1/clients/{client_id}/intelligence/report.md", response_class=PlainTextResponse)
def client_report_md(client_id: str, ctx: Ctx = Depends(get_ctx)):
    client = get_owned(ctx, Client, client_id, "Client")
    return report_markdown(compile_report(ctx.db, ctx.tenant_id, client))


@router.get("/api/v1/clients/{client_id}/intelligence/findings/{ftype}")
def list_findings(client_id: str, ftype: FindingType, ctx: Ctx = Depends(get_ctx), product_id: str | None = None,
                  status: Status | None = None, include_rejected: bool = False, category: str | None = None):
    get_owned(ctx, Client, client_id, "Client")
    model = FINDING_MODELS[ftype]
    stmt = scoped(ctx, model).where(model.client_id == client_id)
    if product_id and hasattr(model, "product_id"):
        stmt = stmt.where(model.product_id == product_id)
    if category and ftype == "insight":
        stmt = stmt.where(model.category == category)
    if status:
        stmt = stmt.where(model.verification_status == status)
    elif not include_rejected:
        stmt = stmt.where(model.verification_status != "rejected")
    rows = ctx.db.scalars(stmt.order_by(model.created_at)).all()
    return {"items": _serialize(ctx, ftype, rows), "total": len(rows)}


# Convenience routes named in the spec
@router.get("/api/v1/clients/{client_id}/intelligence/products")
def product_intelligence(client_id: str, ctx: Ctx = Depends(get_ctx), product_id: str | None = None):
    client = get_owned(ctx, Client, client_id, "Client")
    products = ctx.db.scalars(scoped(ctx, Product).where(Product.client_id == client.id)).all()
    if product_id:
        products = [p for p in products if p.id == product_id]
        if not products:
            raise HTTPException(404, "Product not found")
    insights = list_findings(client_id, "insight", ctx, category="product_fact")["items"]
    apps = list_findings(client_id, "application", ctx)["items"]
    return {"items": [{"product": {"id": p.id, "name": p.name, "category": p.category},
                       "facts": [i for i in insights if i["data"]["product_id"] == p.id],
                       "applications": [a for a in apps if a["data"]["product_id"] == p.id]} for p in products]}


@router.get("/api/v1/clients/{client_id}/intelligence/personas")
def personas(client_id: str, ctx: Ctx = Depends(get_ctx)):
    return list_findings(client_id, "persona", ctx)


@router.get("/api/v1/clients/{client_id}/intelligence/markets")
def markets(client_id: str, ctx: Ctx = Depends(get_ctx)):
    return list_findings(client_id, "market", ctx)


@router.post("/api/v1/clients/{client_id}/intelligence/findings/{ftype}", status_code=201)
def create_finding(client_id: str, ftype: FindingType, body: FindingIn, ctx: Ctx = Depends(get_ctx)):
    """A human-entered finding. It starts as `needs_review` (or `ai_hypothesis` for inferred kinds is NOT used:
    human entries of personas/markets are still judgement calls, so they stay `is_inferred`)."""
    client = get_owned(ctx, Client, client_id, "Client")
    data = _clean(ctx, client, ftype, body.data, partial=False)
    inferred = ftype in INFERRED_TYPES or data.get("category") in ("opportunity", "risk", "gap", "differentiation") \
        or data.get("application_type") == "indirect"
    row = FINDING_MODELS[ftype](tenant_id=ctx.tenant_id, client_id=client.id, origin="user", is_inferred=inferred,
                                verification_status="needs_review", **data)
    ctx.db.add(row)
    ctx.db.flush()
    ctx.db.add(EvidenceSource(tenant_id=ctx.tenant_id, client_id=client.id, finding_type=ftype, finding_id=row.id,
                              source_type="user", excerpt=(body.note or "Entered by a team member")[:600]))
    log(ctx, "finding.created", ftype, row.id, f"{ftype.title()} finding added for {client.company_name}",
        client_id=client.id)
    ctx.db.commit()
    return _serialize(ctx, ftype, [row])[0]


@router.patch("/api/v1/intelligence/findings/{ftype}/{finding_id}")
def edit_finding(ftype: FindingType, finding_id: str, body: FindingPatch, ctx: Ctx = Depends(get_ctx)):
    row = _finding(ctx, ftype, finding_id)
    client = ctx.db.get(Client, row.client_id)
    data = _clean(ctx, client, ftype, body.data, partial=True)
    for k, v in data.items():
        setattr(row, k, v)
    row.edited = True
    # An edit invalidates the previous approval: it must be reviewed again.
    row.approved = False
    if row.verification_status in ("verified", "rejected"):
        row.verification_status = "ai_hypothesis" if row.is_inferred else "needs_review"
    log(ctx, "finding.edited", ftype, row.id, f"{ftype.title()} finding edited", fields=sorted(data))
    ctx.db.commit()
    return _serialize(ctx, ftype, [row])[0]


@router.post("/api/v1/intelligence/findings/{ftype}/{finding_id}/review")
def review_finding(ftype: FindingType, finding_id: str, body: ReviewIn, ctx: Ctx = Depends(get_ctx)):
    if ROLE_RANK[ctx.user.role] < ROLE_RANK["manager"]:
        raise HTTPException(403, "Requires manager role or higher")
    row = _finding(ctx, ftype, finding_id)
    if body.action == "approve":
        row.approved = True
        # Inferences are approved as working hypotheses; they are never displayed as verified facts.
        row.verification_status = "ai_hypothesis" if row.is_inferred else "verified"
    elif body.action == "reject":
        row.approved, row.verification_status = False, "rejected"
    else:
        row.approved = False
        row.verification_status = "needs_review"
    row.reviewed_by, row.reviewed_at, row.review_note = ctx.user.id, datetime.now(timezone.utc), body.note
    log(ctx, f"finding.{body.action}", ftype, row.id, f"{ftype.title()} finding {body.action.replace('_', ' ')}d"
        if body.action != "needs_review" else f"{ftype.title()} finding sent back for review")
    ctx.db.commit()
    return _serialize(ctx, ftype, [row])[0]


@router.delete("/api/v1/intelligence/findings/{ftype}/{finding_id}", status_code=204)
def delete_finding(ftype: FindingType, finding_id: str, ctx: Ctx = Depends(get_ctx)):
    if ROLE_RANK[ctx.user.role] < ROLE_RANK["admin"]:
        raise HTTPException(403, "Requires admin role or higher (reject keeps an audit trail instead)")
    row = _finding(ctx, ftype, finding_id)
    ctx.db.execute(delete(EvidenceSource).where(EvidenceSource.finding_type == ftype,
                                                EvidenceSource.finding_id == row.id))
    ctx.db.delete(row)
    log(ctx, "finding.deleted", ftype, finding_id, f"{ftype.title()} finding deleted")
    ctx.db.commit()
