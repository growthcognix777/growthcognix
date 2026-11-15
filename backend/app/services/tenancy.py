"""Helpers that make tenant scoping the default for every tenant-owned query."""
from fastapi import HTTPException
from sqlalchemy import Select, select

from app.deps import Ctx


def scoped(ctx: Ctx, model) -> Select:
    return select(model).where(model.tenant_id == ctx.tenant_id)


def get_owned(ctx: Ctx, model, obj_id: str, label: str):
    obj = ctx.db.scalar(scoped(ctx, model).where(model.id == obj_id))
    if obj is None:
        # 404 (not 403) so other tenants' ids are not disclosed
        raise HTTPException(404, f"{label} not found")
    return obj
