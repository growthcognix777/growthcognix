from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select

from app.deps import Ctx, get_ctx, require_role
from app.models import Client, Document, Product, User
from app.schemas import ClientCreate, ClientOut, ClientUpdate, Page
from app.services.activity import log
from app.services.tenancy import get_owned, scoped

router = APIRouter(prefix="/api/v1/clients", tags=["clients"])


def _check_assignee(ctx: Ctx, user_id: str | None):
    if user_id:
        get_owned(ctx, User, user_id, "Assigned staff member")


def _out(ctx: Ctx, c: Client) -> ClientOut:
    o = ClientOut.model_validate(c)
    o.product_count = ctx.db.scalar(select(func.count()).select_from(Product).where(
        Product.tenant_id == ctx.tenant_id, Product.client_id == c.id)) or 0
    o.document_count = ctx.db.scalar(select(func.count()).select_from(Document).where(
        Document.tenant_id == ctx.tenant_id, Document.client_id == c.id)) or 0
    return o


@router.get("", response_model=Page[ClientOut])
def list_clients(
    ctx: Ctx = Depends(get_ctx),
    q: str | None = Query(default=None, max_length=100),
    archived: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    stmt = scoped(ctx, Client)
    stmt = stmt.where(Client.archived_at.is_not(None) if archived else Client.archived_at.is_(None))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Client.company_name.ilike(like), Client.industry.ilike(like), Client.website.ilike(like)))
    total = ctx.db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = ctx.db.scalars(stmt.order_by(Client.created_at.desc()).limit(limit).offset(offset)).all()
    return Page[ClientOut](items=[_out(ctx, c) for c in rows], total=total or 0)


@router.post("", response_model=ClientOut, status_code=201)
def create_client(body: ClientCreate, ctx: Ctx = Depends(get_ctx)):
    _check_assignee(ctx, body.assigned_user_id)
    data = body.model_dump(mode="json")
    data["marketing_budget"] = body.marketing_budget
    c = Client(tenant_id=ctx.tenant_id, **data)
    ctx.db.add(c)
    ctx.db.flush()
    log(ctx, "client.created", "client", c.id, f"Client {c.company_name} created")
    ctx.db.commit()
    return _out(ctx, c)


@router.get("/{client_id}", response_model=ClientOut)
def get_client(client_id: str, ctx: Ctx = Depends(get_ctx)):
    return _out(ctx, get_owned(ctx, Client, client_id, "Client"))


@router.patch("/{client_id}", response_model=ClientOut)
def update_client(client_id: str, body: ClientUpdate, ctx: Ctx = Depends(get_ctx)):
    c = get_owned(ctx, Client, client_id, "Client")
    changes = body.model_dump(exclude_unset=True, mode="json")
    if "marketing_budget" in changes:
        changes["marketing_budget"] = body.marketing_budget
    if "assigned_user_id" in changes:
        _check_assignee(ctx, changes["assigned_user_id"])
    for k, v in changes.items():
        setattr(c, k, v)
    log(ctx, "client.updated", "client", c.id, f"Client {c.company_name} updated", fields=sorted(changes))
    ctx.db.commit()
    return _out(ctx, c)


@router.post("/{client_id}/archive", response_model=ClientOut)
def archive_client(client_id: str, ctx: Ctx = Depends(require_role("manager"))):
    c = get_owned(ctx, Client, client_id, "Client")
    if c.archived_at:
        raise HTTPException(400, "Client is already archived")
    c.archived_at = datetime.now(timezone.utc)
    log(ctx, "client.archived", "client", c.id, f"Client {c.company_name} archived")
    ctx.db.commit()
    return _out(ctx, c)


@router.post("/{client_id}/restore", response_model=ClientOut)
def restore_client(client_id: str, ctx: Ctx = Depends(require_role("manager"))):
    c = get_owned(ctx, Client, client_id, "Client")
    c.archived_at = None
    log(ctx, "client.restored", "client", c.id, f"Client {c.company_name} restored")
    ctx.db.commit()
    return _out(ctx, c)


@router.delete("/{client_id}", status_code=204)
def delete_client(client_id: str, ctx: Ctx = Depends(require_role("admin"))):
    """Permanent delete. Only archived clients can be deleted, so nothing is lost by accident."""
    c = get_owned(ctx, Client, client_id, "Client")
    if not c.archived_at:
        raise HTTPException(400, "Archive the client before deleting it permanently")
    log(ctx, "client.deleted", "client", c.id, f"Client {c.company_name} permanently deleted")
    ctx.db.delete(c)
    ctx.db.commit()
