"""Pydantic request/response schemas. Validation here mirrors the frontend zod-like validators."""
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, field_validator

Role = Literal["owner", "admin", "manager", "staff"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- auth ----------
class RegisterIn(BaseModel):
    agency_name: str = Field(min_length=2, max_length=200)
    full_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def strong(cls, v: str) -> str:
        if not any(c.isdigit() for c in v) or not any(c.isalpha() for c in v):
            raise ValueError("Password must contain letters and numbers")
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(ORM):
    id: str
    email: EmailStr
    full_name: str
    role: Role
    is_active: bool
    created_at: datetime


class TenantOut(ORM):
    id: str
    name: str
    slug: str
    website: str | None = None
    phone: str | None = None
    address: str | None = None


class TenantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    website: str | None = Field(default=None, max_length=300)
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=1000)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
    tenant: TenantOut


class UserCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: Role = "staff"


class UserRoleUpdate(BaseModel):
    role: Role


# ---------- clients ----------
class ClientBase(BaseModel):
    company_name: str = Field(min_length=2, max_length=200)
    website: HttpUrl | None = None
    industry: str | None = Field(default=None, max_length=120)
    business_type: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=5000)
    address: str | None = Field(default=None, max_length=1000)
    contact_name: str | None = Field(default=None, max_length=200)
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, max_length=40, pattern=r"^[0-9+()\-\s]{6,40}$")
    target_markets: list[str] = Field(default_factory=list, max_length=50)
    marketing_budget: Decimal | None = Field(default=None, ge=0, le=10**12)
    budget_currency: str = Field(default="INR", min_length=3, max_length=3)
    business_objectives: str | None = Field(default=None, max_length=5000)
    assigned_user_id: str | None = None

    @field_validator("website", mode="before")
    @classmethod
    def blank_url(cls, v):
        if v in ("", None):
            return None
        if isinstance(v, str) and not v.startswith(("http://", "https://")):
            v = "https://" + v
        return v

    @field_validator("contact_email", "contact_phone", mode="before")
    @classmethod
    def blank_none(cls, v):
        return None if v == "" else v


class ClientCreate(ClientBase):
    pass


class ClientUpdate(ClientBase):
    company_name: str | None = Field(default=None, min_length=2, max_length=200)  # type: ignore[assignment]
    target_markets: list[str] | None = None  # type: ignore[assignment]
    budget_currency: str | None = Field(default=None, min_length=3, max_length=3)  # type: ignore[assignment]


class ClientOut(ORM):
    id: str
    company_name: str
    website: str | None
    industry: str | None
    business_type: str | None
    description: str | None
    address: str | None
    contact_name: str | None
    contact_email: str | None
    contact_phone: str | None
    target_markets: list[str]
    marketing_budget: Decimal | None
    budget_currency: str
    business_objectives: str | None
    assigned_user_id: str | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
    product_count: int = 0
    document_count: int = 0


# ---------- products ----------
class ProductBase(BaseModel):
    kind: Literal["product", "service"] = "product"
    name: str = Field(min_length=2, max_length=200)
    category: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=5000)
    specifications: str | None = Field(default=None, max_length=10000)
    applications: str | None = Field(default=None, max_length=5000)
    pricing: str | None = Field(default=None, max_length=200)
    min_order_quantity: str | None = Field(default=None, max_length=120)
    production_capacity: str | None = Field(default=None, max_length=200)
    target_industries: list[str] = Field(default_factory=list, max_length=50)


class ProductCreate(ProductBase):
    client_id: str


class ProductUpdate(ProductBase):
    kind: Literal["product", "service"] | None = None  # type: ignore[assignment]
    name: str | None = Field(default=None, min_length=2, max_length=200)  # type: ignore[assignment]
    target_industries: list[str] | None = None  # type: ignore[assignment]


class ProductOut(ORM):
    id: str
    client_id: str
    kind: str
    name: str
    category: str | None
    description: str | None
    specifications: str | None
    applications: str | None
    pricing: str | None
    min_order_quantity: str | None
    production_capacity: str | None
    target_industries: list[str]
    created_at: datetime
    updated_at: datetime


# ---------- documents ----------
class DocumentOut(ORM):
    id: str
    client_id: str
    product_id: str | None
    original_name: str
    content_type: str
    file_ext: str
    size_bytes: int
    extraction_status: str
    created_at: datetime


# ---------- jobs ----------
JobStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


class JobCreate(BaseModel):
    job_type: str = Field(min_length=2, max_length=60)
    client_id: str | None = None
    agent_key: str | None = Field(default=None, max_length=60)
    params: dict = Field(default_factory=dict)


class JobOut(ORM):
    id: str
    client_id: str | None
    job_type: str
    agent_key: str | None
    status: JobStatus
    progress: int
    started_at: datetime | None
    completed_at: datetime | None
    error: str | None
    result: dict | None
    params: dict
    created_at: datetime


class ActivityOut(ORM):
    id: str
    user_id: str | None
    action: str
    entity_type: str
    entity_id: str | None
    summary: str
    meta: dict
    created_at: datetime


class Page[T](BaseModel):
    items: list[T]
    total: int
