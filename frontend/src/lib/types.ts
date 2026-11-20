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

// ---------------------------------------------------------------- Phase 4: Buyer discovery & lead intelligence
export type BuyerType = "end_user" | "distributor" | "importer" | "dealer" | "oem" | "institutional" | "project";
export type GeoLevel = "global" | "country" | "state" | "district" | "city" | "industrial_area";
export type LeadVerification = "discovered" | "company_verified" | "website_verified" | "industry_verified" | "product_relevance_verified" | "contact_verified" | "needs_review" | "rejected";
export type ScoreClass = "very_high" | "high" | "medium" | "low";
export interface LeadProvider { key: string; label: string; kind: string; configured: boolean; daily_limit: number | null; used_today: number | null; cost: string | null; status: string; note?: string; }
export interface LeadProviders { providers: LeadProvider[]; weights: Record<string, number>; classes: { min: number; class: ScoreClass }[]; verification_order: string[]; buyer_types: BuyerType[]; }
export interface GeoReference { levels: GeoLevel[]; countries: { name: string; code: string; comtrade: number }[]; india: { states: string[]; union_territories: string[]; note: string }; sources: { name: string; url: string }[]; }
export interface GeoArea { id: string; client_id: string; level: GeoLevel; name: string; code: string | null; parent_id: string | null; country_code: string | null; path: string[]; notes: string | null; source_url: string | null; created_at: string; }
export interface DiscoveryCampaign {
  id: string; client_id: string; name: string; status: "draft" | "queued" | "running" | "paused" | "cancelled" | "completed" | "failed";
  product_ids: string[]; persona_ids: string[]; geography_ids: string[]; buyer_types: string[]; sources: string[];
  config: { directory_urls?: string[]; results_per_query?: number; max_companies?: number; weights?: Record<string, number> | null };
  progress: number; stage: string | null; counts: Record<string, number>; attempts: number; error: string | null;
  started_at: string | null; completed_at: string | null; created_at: string; targets?: Record<string, number>;
}
export interface DiscoveryTarget { id: string; provider: string; query: string; status: string; results_count: number; new_prospects: number; attempts: number; error: string | null; executed_at: string | null; persona_id: string | null; geography_id: string | null; }
export interface Prospect {
  id: string; client_id: string; name: string; legal_name: string | null; website: string | null; domain: string | null; description: string | null;
  industry: string | null; sub_industry: string | null; company_category: string | null; buyer_type: BuyerType | null;
  country: string | null; state: string | null; district: string | null; city: string | null; industrial_area: string | null;
  searched_area: string[][]; observed_locations: string[]; qualification_reason: string | null; verification_status: LeadVerification;
  verified_fields: Record<string, { by: string; at: string; note?: string | null; source_url?: string | null }>; providers: string[]; origin: string;
  last_verified_at: string | null; site_checked_at: string | null; site_status: string | null; score_total: number | null; score_class: ScoreClass | null;
  confidence: number | null; crm_status: "none" | "approved" | "handed_off"; crm_handoff_at: string | null; assigned_to: string | null;
  first_campaign_id: string | null; created_at: string; updated_at: string;
}
export interface LeadEvidence { id: string; source_type: string; source_ref: string | null; source_url: string | null; excerpt: string | null; quote_matched: boolean; field: string | null; provider: string | null; observed_at: string | null; created_at: string; }
export interface BusinessContact { id: string; kind: "role_email" | "phone" | "person"; value: string | null; person_name: string | null; role: string | null; source_url: string | null; observed_at: string | null; origin: string; verified: boolean; purpose: string | null; }
export interface ScoreComponent { points: number; max: number; reasons: string[]; }
export interface LeadScore { total: number; score_class: ScoreClass; confidence: number; components: Record<string, ScoreComponent>; weights: Record<string, number>; explanation: string[]; version: string; created_at: string; }
export interface ProspectDetail extends Prospect {
  signals: { matched_terms?: { term: string; kind: string; url: string; excerpt: string }[]; intent?: { signal: string; strength: string; url: string; excerpt: string }[];
    capacity?: { kind: string; value: string; url: string; excerpt: string }[]; pages?: { url: string; title: string | null; type: string | null }[] };
  evidence: LeadEvidence[]; contacts: BusinessContact[];
  fits: { id: string; product_id: string | null; persona_id: string | null; application: string | null; relation: string; reason: string | null; matched_terms: string[]; origin: string; verified: boolean }[];
  score: LeadScore | null; verifications: { id: string; field: string; decision: string; note: string | null; source_url: string | null; user_id: string | null; created_at: string }[];
  assignments: { id: string; user_id: string | null; assigned_by: string | null; status: string; note: string | null; created_at: string }[];
}
export interface ProspectInput { name: string; website?: string | null; source_url: string; buyer_type?: BuyerType | null; industry?: string | null; company_category?: string | null; country?: string | null; state?: string | null; district?: string | null; city?: string | null; industrial_area?: string | null; note?: string | null; }
export interface ProspectQuery { q?: string; country?: string; state?: string; district?: string; city?: string; industry?: string; product_id?: string; buyer_type?: string; score_class?: string; min_score?: number; verification?: string; source?: string; campaign_id?: string; assigned_to?: string; crm_status?: string; include_rejected?: boolean; sort?: "score" | "recent" | "name"; limit?: number; offset?: number; }
export interface LeadSummary { prospects: number; by_class: Record<string, number>; by_status: Record<string, number>; by_buyer_type: Record<string, number>; by_crm: Record<string, number>; assigned: number; campaigns: Record<string, number>; profiles: number; areas: number; avg_score: number | null; }
export interface Suppression { id: string; kind: "domain" | "email" | "phone"; value: string; reason: string | null; created_at: string; }
export interface MarketInsight { id: string; client_id: string; product_id: string | null; kind: string; hs_code: string | null; reporter: string | null; partner: string | null; flow: string | null; period: string | null; value_usd: number | null; quantity: number | null; quantity_unit: string | null; title: string | null; detail: string | null; source: string; source_url: string | null; retrieved_at: string | null; created_at: string; }

// ---------------------------------------------------------------- Phase 5: Marketing strategy & campaigns
export type MkStatus = "draft" | "ai_generated" | "internal_review" | "client_review" | "approved" | "scheduled" | "published" | "rejected" | "failed";
export type MkEntity = "strategy" | "budget" | "content" | "ad_plan";
export type ReviewAction = "submit" | "approve" | "send_to_client" | "client_approve" | "reject" | "request_changes";
export type CostKind = "ad_spend" | "agency_fee" | "production";
export interface Reviewable {
  status: MkStatus; origin: string; provider: string | null; model: string | null; version: number; reviewed_by: string | null; reviewed_at: string | null;
  approved_by: string | null; approved_at: string | null; created_by: string | null; created_at: string; updated_at: string;
}
export interface StrategySection { key: string; summary: string; facts: { text: string; source_id: string; quote: string }[]; assumptions: string[]; recommendations: string[]; }
export interface MarketingStrategy extends Reviewable {
  id: string; client_id: string; title: string; inputs: Record<string, unknown>; sections: Record<string, StrategySection>; disclaimer: string | null;
  job_status: "queued" | "running" | "completed" | "failed"; error: string | null;
}
export interface StrategyInput { title: string; objectives?: string | null; monthly_budget?: number | null; currency?: string; sales_capacity?: string | null; channels_in_use?: string[]; product_ids?: string[]; notes?: string | null; }
export interface BudgetLine { category: string; cost_kind: CostKind; amount: number; note?: string | null; }
export interface BudgetSummary { monthly_total: number; quarterly_total: number; by_cost_kind: Record<CostKind, number>; by_category: Record<string, number>; quarterly_by_category: Record<string, number>; share: Record<string, number>; }
export interface MarketingBudget extends Reviewable {
  id: string; client_id: string; name: string; strategy_id: string | null; scenario: "base" | "conservative" | "growth" | "custom"; currency: string; monthly_total: number;
  lines: BudgetLine[]; quarterly_overrides: Record<string, number>; notes: string | null; summary: BudgetSummary;
}
export interface BudgetInput { name: string; monthly_total?: number | null; currency?: string; categories?: string[] | null; lines?: BudgetLine[] | null; scenario?: MarketingBudget["scenario"]; strategy_id?: string | null; notes?: string | null; }
export interface MarketingCampaign { id: string; client_id: string; name: string; objective: string | null; strategy_id: string | null; budget_id: string | null; start_date: string | null; end_date: string | null; status: "planned" | "active" | "paused" | "completed" | "archived"; created_at: string; }
export interface MarketingCampaignInput { name: string; objective?: string | null; strategy_id?: string | null; budget_id?: string | null; start_date?: string | null; end_date?: string | null; status?: MarketingCampaign["status"]; }
export interface ContentData {
  hashtags?: string[]; cta?: string | null; slides?: string[]; scenes?: { time?: string; visual?: string; voiceover?: string; on_screen_text?: string }[]; creative_brief?: string | null;
  keywords?: string[]; outline?: string[]; meta_title?: string | null; meta_description?: string | null; faqs?: { q: string; a: string }[]; internal_links?: { anchor: string; target: string }[];
  image_url?: string | null; link?: string | null; notes?: string | null; external_url?: string | null; removed_promises?: string[];
}
export interface ContentItem extends Reviewable {
  id: string; client_id: string; campaign_id: string | null; product_id: string | null; persona_id: string | null; studio: "social" | "seo"; kind: string; platform: string | null;
  title: string; body: string | null; data: ContentData; claims_to_check: string[]; asset_ids: string[]; scheduled_at: string | null; published_at: string | null;
  publishing_status: string; assigned_to: string | null;
}
export interface ContentInput { studio?: "social" | "seo"; kind: string; platform?: string | null; title: string; body?: string | null; data?: ContentData; product_id?: string | null; persona_id?: string | null; campaign_id?: string | null; scheduled_at?: string | null; assigned_to?: string | null; }
export interface ContentPatch { title?: string; body?: string | null; data?: ContentData; kind?: string; platform?: string | null; claims_to_check?: string[]; asset_ids?: string[]; scheduled_at?: string | null; clear_schedule?: boolean; assigned_to?: string | null; campaign_id?: string | null; note?: string | null; }
export interface GenerateContentInput { studio: "social" | "seo"; kind: string; platform?: string | null; product_id?: string | null; persona_id?: string | null; topic?: string | null; tone?: string | null; count?: number; campaign_id?: string | null; }
export interface BrandAsset { id: string; client_id: string; kind: string; name: string; document_id: string | null; value: string | null; product_id: string | null; tags: string[]; notes: string | null; approved: boolean; approved_by: string | null; approved_at: string | null; created_at: string; }
export interface BrandAssetInput { kind: string; name: string; document_id?: string | null; value?: string | null; product_id?: string | null; tags?: string[]; notes?: string | null; }
export interface AdPlan extends Reviewable {
  id: string; client_id: string; campaign_id: string | null; platform: "meta" | "google" | "linkedin"; name: string; objective: string | null; audience: Record<string, unknown>;
  geography: string[]; creative_brief: string | null; headlines: string[]; ad_copy: string[]; landing_page: string | null; currency: string; daily_budget: number | null;
  total_budget: number | null; bidding: string | null; conversion_tracking: string | null; ab_tests: string[]; targets: Record<string, unknown>; claims_to_check: string[];
  spend_approved: boolean; spend_cap: number | null; spend_approved_by: string | null; spend_approved_at: string | null; note?: string;
}
export interface AdPlanInput { platform: AdPlan["platform"]; name?: string; product_id?: string | null; persona_id?: string | null; objective?: string | null; geography?: string[]; landing_page?: string | null; daily_budget?: number | null; total_budget?: number | null; currency?: string; campaign_id?: string | null; audience?: Record<string, unknown>; creative_brief?: string | null; headlines?: string[]; ad_copy?: string[]; bidding?: string | null; conversion_tracking?: string | null; ab_tests?: string[]; targets?: Record<string, unknown>; }
export interface PlatformStatus { platform: string; automated: boolean; configured: boolean; note: string; missing: string[]; }
export interface SocialAccount { id: string; client_id: string; platform: string; account_name: string; external_id: string | null; status: string; token_expires_at: string | null; scopes: string[]; permissions: { can_publish?: boolean; can_read_insights?: boolean; [k: string]: unknown }; last_error: string | null; connected_by: string | null; connected_at: string | null; created_at: string; }
export interface PublishingJob { id: string; client_id: string; content_item_id: string; social_account_id: string | null; platform: string; status: "queued" | "publishing" | "published" | "failed" | "cancelled"; scheduled_at: string | null; attempts: number; error: string | null; external_post_id: string | null; external_url: string | null; content_version: number; requested_by: string | null; published_at: string | null; created_at: string; updated_at: string; title?: string | null; }
export interface MetricRow { source: "platform" | "calculated"; platform: string; entity_type: string; entity_id: string; title: string | null; external_id: string | null; metric: string; value: number; formula: string | null; retrieved_at: string; }
export interface MarketingAnalytics { platform: MetricRow[]; calculated: MetricRow[]; not_available: Record<string, string>; }
export interface MarketingReport { id: string; client_id: string; title: string; period_start: string; period_end: string; markdown?: string; data: Record<string, unknown>; created_at: string; }
export interface ApprovalRow { id: string; entity_type: MkEntity; entity_id: string; stage: string; status: string; requested_by: string | null; reviewer_id: string | null; reviewer_name: string | null; note: string | null; decided_at: string | null; entity_version: number; created_at: string; title?: string | null; entity_status?: MkStatus; platform?: string | null; kind?: string | null; claims_to_check?: string[]; current_version?: number; }
export interface Revision { id: string; version: number; snapshot: Record<string, unknown>; note: string | null; user_id: string | null; created_at: string; }
export interface CalendarSettings { timezone: string; require_client_review: boolean; default_reviewer_id: string | null; }
export interface MarketingStatus {
  ai: Record<string, unknown>; publishing: PlatformStatus[]; ad_platforms: Record<string, string>; approval_statuses: MkStatus[]; content_kinds: string[]; social_kinds: string[]; seo_kinds: string[];
  budget_categories: string[]; budget_labels: Record<string, string>; strategy_sections: string[]; analytics_unavailable: Record<string, string>; email_marketing: string;
}
export interface MarketingOverview { strategies: Record<string, number>; content: Record<string, number>; ad_plans: Record<string, number>; accounts: Record<string, number>; pending_approvals: number; upcoming: ContentItem[]; approved_budget: MarketingBudget | null; }
