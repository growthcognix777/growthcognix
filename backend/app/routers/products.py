from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select

from app.deps import Ctx, get_ctx, require_role
from app.models import Client, Product
from app.schemas import Page, ProductCreate, ProductOut, ProductUpdate
from app.services.activity import log
from app.services.tenancy import get_owned, scoped

router = APIRouter(prefix="/api/v1/products", tags=["products"])


@router.get("", response_model=Page[ProductOut])
def list_products(
    ctx: Ctx = Depends(get_ctx),
    client_id: str | None = None,
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    stmt = scoped(ctx, Product)
    if client_id:
        stmt = stmt.where(Product.client_id == client_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Product.name.ilike(like), Product.category.ilike(like)))
    total = ctx.db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = ctx.db.scalars(stmt.order_by(Product.created_at.desc()).limit(limit).offset(offset)).all()
    return Page[ProductOut](items=rows, total=total or 0)


@router.post("", response_model=ProductOut, status_code=201)
def create_product(body: ProductCreate, ctx: Ctx = Depends(get_ctx)):
    client = get_owned(ctx, Client, body.client_id, "Client")
    p = Product(tenant_id=ctx.tenant_id, **body.model_dump())
    ctx.db.add(p)
    ctx.db.flush()
    log(ctx, "product.created", "product", p.id, f"{p.kind.title()} {p.name} added to {client.company_name}",
        client_id=client.id)
    ctx.db.commit()
    return p


@router.get("/{product_id}", response_model=ProductOut)
def get_product(product_id: str, ctx: Ctx = Depends(get_ctx)):
    return get_owned(ctx, Product, product_id, "Product")


@router.patch("/{product_id}", response_model=ProductOut)
def update_product(product_id: str, body: ProductUpdate, ctx: Ctx = Depends(get_ctx)):
    p = get_owned(ctx, Product, product_id, "Product")
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(p, k, v)
    log(ctx, "product.updated", "product", p.id, f"{p.name} updated", fields=sorted(changes), client_id=p.client_id)
    ctx.db.commit()
    return p


@router.delete("/{product_id}", status_code=204)
def delete_product(product_id: str, ctx: Ctx = Depends(require_role("manager"))):
    p = get_owned(ctx, Product, product_id, "Product")
    log(ctx, "product.deleted", "product", p.id, f"{p.name} deleted", client_id=p.client_id)
    ctx.db.delete(p)
    ctx.db.commit()
