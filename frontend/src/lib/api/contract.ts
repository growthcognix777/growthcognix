import type {
  Activity, Agent, Client, ClientInput, DashboardSummary, DocumentMeta, Page, Product, ProductInput,
  ResearchJob, Role, Session, Tenant, User, Analysis, Finding, FindingType, IntelligenceProviders,
  IntelligenceSummary, VerificationStatus, ClientWebsite, Competitor, CompetitorChange, CompetitorInput, CompetitorProfile,
  ComparisonRow, CrawlConfig, CrawlJob, CrawledPage, CrawlerStatus, Opportunity, SEOFinding, Topic, WebsiteAudit, WebsiteRec,
  BuyerType, DiscoveryCampaign, DiscoveryTarget, GeoArea, GeoLevel, GeoReference, LeadProviders, LeadSummary, MarketInsight,
  BusinessContact, Prospect, ProspectDetail, ProspectInput, ProspectQuery, Suppression, LeadScore,
  AdPlan, AdPlanInput, ApprovalRow, BrandAsset, BrandAssetInput, BudgetInput, BudgetLine, CalendarSettings, ContentInput, ContentItem, ContentPatch,
  GenerateContentInput, MarketingAnalytics, MarketingBudget, MarketingCampaign, MarketingCampaignInput, MarketingOverview, MarketingReport, MarketingStatus,
  MarketingStrategy, MkEntity, PlatformStatus, PublishingJob, ReviewAction, Revision, SocialAccount, StrategyInput, StrategySection, BudgetSummary,
} from "../types";
export interface ReviewInput { action: ReviewAction; note?: string | null; reviewer_name?: string | null; }

export interface CampaignInput { name: string; persona_ids: string[]; geography_ids: string[]; sources: string[]; directory_urls?: string[]; results_per_query?: number; max_companies?: number; weights?: Record<string, number> | null; }
export type ProspectPatch = Partial<Pick<Prospect, "name" | "legal_name" | "buyer_type" | "industry" | "sub_industry" | "company_category" | "country" | "state" | "district" | "city" | "industrial_area" | "qualification_reason">>;
export interface VerifyInput { field: "company" | "website" | "industry" | "product_relevance" | "contact" | "status"; decision: "verified" | "rejected" | "needs_review"; note?: string | null; source_url?: string | null; }

/** One contract, two drivers: HttpDriver (FastAPI) and LocalDriver (browser sandbox for GitHub Pages). */
export interface DataDriver {
  readonly mode: "api" | "local";
  register(b: { agency_name: string; full_name: string; email: string; password: string }): Promise<Session>;
  login(b: { email: string; password: string }): Promise<Session>;
  logout(): Promise<void>;
  me(): Promise<Session>;

  getAgency(): Promise<Tenant>;
  updateAgency(b: Partial<Tenant>): Promise<Tenant>;
  listUsers(): Promise<User[]>;
  createUser(b: { full_name: string; email: string; password: string; role: Role }): Promise<User>;
  changeRole(userId: string, role: Role): Promise<User>;

  listClients(q?: { q?: string; archived?: boolean }): Promise<Page<Client>>;
  getClient(id: string): Promise<Client>;
  createClient(b: ClientInput): Promise<Client>;
  updateClient(id: string, b: Partial<ClientInput>): Promise<Client>;
  archiveClient(id: string): Promise<Client>;
  restoreClient(id: string): Promise<Client>;
  deleteClient(id: string): Promise<void>;

  listProducts(q?: { client_id?: string; q?: string }): Promise<Page<Product>>;
  createProduct(b: ProductInput): Promise<Product>;
  updateProduct(id: string, b: Partial<ProductInput>): Promise<Product>;
  deleteProduct(id: string): Promise<void>;

  listDocuments(q?: { client_id?: string; product_id?: string }): Promise<Page<DocumentMeta>>;
  uploadDocument(file: File, clientId: string, productId?: string | null, onProgress?: (pct: number) => void): Promise<DocumentMeta>;
  downloadDocument(id: string): Promise<Blob>;
  deleteDocument(id: string): Promise<void>;

  listJobs(q?: { client_id?: string; status?: string }): Promise<Page<ResearchJob>>;
  cancelJob(id: string): Promise<ResearchJob>;
  listAgents(): Promise<Agent[]>;

  listActivity(q?: { limit?: number; entity_type?: string }): Promise<Page<Activity>>;
  dashboard(): Promise<DashboardSummary>;

  // Phase 2 — Client Intelligence. AI analysis runs only on the backend (keys never reach the browser).
  intelligenceProviders(): Promise<IntelligenceProviders>;
  startAnalysis(clientId: string, b?: { stages?: string[]; product_ids?: string[]; re_extract?: boolean }): Promise<Analysis>;
  listAnalyses(clientId: string): Promise<Analysis[]>;
  retryAnalysis(id: string): Promise<Analysis>;
  cancelAnalysis(id: string): Promise<Analysis>;
  intelligenceSummary(clientId: string): Promise<IntelligenceSummary>;
  listFindings(clientId: string, type: FindingType, q?: { status?: VerificationStatus; include_rejected?: boolean }): Promise<Page<Finding>>;
  createFinding(clientId: string, type: FindingType, b: { data: Record<string, unknown>; note?: string | null }): Promise<Finding>;
  editFinding(type: FindingType, id: string, data: Record<string, unknown>): Promise<Finding>;
  reviewFinding(type: FindingType, id: string, action: "approve" | "reject" | "needs_review", note?: string | null): Promise<Finding>;
  deleteFinding(type: FindingType, id: string): Promise<void>;
  reportMarkdown(clientId: string): Promise<string>;

  // Phase 3 — Website audit & competitor intelligence. Crawling runs only on the backend.
  crawlerStatus(): Promise<CrawlerStatus>;
  getClientWebsite(clientId: string): Promise<ClientWebsite>;
  saveClientWebsite(clientId: string, b: { url?: string | null; crawl_config?: Partial<CrawlConfig>; crawl_interval_days?: number | null }): Promise<WebsiteRec>;
  startAudit(clientId: string, config?: Partial<CrawlConfig>): Promise<CrawlJob>;
  listCrawls(clientId: string, kind?: "audit" | "competitor"): Promise<{ items: CrawlJob[] }>;
  getCrawl(id: string): Promise<CrawlJob>;
  cancelCrawl(id: string): Promise<CrawlJob>;
  retryCrawl(id: string): Promise<CrawlJob>;
  listCrawlPages(id: string, q?: { status?: string; page_type?: string; q?: string; limit?: number; offset?: number }): Promise<Page<CrawledPage>>;
  getCrawledPage(id: string): Promise<CrawledPage>;
  listAudits(clientId: string): Promise<{ items: WebsiteAudit[] }>;
  auditFindings(id: string, q?: { category?: string; severity?: string; source?: string }): Promise<Page<SEOFinding>>;
  auditTopics(id: string): Promise<{ items: Topic[]; basis: string }>;
  auditReport(id: string): Promise<string>;
  auditCsv(id: string): Promise<string>;

  listCompetitors(clientId: string, status?: string): Promise<{ items: Competitor[] }>;
  addCompetitor(clientId: string, b: CompetitorInput): Promise<Competitor>;
  editCompetitor(id: string, b: Partial<CompetitorInput> & { status?: "active" | "archived" }): Promise<Competitor>;
  deleteCompetitor(id: string): Promise<void>;
  reviewCompetitor(id: string, action: "accept" | "reject"): Promise<Competitor>;
  suggestCompetitors(clientId: string): Promise<{ created: number; dropped: Record<string, number> }>;
  analyseCompetitor(id: string): Promise<CrawlJob>;
  competitorProfile(id: string): Promise<CompetitorProfile>;
  competitorChanges(id: string): Promise<{ items: CompetitorChange[] }>;
  clientCompetitorChanges(clientId: string): Promise<{ items: CompetitorChange[] }>;
  comparison(clientId: string): Promise<{ items: ComparisonRow[]; basis: string }>;

  analyseOpportunities(clientId: string): Promise<{ created: number; note?: string }>;
  listOpportunities(clientId: string, q?: { status?: string; kind?: string; include_rejected?: boolean }): Promise<Page<Opportunity>>;
  reviewOpportunity(id: string, action: "approve" | "reject" | "needs_review", note?: string | null): Promise<Opportunity>;
  editOpportunity(id: string, b: Partial<Pick<Opportunity, "title" | "description" | "priority" | "next_action">>): Promise<Opportunity>;
  deleteOpportunity(id: string): Promise<void>;

  // Phase 4 — Buyer discovery & lead intelligence. Searching, site checks, AI profiles and UN Comtrade run only on the backend.
  leadProviders(): Promise<LeadProviders>;
  geoReference(): Promise<GeoReference>;
  listBuyerProfiles(clientId: string): Promise<Finding[]>;
  generateBuyerProfiles(clientId: string, b: { product_ids?: string[]; buyer_types?: BuyerType[]; geography?: string[] }): Promise<{ created: number }>;
  listGeos(clientId: string): Promise<GeoArea[]>;
  addGeo(clientId: string, b: { level: GeoLevel; name: string; parent_id?: string | null; code?: string | null; notes?: string | null; source_url?: string | null }): Promise<GeoArea>;
  deleteGeo(id: string): Promise<void>;
  listLeadCampaigns(clientId: string): Promise<DiscoveryCampaign[]>;
  createLeadCampaign(clientId: string, b: CampaignInput): Promise<DiscoveryCampaign>;
  getLeadCampaign(id: string): Promise<DiscoveryCampaign>;
  leadCampaignTargets(id: string): Promise<DiscoveryTarget[]>;
  startLeadCampaign(id: string): Promise<DiscoveryCampaign>;
  pauseLeadCampaign(id: string): Promise<DiscoveryCampaign>;
  cancelLeadCampaign(id: string): Promise<DiscoveryCampaign>;
  listProspects(clientId: string, q?: ProspectQuery): Promise<Page<Prospect>>;
  addProspect(clientId: string, b: ProspectInput): Promise<Prospect>;
  getProspect(id: string): Promise<ProspectDetail>;
  editProspect(id: string, b: ProspectPatch): Promise<Prospect>;
  deleteProspect(id: string): Promise<void>;
  verifyProspect(id: string, b: VerifyInput): Promise<Prospect>;
  reopenProspect(id: string): Promise<Prospect>;
  addProspectEvidence(id: string, b: { field: string; source_url: string; excerpt: string }): Promise<ProspectDetail>;
  addProspectContact(id: string, b: { kind: "role_email" | "phone" | "person"; value?: string | null; person_name?: string | null; role?: string | null; source_url: string; purpose?: string | null }): Promise<BusinessContact>;
  verifyContact(id: string, verified: boolean): Promise<BusinessContact>;
  deleteContact(id: string): Promise<void>;
  checkProspectSite(id: string): Promise<ProspectDetail>;
  scoreHistory(id: string): Promise<LeadScore[]>;
  rescoreLeads(clientId: string, b: { weights?: Record<string, number> | null; prospect_ids?: string[] }): Promise<{ rescored: number; weights: Record<string, number> }>;
  assignLeads(clientId: string, b: { prospect_ids: string[]; user_id: string | null; note?: string | null }): Promise<{ updated: number }>;
  approveLeads(clientId: string, b: { prospect_ids: string[]; approved: boolean }): Promise<{ updated: number; blocked: string[] }>;
  exportLeads(clientId: string, format: "csv" | "xlsx"): Promise<Blob>;
  crmHandoff(clientId: string, prospect_ids: string[]): Promise<{ handed_off: number; skipped: string[] }>;
  leadSummary(clientId: string): Promise<LeadSummary>;
  verificationQueue(clientId: string): Promise<Prospect[]>;
  listSuppression(): Promise<Suppression[]>;
  addSuppression(b: { kind: "domain" | "email" | "phone"; value: string; reason?: string | null }): Promise<Suppression>;
  deleteSuppression(id: string): Promise<void>;
  listMarketInsights(clientId: string, kind?: string): Promise<MarketInsight[]>;
  fetchComtrade(clientId: string, b: { hs_code: string; reporter: string; period: string; flow: "M" | "X"; partner?: string | null; product_id?: string | null }): Promise<MarketInsight[]>;
  addMarketInsight(clientId: string, b: { kind: string; title: string; detail?: string | null; source_url: string; product_id?: string | null; hs_code?: string | null; reporter?: string | null }): Promise<MarketInsight>;
  deleteMarketInsight(id: string): Promise<void>;

  // Phase 5 — Marketing strategy & campaigns. AI drafting, OAuth, publishing and analytics run only on the backend.
  marketingStatus(): Promise<MarketingStatus>;
  marketingOverview(clientId: string): Promise<MarketingOverview>;
  marketingHistory(entity: MkEntity, id: string): Promise<{ revisions: Revision[]; approvals: ApprovalRow[] }>;
  marketingApprovals(clientId: string, status?: string | null): Promise<ApprovalRow[]>;
  review(entity: MkEntity, id: string, b: ReviewInput): Promise<unknown>;
  listStrategies(clientId: string): Promise<MarketingStrategy[]>;
  createStrategy(clientId: string, b: StrategyInput): Promise<MarketingStrategy>;
  getStrategy(id: string): Promise<MarketingStrategy>;
  editStrategy(id: string, b: { title?: string; sections?: Record<string, Partial<StrategySection>>; note?: string | null }): Promise<MarketingStrategy>;
  retryStrategy(id: string): Promise<MarketingStrategy>;
  deleteStrategy(id: string): Promise<void>;
  budgetTemplate(monthlyTotal: number, categories?: string[]): Promise<{ lines: BudgetLine[]; summary: BudgetSummary; basis: string }>;
  listBudgets(clientId: string): Promise<MarketingBudget[]>;
  createBudget(clientId: string, b: BudgetInput): Promise<MarketingBudget>;
  editBudget(id: string, b: { name?: string; currency?: string; lines?: BudgetLine[]; quarterly_overrides?: Record<string, number>; notes?: string | null }): Promise<MarketingBudget>;
  budgetScenario(id: string, scenario: "base" | "conservative" | "growth"): Promise<MarketingBudget>;
  deleteBudget(id: string): Promise<void>;
  listMarketingCampaigns(clientId: string): Promise<MarketingCampaign[]>;
  createMarketingCampaign(clientId: string, b: MarketingCampaignInput): Promise<MarketingCampaign>;
  editMarketingCampaign(id: string, b: MarketingCampaignInput): Promise<MarketingCampaign>;
  deleteMarketingCampaign(id: string): Promise<void>;
  generateContent(clientId: string, b: GenerateContentInput): Promise<ContentItem[]>;
  addContent(clientId: string, b: ContentInput): Promise<ContentItem>;
  listContent(clientId: string, q?: { studio?: string; status?: string; platform?: string; campaign_id?: string }): Promise<ContentItem[]>;
  getContent(id: string): Promise<ContentItem>;
  editContent(id: string, b: ContentPatch): Promise<ContentItem>;
  deleteContent(id: string): Promise<void>;
  calendar(clientId: string, start: string, end: string): Promise<{ settings: CalendarSettings; items: ContentItem[] }>;
  saveCalendarSettings(clientId: string, b: CalendarSettings): Promise<CalendarSettings>;
  listAssets(clientId: string, kind?: string): Promise<BrandAsset[]>;
  addAsset(clientId: string, b: BrandAssetInput): Promise<BrandAsset>;
  approveAsset(id: string, approved: boolean): Promise<BrandAsset>;
  deleteAsset(id: string): Promise<void>;
  listAdPlans(clientId: string): Promise<AdPlan[]>;
  generateAdPlan(clientId: string, b: AdPlanInput): Promise<AdPlan>;
  addAdPlan(clientId: string, b: AdPlanInput & { name: string }): Promise<AdPlan>;
  editAdPlan(id: string, b: Partial<AdPlanInput>): Promise<AdPlan>;
  spendApproval(id: string, b: { approved: boolean; spend_cap?: number | null; note?: string | null }): Promise<AdPlan>;
  deleteAdPlan(id: string): Promise<void>;
  listSocialAccounts(clientId: string): Promise<{ accounts: SocialAccount[]; platforms: PlatformStatus[] }>;
  connectSocial(clientId: string, platform: "facebook" | "instagram" | "linkedin"): Promise<{ authorize_url: string }>;
  disconnectSocial(id: string): Promise<SocialAccount>;
  publishContent(id: string, b: { account_id: string; scheduled_at?: string | null }): Promise<PublishingJob>;
  markPublished(id: string, b: { url: string; published_at?: string | null }): Promise<ContentItem>;
  publishingJobs(clientId: string, status?: string): Promise<PublishingJob[]>;
  cancelPublishingJob(id: string): Promise<PublishingJob>;
  retryPublishingJob(id: string): Promise<PublishingJob>;
  refreshAnalytics(clientId: string): Promise<{ posts_updated: number; errors: string[]; not_available: string[]; notes: Record<string, string> }>;
  marketingAnalytics(clientId: string): Promise<MarketingAnalytics>;
  createMarketingReport(clientId: string, b: { start: string; end: string; title?: string | null }): Promise<MarketingReport>;
  listMarketingReports(clientId: string): Promise<MarketingReport[]>;
  marketingReportMarkdown(id: string): Promise<string>;
  deleteMarketingReport(id: string): Promise<void>;
}
