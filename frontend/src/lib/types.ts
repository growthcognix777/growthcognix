// Typed interfaces mirroring backend/app/schemas.py
export type Role = "owner" | "admin" | "manager" | "staff";

export interface User { id: string; email: string; full_name: string; role: Role; is_active: boolean; created_at: string; }
export interface Tenant { id: string; name: string; slug: string; website?: string | null; phone?: string | null; address?: string | null; }
export interface Session { access_token: string; token_type: string; user: User; tenant: Tenant; }

export interface Page<T> { items: T[]; total: number; }

export interface ClientInput {
  company_name: string;
  website?: string | null;
  industry?: string | null;
  business_type?: string | null;
  description?: string | null;
  address?: string | null;
  contact_name?: string | null;
  contact_email?: string | null;
  contact_phone?: string | null;
  target_markets: string[];
  marketing_budget?: number | null;
  budget_currency: string;
  business_objectives?: string | null;
  assigned_user_id?: string | null;
}
export interface Client extends ClientInput {
  id: string;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  product_count: number;
  document_count: number;
}

export type ProductKind = "product" | "service";
export interface ProductInput {
  client_id: string;
  kind: ProductKind;
  name: string;
  category?: string | null;
  description?: string | null;
  specifications?: string | null;
  applications?: string | null;
  pricing?: string | null;
  min_order_quantity?: string | null;
  production_capacity?: string | null;
  target_industries: string[];
}
export interface Product extends ProductInput { id: string; created_at: string; updated_at: string; }

export interface DocumentMeta {
  id: string; client_id: string; product_id: string | null; original_name: string;
  content_type: string; file_ext: string; size_bytes: number; extraction_status: string; created_at: string;
}

export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export interface ResearchJob {
  id: string; client_id: string | null; job_type: string; agent_key: string | null; status: JobStatus;
  progress: number; started_at: string | null; completed_at: string | null; error: string | null;
  result: Record<string, unknown> | null; params: Record<string, unknown>; created_at: string;
}

export interface Agent { key: string; name: string; phase: number; description: string; status: "planned" | "active"; total_jobs: number; last_job_at: string | null; }

export interface Activity { id: string; user_id: string | null; action: string; entity_type: string; entity_id: string | null; summary: string; meta: Record<string, unknown>; created_at: string; }

export interface DashboardSummary { active_clients: number; archived_clients: number; products: number; documents: number; team_members: number; jobs_running: number; }

export interface FieldError { field: string; message: string; }
export class ApiError extends Error {
  status: number; errors: FieldError[];
  constructor(status: number, message: string, errors: FieldError[] = []) { super(message); this.status = status; this.errors = errors; }
}

// ---------------------------------------------------------------- Phase 2: Client Intelligence
export type FindingType = "profile" | "application" | "market" | "persona" | "insight";
export type VerificationStatus = "verified" | "ai_hypothesis" | "needs_review" | "rejected";
export interface Evidence {
  id: string; source_type: string; source_url: string | null; document_id: string | null;
  excerpt: string | null; quote_matched: boolean | null; created_at: string;
}
export interface Finding {
  id: string; type: FindingType; client_id: string; verification_status: VerificationStatus;
  confidence: number | null; is_inferred: boolean; approved: boolean; origin: string; edited: boolean;
  analysis_job_id: string | null; reviewed_by: string | null; reviewed_at: string | null; review_note: string | null;
  created_at: string; updated_at: string; data: Record<string, unknown>; evidence: Evidence[];
}
export interface AnalysisStage { key: string; label: string; status: string; error: string | null; result: Record<string, unknown> | null; }
export interface Analysis {
  id: string; client_id: string; status: JobStatus; progress: number; stages: AnalysisStage[]; attempts: number;
  provider: string | null; model: string | null; params: Record<string, unknown>; error: string | null;
  summary: Record<string, unknown> | null; started_at: string | null; completed_at: string | null; created_at: string;
}
export interface ProviderInfo { name: string; model: string; configured: boolean; used_for: string; }
export interface IntelligenceProviders { providers: ProviderInfo[]; stages: string[]; }
export interface IntelligenceSummary {
  status_counts: Record<VerificationStatus, number>;
  sources: { documents: number; documents_extracted: number; evidence_items: number };
  last_analysis: Analysis | null;
}

// ---------------------------------------------------------------- Phase 3: Website audit & competitors
export interface CrawlConfig {
  max_pages: number; max_depth: number; delay_seconds: number; concurrency: number; retries: number;
  include: string[]; exclude: string[]; use_sitemap: boolean;
}
export interface CrawlerStatus { provider: string; firecrawl_configured: boolean; pagespeed_configured: boolean; max_pages_limit: number; defaults: CrawlConfig; competitor_max_pages: number; }
export interface WebsiteRec { id: string; client_id: string; competitor_id: string | null; url: string; domain: string; is_client_site: boolean; crawl_config: Partial<CrawlConfig>; crawl_interval_days: number | null; last_crawled_at: string | null; created_at: string; }
export interface CrawlJob {
  id: string; client_id: string; website_id: string; competitor_id: string | null; kind: "audit" | "competitor"; trigger: string;
  status: JobStatus; progress: number; provider: string; config: CrawlConfig; pages_discovered: number; pages_crawled: number;
  pages_failed: number; pages_blocked: number; robots: Record<string, unknown> | null; attempts: number; stage: string | null;
  error: string | null; summary: Record<string, unknown> | null; started_at: string | null; completed_at: string | null; created_at: string;
}
export interface CrawledPage {
  id: string; url: string; final_url: string | null; depth: number; status_code: number | null; redirect_chain: { url: string; status: number | null }[];
  content_type: string | null; response_ms: number | null; title: string | null; meta_description: string | null; h1: string[]; h2: string[];
  canonical: string | null; robots_meta: string | null; lang: string | null; has_viewport: boolean | null; structured_data: string[];
  word_count: number | null; external_links_count: number | null; images_total: number | null; images_missing_alt: number | null;
  page_type: string | null; blocked_by_robots: boolean; retries: number; error: string | null; internal_links_count: number;
  fetched_at: string | null; internal_links?: string[]; text_preview?: string;
}
export interface PageSpeedResult { strategy: string; url?: string; error?: string; scores?: Record<string, number>; lab?: Record<string, number>; field?: Record<string, { p75: number; category: string }> | null; fetched_at?: string; source?: string; }
export interface Recommendation { kind: string; title: string; detail: string; urls: string[]; priority: string; basis: string; }
export interface WebsiteAudit {
  id: string; client_id: string; website_id: string; crawl_job_id: string; health_score: number | null;
  summary: Record<string, unknown> & { content_calendar?: { week: number; topic: string; status: string }[]; by_severity?: Record<string, number>; by_category?: Record<string, number> };
  pagespeed: { results?: PageSpeedResult[]; skipped?: string } | null; page_scores: Record<string, number>; recommendations: Recommendation[]; created_at: string;
}
export interface SEOFinding { id: string; page_url: string | null; check: string; category: string; severity: "high" | "medium" | "low" | "info"; message: string; observed_value: string | null; source: string; measured: boolean; created_at: string; }
export interface Topic { topic: string; pages: number; occurrences: number; in_titles: number; example_urls: string[]; }
export interface ClientWebsite { website: WebsiteRec | null; client_website: string | null; latest_crawl: CrawlJob | null; latest_audit: WebsiteAudit | null; }
export type CompetitorCategory = "direct" | "indirect" | "substitute" | "aspirational";
export interface CompetitorInput { name: string; website?: string | null; category: CompetitorCategory; relevance: Record<string, string>; geography: string[]; notes?: string | null; monitor_interval_days?: number | null; }
export interface Competitor extends CompetitorInput {
  id: string; client_id: string; domain: string | null; origin: string; status: "suggested" | "active" | "rejected" | "archived";
  domain_valid: boolean | null; last_analysed_at: string | null; positioning: string | null; created_at: string; updated_at: string;
}
export interface CompetitorSnapshot {
  id: string; competitor_id: string; crawl_job_id: string | null; captured_at: string; homepage: { url?: string; title?: string; h1?: string; description?: string };
  products: { name: string; url: string }[]; prices: { text: string; url: string }[]; certifications: { name: string; url: string }[];
  locations: { name: string; url: string }[]; contact: { emails?: string[]; phones?: string[]; url?: string | null }; topics: string[];
  seo: Record<string, unknown> & { promotions?: { text: string; url: string }[] }; pages_count: number;
}
export interface CompetitorProfile { competitor: Competitor; latest_snapshot: CompetitorSnapshot | null; snapshots: number; latest_crawl: CrawlJob | null; }
export interface CompetitorChange { id: string; competitor_id: string; snapshot_id: string; previous_snapshot_id: string | null; change_type: string; url: string | null; old_value: string | null; new_value: string | null; observed_at: string; competitor_name?: string | null; }
export interface ComparisonRow { id: string | null; name: string; is_client: boolean; website: string | null; captured_at: string; pages: number | null; product_pages: number | null; prices_published: number; certifications: string[]; locations: string[]; schema_types: string[]; avg_words: number | null; https: boolean | null; health_score: number | null; topics: string[]; shared_topics: string[]; }
export interface Opportunity {
  id: string; client_id: string; kind: string; title: string; description: string | null; rationale: string | null; priority: "high" | "medium" | "low";
  next_action: string | null; source_refs: { type: string; url?: string; note?: string }[]; confidence: number | null; origin: string;
  verification_status: VerificationStatus; approved: boolean; is_inferred: boolean; edited: boolean; reviewed_by: string | null;
  reviewed_at: string | null; review_note: string | null; created_at: string; updated_at: string;
  evidence: { id: string; source_type: string; source_url: string | null; excerpt: string | null; created_at: string }[];
}
