"""Phase 2 — Client Intelligence Engine data model.

Every finding table shares FindingMixin: a verification status, a confidence, its origin, the analysis
job that produced it and the human review trail. Evidence lives in EvidenceSource rows that point at a
finding by (finding_type, finding_id), so a finding can cite several sources.

Verification statuses:
  verified      a human approved it, and it is a fact (not an inference)
  ai_hypothesis produced or inferred by AI and not confirmed by a human
  needs_review  backed by quoted evidence from a source, waiting for a human
  rejected      a human rejected it (kept for audit, hidden by default)
`is_inferred` findings (buyer personas, target markets, purchase intent, budget…) can never become
`verified`; a human approval keeps them `ai_hypothesis` with `approved=True`.
"""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.entities import TimestampMixin, _now, _uuid

VERIFICATION_STATUSES = ("verified", "ai_hypothesis", "needs_review", "rejected")
ORIGINS = ("ai", "user", "client_record")


class FindingMixin(TimestampMixin):
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True, nullable=False)
    verification_status: Mapped[str] = mapped_column(String(20), default="ai_hypothesis", nullable=False, index=True)
    confidence: Mapped[float | None] = mapped_column(Float)  # 0..1, model-reported; never a verification
    is_inferred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    origin: Mapped[str] = mapped_column(String(20), default="ai", nullable=False)
    analysis_job_id: Mapped[str | None] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="SET NULL"), index=True)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)
    edited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class AnalysisJob(TimestampMixin, Base):
    __tablename__ = "analysis_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False, index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stages: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # [{key,status,error,count}]
    attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(80))
    params: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[dict | None] = mapped_column(JSON)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class DocumentExtraction(TimestampMixin, Base):
    """Text pulled out of an uploaded Document (one row per document, replaced on re-extraction)."""
    __tablename__ = "document_extractions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), unique=True, nullable=False)
    extractor: Mapped[str] = mapped_column(String(40), nullable=False)
    text: Mapped[str | None] = mapped_column(Text)
    pages: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)


class WebsiteSnapshot(TimestampMixin, Base):
    """Readable text of a client web page fetched during analysis."""
    __tablename__ = "website_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True, nullable=False)
    analysis_job_id: Mapped[str | None] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="SET NULL"))
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    title: Mapped[str | None] = mapped_column(String(300))
    text: Mapped[str | None] = mapped_column(Text)
    status_code: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)


class BusinessProfile(FindingMixin, Base):
    __tablename__ = "business_profiles"
    summary: Mapped[str | None] = mapped_column(Text)
    # Only values found in sources: {"founded": "...", "headquarters": "...", ...}
    facts: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    value_proposition: Mapped[str | None] = mapped_column(Text)


class ProductApplication(FindingMixin, Base):
    __tablename__ = "product_applications"
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True, nullable=False)
    application: Mapped[str] = mapped_column(String(300), nullable=False)
    application_type: Mapped[str] = mapped_column(String(10), default="direct", nullable=False)  # direct|indirect
    industry: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    businesses_needing: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    buyer_categories: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    pain_points: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    purchase_reasons: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    substitutes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)


class TargetMarket(FindingMixin, Base):
    __tablename__ = "target_markets"
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)  # india|state|district_city|country|export_market
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    parent: Mapped[str | None] = mapped_column(String(200))
    rationale: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str | None] = mapped_column(String(10))  # high|medium|low (AI suggestion)


class BuyerPersona(FindingMixin, Base):
    __tablename__ = "buyer_personas"
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    buyer_category: Mapped[str | None] = mapped_column(String(200))
    industry: Mapped[str | None] = mapped_column(String(200))
    company_size: Mapped[str | None] = mapped_column(String(100))
    job_titles: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    departments: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    pain_points: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    purchase_reasons: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # Phase 4 buyer-profile fields (extends the Phase 2 persona instead of a second model)
    buyer_type: Mapped[str | None] = mapped_column(String(20))  # end_user|distributor|importer|dealer|oem|institutional|project
    industry_relation: Mapped[str | None] = mapped_column(String(10))  # direct|indirect
    application_categories: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    company_types: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    problems_solved: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    substitutes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    geography: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)


class BusinessInsight(FindingMixin, Base):
    """Product intelligence fields and business-level insights.

    category: product_fact (field=specifications|materials|pricing|moq|capacity|certifications|…),
              advantage | differentiation | industry_usage | opportunity | risk | gap
    """
    __tablename__ = "business_insights"
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    field: Mapped[str | None] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)


class EvidenceSource(Base):
    __tablename__ = "evidence_sources"
    __table_args__ = (Index("ix_evidence_finding", "finding_type", "finding_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True, nullable=False)
    finding_type: Mapped[str] = mapped_column(String(30), nullable=False)
    finding_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)  # document|website|client_record|product_record|ai_inference|user
    source_ref: Mapped[str | None] = mapped_column(String(80))  # internal source key (e.g. doc:<id>)
    source_url: Mapped[str | None] = mapped_column(String(500))
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    excerpt: Mapped[str | None] = mapped_column(Text)
    quote_matched: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Phase 4 (LeadEvidence): which field the evidence supports, which provider observed it and when.
    field: Mapped[str | None] = mapped_column(String(40))
    provider: Mapped[str | None] = mapped_column(String(40))
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


FINDING_MODELS = {
    "profile": BusinessProfile,
    "application": ProductApplication,
    "market": TargetMarket,
    "persona": BuyerPersona,
    "insight": BusinessInsight,
}
