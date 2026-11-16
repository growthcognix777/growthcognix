import type {
  Activity, Agent, Client, ClientInput, DashboardSummary, DocumentMeta, Page, Product, ProductInput,
  ResearchJob, Role, Session, Tenant, User, Analysis, Finding, FindingType, IntelligenceProviders,
  IntelligenceSummary, VerificationStatus, ClientWebsite, Competitor, CompetitorChange, CompetitorInput, CompetitorProfile,
  ComparisonRow, CrawlConfig, CrawlJob, CrawledPage, CrawlerStatus, Opportunity, SEOFinding, Topic, WebsiteAudit, WebsiteRec,
} from "../types";

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
}
