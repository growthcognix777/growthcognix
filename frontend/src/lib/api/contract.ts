import type {
  Activity, Agent, Client, ClientInput, DashboardSummary, DocumentMeta, Page, Product, ProductInput,
  ResearchJob, Role, Session, Tenant, User, Analysis, Finding, FindingType, IntelligenceProviders,
  IntelligenceSummary, VerificationStatus,
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
}
