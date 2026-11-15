import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.deps import Ctx, get_ctx
from app.models import ActivityLog, Tenant, User
from app.schemas import LoginIn, RegisterIn, TenantOut, TokenOut, UserOut

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:80] or "agency"
    return f"{base}-{uuid.uuid4().hex[:6]}"


def _token_out(user: User, tenant: Tenant) -> TokenOut:
    return TokenOut(
        access_token=create_access_token(user.id, tenant.id, user.role),
        user=UserOut.model_validate(user),
        tenant=TenantOut.model_validate(tenant),
    )


@router.post("/register", response_model=TokenOut, status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists")
    tenant = Tenant(name=body.agency_name.strip(), slug=_slug(body.agency_name))
    db.add(tenant)
    db.flush()
    user = User(tenant_id=tenant.id, email=email, full_name=body.full_name.strip(),
                password_hash=hash_password(body.password), role="owner")
    db.add(user)
    db.flush()
    db.add(ActivityLog(tenant_id=tenant.id, user_id=user.id, action="agency.registered",
                       entity_type="tenant", entity_id=tenant.id, summary=f"Agency {tenant.name} registered", meta={}))
    db.commit()
    return _token_out(user, tenant)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Incorrect email or password")
    if not user.is_active:
        raise HTTPException(403, "This account has been disabled")
    tenant = db.get(Tenant, user.tenant_id)
    db.add(ActivityLog(tenant_id=tenant.id, user_id=user.id, action="user.login",
                       entity_type="user", entity_id=user.id, summary=f"{user.full_name} signed in", meta={}))
    db.commit()
    return _token_out(user, tenant)


@router.post("/logout", status_code=204)
def logout(ctx: Ctx = Depends(get_ctx)):
    # Stateless JWT: the client discards the token. Server-side revocation lands with refresh tokens (pre-VPS hardening).
    ctx.db.add(ActivityLog(tenant_id=ctx.tenant_id, user_id=ctx.user.id, action="user.logout",
                           entity_type="user", entity_id=ctx.user.id, summary=f"{ctx.user.full_name} signed out", meta={}))
    ctx.db.commit()


@router.get("/me", response_model=TokenOut)
def me(ctx: Ctx = Depends(get_ctx)):
    tenant = ctx.db.get(Tenant, ctx.tenant_id)
    return _token_out(ctx.user, tenant)
