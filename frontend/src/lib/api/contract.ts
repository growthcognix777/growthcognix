import type {
  Activity, Agent, Client, ClientInput, DashboardSummary, DocumentMeta, Page, Product, ProductInput,
  ResearchJob, Role, Session, Tenant, User,
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
}
