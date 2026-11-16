/**
 * Browser sandbox driver — used on the GitHub Pages preview where no backend runs.
 * Stores ONLY records the user creates, in this browser's IndexedDB. No sample or fake data is ever seeded.
 * It mirrors the backend's rules (validation, tenant scoping, roles, activity log) so the UI behaves the same.
 * Not a security boundary: anyone with access to this browser can read its IndexedDB.
 */
import {
  ApiError, type Activity, type Agent, type Client, type ClientInput, type DocumentMeta, type Product,
  type ProductInput, type ResearchJob, type Role, type Session, type Tenant, type User,
  type Finding, type FindingType,
} from "../types";
import { approvedStatus, buildReportMarkdown, cleanFinding, isInferred } from "../intelligence";
import { normaliseUrl, validateClient, validateFile, validatePassword, validateProduct, isEmail } from "../validate";
import { AGENTS } from "../agents";
import type { DataDriver } from "./contract";
import { idb } from "./idb";
import { tokenStore } from "./token";

type StoredUser = User & { tenant_id: string; password_hash: string; salt: string };
type Owned<T> = T & { tenant_id: string };
const RANK: Record<Role, number> = { staff: 0, manager: 1, admin: 2, owner: 3 };
const now = () => new Date().toISOString();
const uid = () => crypto.randomUUID();

async function hash(password: string, salt: string): Promise<string> {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits({ name: "PBKDF2", salt: new TextEncoder().encode(salt), iterations: 100_000, hash: "SHA-256" }, key, 256);
  return Array.from(new Uint8Array(bits)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function ctx(minRole: Role = "staff"): Promise<{ user: StoredUser; tenant: Tenant & { id: string } }> {
  const token = tokenStore.get();
  const sess = token ? await idb.get<{ id: string; user_id: string }>("sessions", token) : undefined;
  const user = sess ? await idb.get<StoredUser>("users", sess.user_id) : undefined;
  if (!user || !user.is_active) { tokenStore.clear(); throw new ApiError(401, "Not signed in"); }
  if (RANK[user.role] < RANK[minRole]) throw new ApiError(403, `Requires ${minRole} role or higher`);
  const tenant = (await idb.get<Tenant>("tenants", user.tenant_id))!;
  return { user, tenant };
}

async function owned<T>(store: "clients" | "products" | "documents" | "jobs" | "users" | "findings", tenantId: string, id: string, label: string): Promise<Owned<T>> {
  const r = await idb.get<Owned<T>>(store, id);
  if (!r || r.tenant_id !== tenantId) throw new ApiError(404, `${label} not found`);
  return r;
}
const scoped = async <T>(store: "clients" | "products" | "documents" | "jobs" | "activity" | "users" | "findings", tenantId: string) =>
  (await idb.all<Owned<T>>(store)).filter((r) => r.tenant_id === tenantId);

async function log(tenant_id: string, user_id: string, action: string, entity_type: string, entity_id: string | null, summary: string, meta: Record<string, unknown> = {}) {
  await idb.put<Owned<Activity>>("activity", { id: uid(), tenant_id, user_id, action, entity_type, entity_id, summary, meta, created_at: now() });
}

const publicUser = ({ password_hash, salt, tenant_id, ...u }: StoredUser): User => u; // eslint-disable-line @typescript-eslint/no-unused-vars
const strip = <T extends { tenant_id: string }>({ tenant_id, ...r }: T) => r; // eslint-disable-line @typescript-eslint/no-unused-vars
const byNewest = <T extends { created_at: string }>(a: T, b: T) => b.created_at.localeCompare(a.created_at);
const fail = (errs: { field: string; message: string }[]) => { if (errs.length) throw new ApiError(422, "Please check the highlighted fields", errs); };

async function session(user: StoredUser): Promise<Session> {
  const token = uid() + uid();
  await idb.put("sessions", { id: token, user_id: user.id });
  tokenStore.set(token);
  const tenant = (await idb.get<Tenant>("tenants", user.tenant_id))!;
  return { access_token: token, token_type: "bearer", user: publicUser(user), tenant };
}

async function withCounts(c: Owned<Client>): Promise<Client> {
  const products = (await scoped<Product>("products", c.tenant_id)).filter((p) => p.client_id === c.id).length;
  const docs = (await scoped<DocumentMeta>("documents", c.tenant_id)).filter((d) => d.client_id === c.id).length;
  return { ...strip(c), product_count: products, document_count: docs };
}

const NO_AI = "AI analysis runs only on the GrowthCognix backend, where the Gemini/Groq API keys are kept. This browser preview has no server, so no analysis can run here. You can still add, edit and review findings by hand.";
const RANK_OK = (r: Role, min: Role) => RANK[r] >= RANK[min];

async function checkProduct(tenantId: string, clientId: string, data: Record<string, unknown>) {
  if (!data.product_id) return;
  const p = await owned<Product>("products", tenantId, String(data.product_id), "Product");
  if (p.client_id !== clientId) throw new ApiError(400, "Product does not belong to this client");
}

function cleanClient<T extends Partial<ClientInput>>(b: T): T {
  const out = { ...b };
  if ("website" in out) out.website = normaliseUrl(out.website);
  (["contact_email", "contact_phone"] as const).forEach((k) => { if (k in out && !out[k]) out[k] = null; });
  return out;
}

export const localDriver: DataDriver = {
  mode: "local",

  async register(b) {
    const errs: { field: string; message: string }[] = [];
    if (b.agency_name.trim().length < 2) errs.push({ field: "agency_name", message: "Enter your agency name" });
    if (b.full_name.trim().length < 2) errs.push({ field: "full_name", message: "Enter your full name" });
    if (!isEmail(b.email)) errs.push({ field: "email", message: "Enter a valid email address" });
    const pw = validatePassword(b.password); if (pw) errs.push({ field: "password", message: pw });
    fail(errs);
    const email = b.email.trim().toLowerCase();
    if ((await idb.all<StoredUser>("users")).some((u) => u.email === email)) throw new ApiError(409, "An account with this email already exists");
    const tenant: Tenant = { id: uid(), name: b.agency_name.trim(), slug: b.agency_name.toLowerCase().replace(/[^a-z0-9]+/g, "-") };
    await idb.put("tenants", tenant);
    const salt = uid();
    const user: StoredUser = { id: uid(), tenant_id: tenant.id, email, full_name: b.full_name.trim(), role: "owner", is_active: true,
      created_at: now(), salt, password_hash: await hash(b.password, salt) };
    await idb.put("users", user);
    await log(tenant.id, user.id, "agency.registered", "tenant", tenant.id, `Agency ${tenant.name} registered`);
    return session(user);
  },
  async login(b) {
    const user = (await idb.all<StoredUser>("users")).find((u) => u.email === b.email.trim().toLowerCase());
    if (!user || (await hash(b.password, user.salt)) !== user.password_hash) throw new ApiError(401, "Incorrect email or password");
    await log(user.tenant_id, user.id, "user.login", "user", user.id, `${user.full_name} signed in`);
    return session(user);
  },
  async logout() {
    const t = tokenStore.get();
    try { const { user } = await ctx(); await log(user.tenant_id, user.id, "user.logout", "user", user.id, `${user.full_name} signed out`); } catch { /* already out */ }
    if (t) await idb.del("sessions", t);
    tokenStore.clear();
  },
  async me() {
    const { user, tenant } = await ctx();
    return { access_token: tokenStore.get()!, token_type: "bearer", user: publicUser(user), tenant };
  },

  async getAgency() { return (await ctx()).tenant; },
  async updateAgency(b) {
    const { user, tenant } = await ctx("admin");
    const t = { ...tenant, ...b, id: tenant.id, slug: tenant.slug };
    await idb.put("tenants", t);
    await log(tenant.id, user.id, "agency.updated", "tenant", tenant.id, "Agency profile updated");
    return t;
  },
  async listUsers() {
    const { tenant } = await ctx();
    return (await scoped<StoredUser>("users", tenant.id)).map((u) => publicUser(u as StoredUser));
  },
  async createUser(b) {
    const { user, tenant } = await ctx("admin");
    const errs: { field: string; message: string }[] = [];
    if (b.full_name.trim().length < 2) errs.push({ field: "full_name", message: "Enter a name" });
    if (!isEmail(b.email)) errs.push({ field: "email", message: "Enter a valid email" });
    const pw = validatePassword(b.password); if (pw) errs.push({ field: "password", message: pw });
    fail(errs);
    if (b.role === "owner" && user.role !== "owner") throw new ApiError(403, "Only the owner can add another owner");
    const email = b.email.trim().toLowerCase();
    if ((await idb.all<StoredUser>("users")).some((u) => u.email === email)) throw new ApiError(409, "An account with this email already exists");
    const salt = uid();
    const u: StoredUser = { id: uid(), tenant_id: tenant.id, email, full_name: b.full_name.trim(), role: b.role, is_active: true, created_at: now(), salt, password_hash: await hash(b.password, salt) };
    await idb.put("users", u);
    await log(tenant.id, user.id, "user.created", "user", u.id, `Team member ${u.full_name} added as ${u.role}`);
    return publicUser(u);
  },
  async changeRole(id, role) {
    const { user, tenant } = await ctx("admin");
    const u = await owned<StoredUser>("users", tenant.id, id, "User");
    if (u.id === user.id) throw new ApiError(400, "You cannot change your own role");
    if (RANK[role] >= RANK[user.role] && user.role !== "owner") throw new ApiError(403, "You cannot grant a role equal to or above your own");
    const nu = { ...u, role } as StoredUser; await idb.put("users", nu);
    await log(tenant.id, user.id, "user.role_changed", "user", u.id, `${u.full_name} is now ${role}`);
    return publicUser(nu);
  },

  async listClients(q) {
    const { tenant } = await ctx();
    let rows = (await scoped<Client>("clients", tenant.id)).filter((c) => (q?.archived ? !!c.archived_at : !c.archived_at));
    if (q?.q) { const s = q.q.toLowerCase(); rows = rows.filter((c) => [c.company_name, c.industry, c.website].some((v) => v?.toLowerCase().includes(s))); }
    rows.sort(byNewest);
    return { items: await Promise.all(rows.map(withCounts)), total: rows.length };
  },
  async getClient(id) { const { tenant } = await ctx(); return withCounts(await owned<Client>("clients", tenant.id, id, "Client")); },
  async createClient(b) {
    const { user, tenant } = await ctx();
    const body = cleanClient(b); fail(validateClient(body));
    if (body.assigned_user_id) await owned("users", tenant.id, body.assigned_user_id, "Assigned staff member");
    const c: Owned<Client> = { ...body, id: uid(), tenant_id: tenant.id, archived_at: null, created_at: now(), updated_at: now(), product_count: 0, document_count: 0 };
    await idb.put("clients", c);
    await log(tenant.id, user.id, "client.created", "client", c.id, `Client ${c.company_name} created`);
    return withCounts(c);
  },
  async updateClient(id, b) {
    const { user, tenant } = await ctx();
    const c = await owned<Client>("clients", tenant.id, id, "Client");
    const next = { ...c, ...cleanClient(b), updated_at: now() };
    fail(validateClient(next));
    if (b.assigned_user_id) await owned("users", tenant.id, b.assigned_user_id, "Assigned staff member");
    await idb.put("clients", next);
    await log(tenant.id, user.id, "client.updated", "client", id, `Client ${next.company_name} updated`, { fields: Object.keys(b).sort() });
    return withCounts(next);
  },
  async archiveClient(id) {
    const { user, tenant } = await ctx("manager");
    const c = await owned<Client>("clients", tenant.id, id, "Client");
    if (c.archived_at) throw new ApiError(400, "Client is already archived");
    const next = { ...c, archived_at: now() }; await idb.put("clients", next);
    await log(tenant.id, user.id, "client.archived", "client", id, `Client ${c.company_name} archived`);
    return withCounts(next);
  },
  async restoreClient(id) {
    const { user, tenant } = await ctx("manager");
    const c = await owned<Client>("clients", tenant.id, id, "Client");
    const next = { ...c, archived_at: null }; await idb.put("clients", next);
    await log(tenant.id, user.id, "client.restored", "client", id, `Client ${c.company_name} restored`);
    return withCounts(next);
  },
  async deleteClient(id) {
    const { user, tenant } = await ctx("admin");
    const c = await owned<Client>("clients", tenant.id, id, "Client");
    if (!c.archived_at) throw new ApiError(400, "Archive the client before deleting it permanently");
    for (const p of (await scoped<Product>("products", tenant.id)).filter((p) => p.client_id === id)) await idb.del("products", p.id);
    for (const d of (await scoped<DocumentMeta>("documents", tenant.id)).filter((d) => d.client_id === id)) { await idb.del("documents", d.id); await idb.del("blobs", d.id); }
    for (const f of (await scoped<Finding>("findings", tenant.id)).filter((f) => f.client_id === id)) await idb.del("findings", f.id);
    await idb.del("clients", id);
    await log(tenant.id, user.id, "client.deleted", "client", id, `Client ${c.company_name} permanently deleted`);
  },

  async listProducts(q) {
    const { tenant } = await ctx();
    let rows = await scoped<Product>("products", tenant.id);
    if (q?.client_id) rows = rows.filter((p) => p.client_id === q.client_id);
    if (q?.q) { const s = q.q.toLowerCase(); rows = rows.filter((p) => [p.name, p.category].some((v) => v?.toLowerCase().includes(s))); }
    rows.sort(byNewest);
    return { items: rows.map(strip) as Product[], total: rows.length };
  },
  async createProduct(b) {
    const { user, tenant } = await ctx();
    fail(validateProduct(b));
    const client = await owned<Client>("clients", tenant.id, b.client_id, "Client");
    const p: Owned<Product> = { ...b, id: uid(), tenant_id: tenant.id, created_at: now(), updated_at: now() };
    await idb.put("products", p);
    await log(tenant.id, user.id, "product.created", "product", p.id, `${p.kind === "service" ? "Service" : "Product"} ${p.name} added to ${client.company_name}`, { client_id: client.id });
    return strip(p) as Product;
  },
  async updateProduct(id, b) {
    const { user, tenant } = await ctx();
    const p = await owned<Product>("products", tenant.id, id, "Product");
    const next = { ...p, ...b, client_id: p.client_id, updated_at: now() };
    fail(validateProduct(next));
    await idb.put("products", next);
    await log(tenant.id, user.id, "product.updated", "product", id, `${next.name} updated`, { client_id: p.client_id });
    return strip(next) as Product;
  },
  async deleteProduct(id) {
    const { user, tenant } = await ctx("manager");
    const p = await owned<Product>("products", tenant.id, id, "Product");
    await idb.del("products", id);
    await log(tenant.id, user.id, "product.deleted", "product", id, `${p.name} deleted`, { client_id: p.client_id });
  },

  async listDocuments(q) {
    const { tenant } = await ctx();
    let rows = await scoped<DocumentMeta>("documents", tenant.id);
    if (q?.client_id) rows = rows.filter((d) => d.client_id === q.client_id);
    if (q?.product_id) rows = rows.filter((d) => d.product_id === q.product_id);
    rows.sort(byNewest);
    return { items: rows.map(strip) as DocumentMeta[], total: rows.length };
  },
  async uploadDocument(file, clientId, productId, onProgress) {
    const { user, tenant } = await ctx();
    const client = await owned<Client>("clients", tenant.id, clientId, "Client");
    if (productId) { const p = await owned<Product>("products", tenant.id, productId, "Product"); if (p.client_id !== clientId) throw new ApiError(400, "Product does not belong to this client"); }
    const err = validateFile(file); if (err) throw new ApiError(415, err);
    const ext = file.name.split(".").pop()!.toLowerCase();
    const head = new Uint8Array(await file.slice(0, 4).arrayBuffer());
    const magic: Record<string, number[]> = { pdf: [0x25, 0x50, 0x44, 0x46], docx: [0x50, 0x4b, 3, 4], png: [0x89, 0x50, 0x4e, 0x47], jpg: [0xff, 0xd8, 0xff], jpeg: [0xff, 0xd8, 0xff] };
    if (!magic[ext].every((b, i) => head[i] === b)) throw new ApiError(415, "File content does not match its extension");
    onProgress?.(50);
    const mime: Record<string, string> = { pdf: "application/pdf", docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg" };
    const doc: Owned<DocumentMeta> = { id: uid(), tenant_id: tenant.id, client_id: clientId, product_id: productId || null, original_name: file.name.slice(0, 255),
      content_type: mime[ext], file_ext: ext, size_bytes: file.size, extraction_status: "not_started", created_at: now() };
    await idb.put("blobs", { id: doc.id, tenant_id: tenant.id, blob: file });
    await idb.put("documents", doc);
    await log(tenant.id, user.id, "document.uploaded", "document", doc.id, `${doc.original_name} uploaded to ${client.company_name}`, { client_id: clientId });
    onProgress?.(100);
    return strip(doc) as DocumentMeta;
  },
  async downloadDocument(id) {
    const { tenant } = await ctx();
    await owned("documents", tenant.id, id, "Document");
    const b = await idb.get<{ id: string; blob: Blob }>("blobs", id);
    if (!b) throw new ApiError(410, "The stored file is missing");
    return b.blob;
  },
  async deleteDocument(id) {
    const { user, tenant } = await ctx("manager");
    const d = await owned<DocumentMeta>("documents", tenant.id, id, "Document");
    await idb.del("documents", id); await idb.del("blobs", id);
    await log(tenant.id, user.id, "document.deleted", "document", id, `${d.original_name} deleted`, { client_id: d.client_id });
  },

  async listJobs(q) {
    const { tenant } = await ctx();
    let rows = await scoped<ResearchJob>("jobs", tenant.id);
    if (q?.client_id) rows = rows.filter((j) => j.client_id === q.client_id);
    if (q?.status) rows = rows.filter((j) => j.status === q.status);
    rows.sort(byNewest);
    return { items: rows.map(strip) as ResearchJob[], total: rows.length };
  },
  async cancelJob(id) {
    const { tenant } = await ctx();
    const j = await owned<ResearchJob>("jobs", tenant.id, id, "Job");
    if (["completed", "failed", "cancelled"].includes(j.status)) throw new ApiError(400, `Job is already ${j.status}`);
    const next = { ...j, status: "cancelled" as const, completed_at: now() }; await idb.put("jobs", next);
    return strip(next) as ResearchJob;
  },
  async listAgents() {
    const { tenant } = await ctx();
    const jobs = await scoped<ResearchJob>("jobs", tenant.id);
    return AGENTS.map((a): Agent => {
      const mine = jobs.filter((j) => j.agent_key === a.key).sort(byNewest);
      return { ...a, status: "planned", total_jobs: mine.length, last_job_at: mine[0]?.created_at ?? null };
    });
  },

  async listActivity(q) {
    const { tenant } = await ctx();
    let rows = await scoped<Activity>("activity", tenant.id);
    if (q?.entity_type) rows = rows.filter((a) => a.entity_type === q.entity_type);
    rows.sort(byNewest);
    return { items: rows.slice(0, q?.limit ?? 50).map(strip) as Activity[], total: rows.length };
  },
  async dashboard() {
    const { tenant } = await ctx();
    const clients = await scoped<Client>("clients", tenant.id);
    const jobs = await scoped<ResearchJob>("jobs", tenant.id);
    return {
      active_clients: clients.filter((c) => !c.archived_at).length,
      archived_clients: clients.filter((c) => c.archived_at).length,
      products: (await scoped("products", tenant.id)).length,
      documents: (await scoped("documents", tenant.id)).length,
      team_members: (await scoped("users", tenant.id)).length,
      jobs_running: jobs.filter((j) => j.status === "queued" || j.status === "running").length,
    };
  },

  async intelligenceProviders() {
    await ctx();
    return { providers: [], stages: [] };
  },
  async startAnalysis() { await ctx(); throw new ApiError(409, NO_AI); },
  async listAnalyses(clientId) { const { tenant } = await ctx(); await owned("clients", tenant.id, clientId, "Client"); return []; },
  async retryAnalysis() { await ctx(); throw new ApiError(409, NO_AI); },
  async cancelAnalysis() { await ctx(); throw new ApiError(404, "Analysis not found"); },
  async intelligenceSummary(clientId) {
    const { tenant } = await ctx();
    await owned("clients", tenant.id, clientId, "Client");
    const rows = (await scoped<Finding>("findings", tenant.id)).filter((f) => f.client_id === clientId);
    const docs = (await scoped<DocumentMeta>("documents", tenant.id)).filter((d) => d.client_id === clientId);
    const counts = { verified: 0, ai_hypothesis: 0, needs_review: 0, rejected: 0 };
    rows.forEach((f) => { if (f.verification_status !== "rejected") counts[f.verification_status]++; });
    return { status_counts: counts, last_analysis: null,
      sources: { documents: docs.length, documents_extracted: 0, evidence_items: rows.reduce((n, f) => n + f.evidence.length, 0) } };
  },
  async listFindings(clientId, type, q) {
    const { tenant } = await ctx();
    await owned("clients", tenant.id, clientId, "Client");
    let rows = (await scoped<Finding>("findings", tenant.id)).filter((f) => f.client_id === clientId && f.type === type);
    if (q?.status) rows = rows.filter((f) => f.verification_status === q.status);
    else if (!q?.include_rejected) rows = rows.filter((f) => f.verification_status !== "rejected");
    rows.sort((a, b) => a.created_at.localeCompare(b.created_at));
    return { items: rows.map(strip) as Finding[], total: rows.length };
  },
  async createFinding(clientId, type, b) {
    const { user, tenant } = await ctx();
    const client = await owned<Client>("clients", tenant.id, clientId, "Client");
    const data = cleanFinding(type, b.data, false);
    await checkProduct(tenant.id, clientId, data);
    const t = now();
    const f: Owned<Finding> = { id: uid(), tenant_id: tenant.id, type, client_id: clientId, verification_status: "needs_review",
      confidence: null, is_inferred: isInferred(type, data), approved: false, origin: "user", edited: false, analysis_job_id: null,
      reviewed_by: null, reviewed_at: null, review_note: null, created_at: t, updated_at: t, data,
      evidence: [{ id: uid(), source_type: "user", source_url: null, document_id: null, excerpt: (b.note || "Entered by a team member").slice(0, 600), quote_matched: null, created_at: t }] };
    await idb.put("findings", f);
    await log(tenant.id, user.id, "finding.created", type, f.id, `${type[0].toUpperCase() + type.slice(1)} finding added for ${client.company_name}`, { client_id: clientId });
    return strip(f) as Finding;
  },
  async editFinding(type, id, patch) {
    const { user, tenant } = await ctx();
    const f = await owned<Finding>("findings", tenant.id, id, "Finding");
    if (f.type !== type) throw new ApiError(404, "Finding not found");
    const data = cleanFinding(type, patch, true);
    await checkProduct(tenant.id, f.client_id, data);
    const next: Owned<Finding> = { ...f, data: { ...f.data, ...data }, edited: true, approved: false, updated_at: now(),
      verification_status: ["verified", "rejected"].includes(f.verification_status) ? (f.is_inferred ? "ai_hypothesis" : "needs_review") : f.verification_status };
    await idb.put("findings", next);
    await log(tenant.id, user.id, "finding.edited", type, id, `${type[0].toUpperCase() + type.slice(1)} finding edited`, { client_id: f.client_id, fields: Object.keys(data).sort() });
    return strip(next) as Finding;
  },
  async reviewFinding(type, id, action, note) {
    const { user, tenant } = await ctx();
    if (!RANK_OK(user.role, "manager")) throw new ApiError(403, "Requires manager role or higher");
    const f = await owned<Finding>("findings", tenant.id, id, "Finding");
    if (f.type !== type) throw new ApiError(404, "Finding not found");
    const status = action === "approve" ? approvedStatus(f) : action === "reject" ? "rejected" : "needs_review";
    const next: Owned<Finding> = { ...f, approved: action === "approve", verification_status: status,
      reviewed_by: user.id, reviewed_at: now(), review_note: note || null, updated_at: now() };
    await idb.put("findings", next);
    const verb = action === "approve" ? "approved" : action === "reject" ? "rejected" : "sent back for review";
    await log(tenant.id, user.id, `finding.${action}`, type, id, `${type[0].toUpperCase() + type.slice(1)} finding ${verb}`, { client_id: f.client_id });
    return strip(next) as Finding;
  },
  async deleteFinding(type, id) {
    const { user, tenant } = await ctx();
    if (!RANK_OK(user.role, "admin")) throw new ApiError(403, "Requires admin role or higher (reject keeps an audit trail instead)");
    const f = await owned<Finding>("findings", tenant.id, id, "Finding");
    await idb.del("findings", id);
    await log(tenant.id, user.id, "finding.deleted", type, id, `${type[0].toUpperCase() + type.slice(1)} finding deleted`, { client_id: f.client_id });
  },
  async reportMarkdown(clientId) {
    const { tenant } = await ctx();
    const client = await owned<Client>("clients", tenant.id, clientId, "Client");
    const rows = (await scoped<Finding>("findings", tenant.id)).filter((f) => f.client_id === clientId).sort((a, b) => a.created_at.localeCompare(b.created_at));
    const by = { profile: [], application: [], market: [], persona: [], insight: [] } as Record<FindingType, Finding[]>;
    rows.forEach((f) => by[f.type].push(f));
    const products = (await scoped<Product>("products", tenant.id)).filter((p) => p.client_id === clientId);
    return buildReportMarkdown(client.company_name, by, products);
  },
};
