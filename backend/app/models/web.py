"""Phase 3: Website Audit & Competitor Intelligence data model.

Facts and interpretation are kept apart:
  * CrawledPage / SEOFinding / CompetitorSnapshot / CompetitorChange hold what the crawler observed
    (or what PageSpeed measured), each with its source URL and timestamp.
  * Opportunity rows are recommendations (rule-based or AI) and use FindingMixin's review statuses;
    they are never shown as verified facts. Their evidence lives in EvidenceSource
    (finding_type="opportunity"), which also serves as the spec's ResearchSource, so there is a single
    evidence store across phases instead of a duplicate table.
"""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.entities import TimestampMixin, _uuid
from app.models.intelligence import FindingMixin


class _Owned(TimestampMixin):
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True, nullable=False)


class Competitor(_Owned, Base):
    __tablename__ = "competitors"
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    website: Mapped[str | None] = mapped_column(String(300))
    domain: Mapped[str | None] = mapped_column(String(253), index=True)
    category: Mapped[str] = mapped_column(String(20), default="direct", nullable=False)  # direct|indirect|substitute|aspirational
    # Why it is a competitor: product, application, customer, geography (never just a shared keyword)
    relevance: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    geography: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(20), default="user", nullable=False)  # user|ai
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)  # suggested|active|rejected|archived
    domain_valid: Mapped[bool | None] = mapped_column(Boolean)
    monitor_interval_days: Mapped[int | None] = mapped_column(Integer)  # None = manual only
    last_analysed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    positioning: Mapped[str | None] = mapped_column(Text)  # AI interpretation, labelled as such in the UI
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class Website(_Owned, Base):
    """A site we are authorised to crawl: the client's own, or a competitor's public pages."""
    __tablename__ = "websites"
    competitor_id: Mapped[str | None] = mapped_column(ForeignKey("competitors.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    domain: Mapped[str] = mapped_column(String(253), nullable=False, index=True)
    is_client_site: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    crawl_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    crawl_interval_days: Mapped[int | None] = mapped_column(Integer)
    last_crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CrawlJob(_Owned, Base):
    __tablename__ = "crawl_jobs"
    website_id: Mapped[str] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True, nullable=False)
    competitor_id: Mapped[str | None] = mapped_column(ForeignKey("competitors.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="audit", nullable=False)  # audit|competitor
    trigger: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)  # manual|scheduled
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False, index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    provider: Mapped[str] = mapped_column(String(30), default="native", nullable=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    # Resume state: URLs still to fetch [[url, depth], ...] and how far we got.
    frontier: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    pages_discovered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pages_crawled: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pages_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pages_blocked: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # disallowed by robots.txt
    robots: Mapped[dict | None] = mapped_column(JSON)  # {"found": bool, "sitemaps": [...], "crawl_delay": n}
    attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    stage: Mapped[str | None] = mapped_column(String(40))
    error: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[dict | None] = mapped_column(JSON)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class CrawledPage(_Owned, Base):
    __tablename__ = "crawled_pages"
    __table_args__ = (Index("ix_crawled_pages_job_url", "crawl_job_id", "url"),)
    website_id: Mapped[str] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True, nullable=False)
    crawl_job_id: Mapped[str] = mapped_column(ForeignKey("crawl_jobs.id", ondelete="CASCADE"), index=True, nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    final_url: Mapped[str | None] = mapped_column(String(1000))
    depth: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    redirect_chain: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(120))
    response_ms: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(String(500))
    meta_description: Mapped[str | None] = mapped_column(Text)
    h1: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    h2: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    canonical: Mapped[str | None] = mapped_column(String(1000))
    robots_meta: Mapped[str | None] = mapped_column(String(200))
    lang: Mapped[str | None] = mapped_column(String(20))
    has_viewport: Mapped[bool | None] = mapped_column(Boolean)
    structured_data: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # schema.org types found
    word_count: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str | None] = mapped_column(Text)  # readable text, truncated
    content_hash: Mapped[str | None] = mapped_column(String(64))
    internal_links: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    external_links_count: Mapped[int | None] = mapped_column(Integer)
    images_total: Mapped[int | None] = mapped_column(Integer)
    images_missing_alt: Mapped[int | None] = mapped_column(Integer)
    page_type: Mapped[str | None] = mapped_column(String(20))  # home|product|service|contact|about|blog|other
    blocked_by_robots: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    retries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WebsiteAudit(_Owned, Base):
    __tablename__ = "website_audits"
    website_id: Mapped[str] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True, nullable=False)
    crawl_job_id: Mapped[str] = mapped_column(ForeignKey("crawl_jobs.id", ondelete="CASCADE"), index=True, nullable=False)
    health_score: Mapped[int | None] = mapped_column(Integer)  # crawler-observation score, not a ranking
    summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    pagespeed: Mapped[dict | None] = mapped_column(JSON)  # measured by Google PageSpeed Insights, when configured
    page_scores: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # {url: score}
    recommendations: Mapped[list] = mapped_column(JSON, default=list, nullable=False)


class SEOFinding(_Owned, Base):
    __tablename__ = "seo_findings"
    audit_id: Mapped[str] = mapped_column(ForeignKey("website_audits.id", ondelete="CASCADE"), index=True, nullable=False)
    page_url: Mapped[str | None] = mapped_column(String(1000))
    check: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(30), nullable=False)  # security|indexing|metadata|content|links|media|mobile|accessibility|performance|structured_data
    severity: Mapped[str] = mapped_column(String(10), nullable=False)  # high|medium|low|info
    message: Mapped[str] = mapped_column(Text, nullable=False)
    observed_value: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), default="crawler", nullable=False)  # crawler|pagespeed
    measured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # True only for PageSpeed metrics


class KeywordTopic(_Owned, Base):
    """Topics the site covers, counted from titles/headings (crawler observation, not search volume)."""
    __tablename__ = "keyword_topics"
    audit_id: Mapped[str] = mapped_column(ForeignKey("website_audits.id", ondelete="CASCADE"), index=True, nullable=False)
    topic: Mapped[str] = mapped_column(String(200), nullable=False)
    pages: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    occurrences: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    in_titles: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    example_urls: Mapped[list] = mapped_column(JSON, default=list, nullable=False)


class CompetitorSnapshot(_Owned, Base):
    __tablename__ = "competitor_snapshots"
    competitor_id: Mapped[str] = mapped_column(ForeignKey("competitors.id", ondelete="CASCADE"), index=True, nullable=False)
    crawl_job_id: Mapped[str | None] = mapped_column(ForeignKey("crawl_jobs.id", ondelete="SET NULL"))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # {url: {"title","description","h1","hash","type","prices":[...],"promotions":[...]}}
    pages: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    homepage: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # {"url","title","h1","description"}
    products: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # [{"name","url"}]
    prices: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # [{"text","url"}] exactly as published
    certifications: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # [{"name","url"}]
    locations: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # [{"name","url"}]
    contact: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # {"emails":[company domain only],"phones":[], "url"}
    topics: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    seo: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # crawler-observed counts only


class CompetitorChange(_Owned, Base):
    __tablename__ = "competitor_changes"
    competitor_id: Mapped[str] = mapped_column(ForeignKey("competitors.id", ondelete="CASCADE"), index=True, nullable=False)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("competitor_snapshots.id", ondelete="CASCADE"), index=True, nullable=False)
    previous_snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("competitor_snapshots.id", ondelete="SET NULL"))
    change_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    url: Mapped[str | None] = mapped_column(String(1000))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Opportunity(FindingMixin, Base):
    """A recommendation for the client (from comparing the client's site with competitors and Phase 2
    intelligence). Always is_inferred: approval keeps it an hypothesis to act on, never a fact."""
    __tablename__ = "opportunities"
    kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(10), default="medium", nullable=False)
    next_action: Mapped[str | None] = mapped_column(Text)
    source_refs: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # [{"type","url","note"}]
    fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)  # de-duplicates re-runs
    crawl_job_id: Mapped[str | None] = mapped_column(ForeignKey("crawl_jobs.id", ondelete="SET NULL"))
    score: Mapped[float | None] = mapped_column(Float)
