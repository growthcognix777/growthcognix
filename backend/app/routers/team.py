from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.core.security import hash_password
from app.deps import ROLE_RANK, Ctx, get_ctx, require_role
from app.models import Tenant, User
from app.schemas import TenantOut, TenantUpdate, UserCreate, UserOut, UserRoleUpdate
from app.services.activity import log
from app.services.tenancy import get_owned, scoped

router = APIRouter(prefix="/api/v1", tags=["agency"])


@router.get("/agency", response_model=TenantOut)
def get_agency(ctx: Ctx = Depends(get_ctx)):
    return ctx.db.get(Tenant, ctx.tenant_id)


@router.patch("/agency", response_model=TenantOut)
def update_agency(body: TenantUpdate, ctx: Ctx = Depends(require_role("admin"))):
    t = ctx.db.get(Tenant, ctx.tenant_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(t, k, v)
    log(ctx, "agency.updated", "tenant", t.id, "Agency profile updated")
    ctx.db.commit()
    return t


@router.get("/users", response_model=list[UserOut])
def list_users(ctx: Ctx = Depends(get_ctx)):
    return ctx.db.scalars(scoped(ctx, User).order_by(User.created_at)).all()


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, ctx: Ctx = Depends(require_role("admin"))):
    if body.role == "owner" and ctx.user.role != "owner":
        raise HTTPException(403, "Only the owner can add another owner")
    if ctx.db.scalar(select(User).where(User.email == body.email.lower())):
        raise HTTPException(409, "An account with this email already exists")
    u = User(tenant_id=ctx.tenant_id, email=body.email.lower(), full_name=body.full_name,
             password_hash=hash_password(body.password), role=body.role)
    ctx.db.add(u)
    ctx.db.flush()
    log(ctx, "user.created", "user", u.id, f"Team member {u.full_name} added as {u.role}")
    ctx.db.commit()
    return u


@router.patch("/users/{user_id}/role", response_model=UserOut)
def change_role(user_id: str, body: UserRoleUpdate, ctx: Ctx = Depends(require_role("admin"))):
    u = get_owned(ctx, User, user_id, "User")
    if u.id == ctx.user.id:
        raise HTTPException(400, "You cannot change your own role")
    if ROLE_RANK[body.role] >= ROLE_RANK[ctx.user.role] and ctx.user.role != "owner":
        raise HTTPException(403, "You cannot grant a role equal to or above your own")
    u.role = body.role
    log(ctx, "user.role_changed", "user", u.id, f"{u.full_name} is now {u.role}")
    ctx.db.commit()
    return u
