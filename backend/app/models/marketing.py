"""Phase 5: AI Marketing Strategy & Campaign Automation data model.

Reuse, not duplication:
  * Client, Product, BuyerPersona, TargetMarket, Competitor, WebsiteAudit and EvidenceSource are read as inputs.
  * Asset files are Phase 1 Documents (same storage, size limits and tenant checks); ContentAsset adds the
    brand meaning (logo, colour, font, guideline, template…) and its approval.
  * Calendar entries are ContentItem rows with a scheduled date. ContentCalendar only holds per-client
    calendar settings (time zone, default reviewer), so there is one source of truth for what is scheduled.

What the system may and may not do:
  * AI output is always a draft (`ai_generated`). Publishing needs status `approved` (or `scheduled`, which
    is only reachable from `approved`), a connected account with the right permission and an explicit
    publish request by a manager. Nothing is published automatically from any other status.
  * Ad plans never create, publish, change bids or spend on any ad platform in this phase. A spend approval
    is recorded with who approved it and the cap, for when an authorised ad-account adapter exists.
  * Metrics are stored only from a provider API (source="platform") or calculated from those
    (source="calculated"). Nothing is estimated or simulated.
"""
from datetime import datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.entities import TimestampMixin, _uuid

APPROVAL_STATUSES = ["draft", "ai_generated", "internal_review", "client_review", "approved", "scheduled", "published",
                     "rejected", "failed"]
PLATFORMS = ["instagram", "facebook", "linkedin", "youtube", "youtube_shorts", "website", "email", "google_ads", "meta_ads", "linkedin_ads"]
CONTENT_KINDS = ["single_image_post", "carousel", "reel_script", "short_video_script", "long_video_script", "caption",
                 "product_announcement", "educational", "case_study", "promotional", "seasonal",
                 "keyword_cluster", "topic_map", "article_outline", "blog_article", "product_description",
                 "industry_landing_page", "location_landing_page", "meta_tags", "faq", "internal_links"]
BUDGET_CATEGORIES = ["seo", "social_media", "content_production", "paid_search", "social_ads", "video_production",
                     "email_marketing", "agency_services"]
COST_KINDS = ["ad_spend", "agency_fee", "production"]


class _Owned(TimestampMixin):
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True, nullable=False)


class _Reviewable:
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False, index=True)
    origin: Mapped[str] = mapped_column(String(10), default="user", nullable=False)  # ai|user
    provider: Mapped[str | None] = mapped_column(String(30))
    model: Mapped[str | None] = mapped_column(String(80))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class MarketingStrategy(_Owned, _Reviewable, Base):
    """sections: {key: {"summary": str, "facts": [{text, source}], "assumptions": [str], "recommendations": [str]}}"""
    __tablename__ = "marketing_strategies"
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    inputs: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # snapshot of what the AI was given
    sections: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    disclaimer: Mapped[str | None] = mapped_column(Text)
    job_status: Mapped[str] = mapped_column(String(20), default="completed", nullable=False)  # queued|running|completed|failed
    error: Mapped[str | None] = mapped_column(Text)


class MarketingBudget(_Owned, _Reviewable, Base):
    """lines: [{category, cost_kind, amount, note}] per month. Quarterly = monthly x 3 unless overridden."""
    __tablename__ = "marketing_budgets"
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    strategy_id: Mapped[str | None] = mapped_column(ForeignKey("marketing_strategies.id", ondelete="SET NULL"))
    scenario: Mapped[str] = mapped_column(String(20), default="base", nullable=False)  # base|conservative|growth|custom
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    monthly_total: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    lines: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    quarterly_overrides: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


class MarketingCampaign(_Owned, Base):
    __tablename__ = "marketing_campaigns"
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    objective: Mapped[str | None] = mapped_column(String(300))
    strategy_id: Mapped[str | None] = mapped_column(ForeignKey("marketing_strategies.id", ondelete="SET NULL"))
    budget_id: Mapped[str | None] = mapped_column(ForeignKey("marketing_budgets.id", ondelete="SET NULL"))
    start_date: Mapped[datetime | None] = mapped_column(Date)
    end_date: Mapped[datetime | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="planned", nullable=False)  # planned|active|paused|completed|archived
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ContentCalendar(_Owned, Base):
    """Per-client calendar settings. Entries are ContentItem rows with scheduled_at."""
    __tablename__ = "content_calendars"
    __table_args__ = (UniqueConstraint("client_id", name="uq_calendar_client"),)
    timezone: Mapped[str] = mapped_column(String(60), default="Asia/Kolkata", nullable=False)
    default_reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    require_client_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ContentItem(_Owned, _Reviewable, Base):
    """Social posts, scripts, SEO pieces and ad copy. data holds kind-specific parts
    (hashtags, cta, slides, scenes, outline, meta_title, faqs, links…)."""
    __tablename__ = "content_items"
    __table_args__ = (Index("ix_content_schedule", "client_id", "scheduled_at"),)
    campaign_id: Mapped[str | None] = mapped_column(ForeignKey("marketing_campaigns.id", ondelete="SET NULL"), index=True)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    persona_id: Mapped[str | None] = mapped_column(ForeignKey("buyer_personas.id", ondelete="SET NULL"))
    studio: Mapped[str] = mapped_column(String(10), default="social", nullable=False)  # social|seo|ads
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    platform: Mapped[str | None] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    claims_to_check: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # statements a person must fact-check
    asset_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publishing_status: Mapped[str] = mapped_column(String(20), default="not_scheduled", nullable=False)
    # not_scheduled|scheduled|publishing|published|failed|manual
    assigned_to: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)


class ContentRevision(Base):
    """Revision history for strategies, budgets, content items and ad plans."""
    __tablename__ = "content_revisions"
    __table_args__ = (Index("ix_revision_entity", "entity_type", "entity_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ContentAsset(_Owned, Base):
    """Brand library entry. Files live in Documents; colours/fonts are values. Only approved assets can be
    attached to content."""
    __tablename__ = "content_assets"
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # logo|colour|font|product_image|guideline|template|creative
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    value: Mapped[str | None] = mapped_column(String(300))  # "#0B2A4A", "Montserrat", or a URL
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ApprovalRequest(_Owned, Base):
    """One review step. stage: internal_review|client_review|spend|publish."""
    __tablename__ = "approval_requests"
    __table_args__ = (Index("ix_approval_entity", "entity_type", "entity_id"),)
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)  # strategy|budget|content|ad_plan
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    stage: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)  # pending|approved|rejected|changes_requested|cancelled
    requested_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewer_name: Mapped[str | None] = mapped_column(String(200))  # e.g. the client contact who approved by email
    note: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    entity_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class SocialAccount(_Owned, Base):
    __tablename__ = "social_accounts"
    __table_args__ = (UniqueConstraint("client_id", "platform", "external_id", name="uq_social_account"),)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)  # facebook|instagram|linkedin|youtube
    account_name: Mapped[str] = mapped_column(String(200), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(120))  # page id / IG user id / organization URN / channel id
    status: Mapped[str] = mapped_column(String(20), default="not_connected", nullable=False)  # not_connected|connected|expired|error|revoked
    token_encrypted: Mapped[str | None] = mapped_column(Text)  # Fernet; never returned by the API
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    permissions: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # {can_publish, can_read_insights, checked_at, missing}
    last_error: Mapped[str | None] = mapped_column(Text)
    oauth_state: Mapped[str | None] = mapped_column(String(80), index=True)
    connected_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PublishingJob(_Owned, Base):
    __tablename__ = "publishing_jobs"
    content_item_id: Mapped[str] = mapped_column(ForeignKey("content_items.id", ondelete="CASCADE"), index=True, nullable=False)
    social_account_id: Mapped[str | None] = mapped_column(ForeignKey("social_accounts.id", ondelete="SET NULL"))
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False, index=True)  # queued|publishing|published|failed|cancelled
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    external_post_id: Mapped[str | None] = mapped_column(String(200))
    external_url: Mapped[str | None] = mapped_column(String(500))
    content_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    requested_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdvertisingCampaign(_Owned, _Reviewable, Base):
    """An ad plan. Never pushed to an ad platform in this phase."""
    __tablename__ = "advertising_campaigns"
    campaign_id: Mapped[str | None] = mapped_column(ForeignKey("marketing_campaigns.id", ondelete="SET NULL"))
    platform: Mapped[str] = mapped_column(String(20), nullable=False)  # meta|google|linkedin
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    objective: Mapped[str | None] = mapped_column(String(100))
    audience: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    geography: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    creative_brief: Mapped[str | None] = mapped_column(Text)
    headlines: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    ad_copy: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    landing_page: Mapped[str | None] = mapped_column(String(500))
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    daily_budget: Mapped[float | None] = mapped_column(Float)
    total_budget: Mapped[float | None] = mapped_column(Float)
    bidding: Mapped[str | None] = mapped_column(Text)
    conversion_tracking: Mapped[str | None] = mapped_column(Text)
    ab_tests: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    targets: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # goals the team sets, not predictions
    claims_to_check: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    spend_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    spend_cap: Mapped[float | None] = mapped_column(Float)
    spend_approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    spend_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CampaignMetric(_Owned, Base):
    """source: platform (reported by the provider API) | calculated (by GrowthCognix from platform values)."""
    __tablename__ = "campaign_metrics"
    __table_args__ = (Index("ix_metric_entity", "client_id", "entity_type", "entity_id"),)
    source: Mapped[str] = mapped_column(String(12), nullable=False)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)  # post|account|ad_campaign|campaign
    entity_id: Mapped[str | None] = mapped_column(String(36))
    external_id: Mapped[str | None] = mapped_column(String(200))
    metric: Mapped[str] = mapped_column(String(40), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    formula: Mapped[str | None] = mapped_column(String(200))  # for calculated metrics


class MarketingReport(_Owned, Base):
    __tablename__ = "marketing_reports"
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    period_start: Mapped[datetime | None] = mapped_column(Date)
    period_end: Mapped[datetime | None] = mapped_column(Date)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
