from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.deps import Ctx, get_ctx
from app.models import ActivityLog, Client, Document, Product, ResearchJob, User
from app.schemas import ActivityOut, Page
from app.services.tenancy import scoped

router = APIRouter(prefix="/api/v1", tags=["activity & dashboard"])


@router.get("/activity", response_model=Page[ActivityOut])
def list_activity(ctx: Ctx = Depends(get_ctx), entity_type: str | None = None, action: str | None = None,
                  limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0)):
    stmt = scoped(ctx, ActivityLog)
    if entity_type:
        stmt = stmt.where(ActivityLog.entity_type == entity_type)
    if action:
        stmt = stmt.where(ActivityLog.action == action)
    total = ctx.db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = ctx.db.scalars(stmt.order_by(ActivityLog.created_at.desc()).limit(limit).offset(offset)).all()
    return Page[ActivityOut](items=rows, total=total or 0)


@router.get("/dashboard/summary")
def summary(ctx: Ctx = Depends(get_ctx)):
    """Every number is a live count of this tenant's records. Nothing is estimated."""
    def count(model, *conds):
        return ctx.db.scalar(select(func.count()).select_from(model).where(model.tenant_id == ctx.tenant_id, *conds)) or 0

    return {
        "active_clients": count(Client, Client.archived_at.is_(None)),
        "archived_clients": count(Client, Client.archived_at.is_not(None)),
        "products": count(Product),
        "documents": count(Document),
        "team_members": count(User),
        "jobs_running": count(ResearchJob, ResearchJob.status.in_(["queued", "running"])),
    }
