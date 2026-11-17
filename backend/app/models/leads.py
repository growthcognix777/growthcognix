"""Phase 4: Global Buyer Discovery & Lead Intelligence data model.

Reuse, not duplication:
  * BuyerPersona (Phase 2) is extended with the buyer-profile fields this phase needs.
  * EvidenceSource (Phase 2/3) is the spec's LeadEvidence: finding_type="prospect" | "contact" | "market_insight",
    with `field`, `provider` and `observed_at`. One evidence store across phases.

What the system may and may not claim:
  * Appearing in a search result or directory makes a company `discovered`, never a verified buyer.
  * The pipeline itself can only reach `website_verified` (it fetched the site). Every other verified
    status is set by a person through the verification queue, and recorded in LeadVerification.
  * Contacts are only role addresses / phone numbers published on the company's own site, or a business
    contact a person entered with a source URL. Personal contacts are never generated.
"""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.entities import TimestampMixin, _uuid

VERIFICATION_ORDER = ["discovered", "company_verified", "website_verified", "industry_verified",
                      "product_relevance_verified", "contact_verified"]
VERIFICATION_STATUSES = VERIFICATION_ORDER + ["needs_review", "rejected"]
BUYER_TYPES = ["end_user", "distributor", "importer", "dealer", "oem", "institutional", "project"]
GEO_LEVELS = ["global", "country", "state", "district", "city", "industrial_area"]


class _Owned(TimestampMixin):
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True, nullable=False)


class GeographicArea(_Owned, Base):
    """A saved research area in the GLOBAL > COUNTRY > STATE > DISTRICT > CITY > INDUSTRIAL AREA hierarchy."""
    __tablename__ = "geographic_areas"
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str | None] = mapped_column(String(20))  # ISO country / Indian state code when known
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("geographic_areas.id", ondelete="CASCADE"), index=True)
    country_code: Mapped[str | None] = mapped_column(String(2))
    path: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # ["India", "Karnataka", "Belagavi"]
    notes: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(500))  # e.g. the cluster's public listing
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class DiscoveryCampaign(_Owned, Base):
    __tablename__ = "discovery_campaigns"
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False, index=True)
    # draft|queued|running|paused|cancelled|completed|failed
    product_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    persona_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    geography_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    buyer_types: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    sources: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # provider keys
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stage: Mapped[str | None] = mapped_column(String(40))
    counts: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class DiscoveryTarget(_Owned, Base):
    """One unit of work: persona x geography x source. Done targets are skipped on resume (idempotent)."""
    __tablename__ = "discovery_targets"
    __table_args__ = (UniqueConstraint("campaign_id", "key", name="uq_target_key"),)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("discovery_campaigns.id", ondelete="CASCADE"), index=True, nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    persona_id: Mapped[str | None] = mapped_column(ForeignKey("buyer_personas.id", ondelete="SET NULL"))
    geography_id: Mapped[str | None] = mapped_column(ForeignKey("geographic_areas.id", ondelete="SET NULL"))
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    query: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)  # pending|done|failed|skipped
    results_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    new_prospects: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProspectCompany(_Owned, Base):
    __tablename__ = "prospect_companies"
    __table_args__ = (UniqueConstraint("client_id", "domain", name="uq_prospect_domain"),
                      Index("ix_prospect_score", "client_id", "score_total"))
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(300))
    website: Mapped[str | None] = mapped_column(String(500))
    domain: Mapped[str | None] = mapped_column(String(253), index=True)  # normalised; dedupe key
    description: Mapped[str | None] = mapped_column(Text)  # as published on its own site
    industry: Mapped[str | None] = mapped_column(String(200))
    sub_industry: Mapped[str | None] = mapped_column(String(200))
    company_category: Mapped[str | None] = mapped_column(String(100))  # manufacturer, hotel, hospital, EPC ...
    buyer_type: Mapped[str | None] = mapped_column(String(20))
    country: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    district: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(100))
    industrial_area: Mapped[str | None] = mapped_column(String(200))
    searched_area: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # geography the search targeted (not verified)
    observed_locations: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # places named on its site
    qualification_reason: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(String(30), default="discovered", nullable=False, index=True)
    verified_fields: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # {field: {by, at, note}}
    signals: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # observed matches from its own site
    providers: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    origin: Mapped[str] = mapped_column(String(20), default="discovery", nullable=False)  # discovery|manual|import
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    site_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    site_status: Mapped[str | None] = mapped_column(String(60))
    score_total: Mapped[int | None] = mapped_column(Integer)
    score_class: Mapped[str | None] = mapped_column(String(10))
    confidence: Mapped[float | None] = mapped_column(Float)
    crm_status: Mapped[str] = mapped_column(String(20), default="none", nullable=False)  # none|approved|handed_off
    crm_handoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_to: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    first_campaign_id: Mapped[str | None] = mapped_column(ForeignKey("discovery_campaigns.id", ondelete="SET NULL"))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ProspectProductFit(_Owned, Base):
    __tablename__ = "prospect_product_fits"
    prospect_id: Mapped[str] = mapped_column(ForeignKey("prospect_companies.id", ondelete="CASCADE"), index=True, nullable=False)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    persona_id: Mapped[str | None] = mapped_column(ForeignKey("buyer_personas.id", ondelete="SET NULL"))
    application: Mapped[str | None] = mapped_column(String(300))
    relation: Mapped[str] = mapped_column(String(10), default="direct", nullable=False)  # direct|indirect
    reason: Mapped[str | None] = mapped_column(Text)
    matched_terms: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    origin: Mapped[str] = mapped_column(String(20), default="observed", nullable=False)  # observed|user
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class BusinessContact(_Owned, Base):
    """Published business contact. kind: role_email | phone | person (person only when a user entered it with a source)."""
    __tablename__ = "business_contacts"
    prospect_id: Mapped[str] = mapped_column(ForeignKey("prospect_companies.id", ondelete="CASCADE"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    value: Mapped[str | None] = mapped_column(String(300))  # email or phone
    person_name: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[str | None] = mapped_column(String(200))
    source_url: Mapped[str | None] = mapped_column(String(500))
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    origin: Mapped[str] = mapped_column(String(20), default="observed", nullable=False)  # observed|user
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    purpose: Mapped[str | None] = mapped_column(String(200))  # stated purpose for holding it (DPDP)


class LeadScore(_Owned, Base):
    """Score history; ProspectCompany.score_* holds the latest."""
    __tablename__ = "lead_scores"
    prospect_id: Mapped[str] = mapped_column(ForeignKey("prospect_companies.id", ondelete="CASCADE"), index=True, nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    score_class: Mapped[str] = mapped_column(String(10), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    components: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    weights: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    explanation: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    version: Mapped[str] = mapped_column(String(20), default="v1", nullable=False)


class LeadVerification(_Owned, Base):
    __tablename__ = "lead_verifications"
    prospect_id: Mapped[str] = mapped_column(ForeignKey("prospect_companies.id", ondelete="CASCADE"), index=True, nullable=False)
    field: Mapped[str] = mapped_column(String(40), nullable=False)  # company|website|industry|product_relevance|contact|status
    decision: Mapped[str] = mapped_column(String(20), nullable=False)  # verified|rejected|needs_review|system_observed
    note: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(500))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class LeadAssignment(_Owned, Base):
    __tablename__ = "lead_assignments"
    prospect_id: Mapped[str] = mapped_column(ForeignKey("prospect_companies.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    assigned_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)  # active|released
    note: Mapped[str | None] = mapped_column(Text)


class TradeMarketInsight(_Owned, Base):
    """kind separates historical trade statistics from current demand signals and obtainable revenue
    (which is never computed automatically)."""
    __tablename__ = "trade_market_insights"
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    # historical_trade|current_demand|tariff|certification|regulation|logistics|trade_agreement|hs_code
    hs_code: Mapped[str | None] = mapped_column(String(12))
    reporter: Mapped[str | None] = mapped_column(String(100))  # country reporting the flow
    partner: Mapped[str | None] = mapped_column(String(100))
    flow: Mapped[str | None] = mapped_column(String(10))  # import|export
    period: Mapped[str | None] = mapped_column(String(10))
    value_usd: Mapped[float | None] = mapped_column(Float)
    quantity: Mapped[float | None] = mapped_column(Float)
    quantity_unit: Mapped[str | None] = mapped_column(String(30))
    title: Mapped[str | None] = mapped_column(String(300))
    detail: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(60), nullable=False)  # un_comtrade|user|...
    source_url: Mapped[str | None] = mapped_column(String(500))
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class SuppressionEntry(TimestampMixin, Base):
    """Tenant-wide do-not-contact / do-not-collect list (domains, emails, phones). Shared with later outreach phases."""
    __tablename__ = "suppression_entries"
    __table_args__ = (UniqueConstraint("tenant_id", "kind", "value", name="uq_suppression"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # domain|email|phone
    value: Mapped[str] = mapped_column(String(300), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
