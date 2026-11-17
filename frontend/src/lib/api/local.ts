/**
 * Browser sandbox driver — used on the GitHub Pages preview where no backend runs.
 * Stores ONLY records the user creates, in this browser's IndexedDB. No sample or fake data is ever seeded.
 * It mirrors the backend's rules (validation, tenant scoping, roles, activity log) so the UI behaves the same.
 * Not a security boundary: anyone with access to this browser can read its IndexedDB.
 */
import {
  ApiError, type Activity, type Agent, type Client, type ClientInput, type DocumentMeta, type Product,
  type ProductInput, type ResearchJob, type Role, type Session, type Tenant, type User,
  type Finding, type FindingType, type Competitor, type CompetitorInput,
  type GeoArea, type Prospect, type ProspectDetail, type LeadEvidence, type BusinessContact, type LeadScore, type Suppression, type MarketInsight,
  type LeadVerification,
} from "../types";
import { GEO_PARENT, GEO_REFERENCE, DEFAULT_WEIGHTS, EXPORT_COLUMNS, VERIFICATION_ORDER, computeScore, isListingSite, normaliseWeights, statusFromFields, toCsv } from "../leads";
import { approvedStatus, buildReportMarkdown, cleanFinding, isInferred } from "../intelligence";
import { normaliseUrl, validateClient, validateFile, validatePassword, validateProduct, isEmail } from "../validate";
import { AGENTS } from "../agents";
import type { DataDriver } from "./contract";
import { idb, type Store } from "./idb";
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

async function owned<T>(store: Store, tenantId: string, id: string, label: string): Promise<Owned<T>> {
  const r = await idb.get<Owned<T>>(store, id);
  if (!r || r.tenant_id !== tenantId) throw new ApiError(404, `${label} not found`);
  return r;
}
const scoped = async <T>(store: Store, tenantId: string) =>
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


// ---------------------------------------------------------------- Phase 4 helpers (browser preview)
const NO_DISCOVERY = "Buyer discovery searches, website checks and UN Comtrade lookups run only on the GrowthCognix backend (with SearXNG, Google Programmable Search or Brave configured). This browser preview has no server, so nothing is searched here and no prospects are simulated. You can still add prospects you found yourself, with their source.";
type PEv = Owned<LeadEvidence> & { prospect_id: string; client_id: string };
type PCt = Owned<BusinessContact> & { prospect_id: string; client_id: string };
type PSc = Owned<LeadScore> & { id: string; prospect_id: string };
type PVer = Owned<ProspectDetail["verifications"][number]> & { prospect_id: string };
type PRow = Owned<Prospect> & { signals: ProspectDetail["signals"]; assignments: ProspectDetail["assignments"] };
const digits = (s: string) => s.replace(/\D/g, "");
const srcUrl = (u: string | null | undefined, required = false): string | null => {
  if (!u || !u.trim()) { if (required) throw new ApiError(422, "A source URL is required", [{ field: "source_url", message: "Required" }]); return null; }
  const n = normaliseUrl(u.trim());
  if (!n) throw new ApiError(422, "Source URL must be a valid http(s) link", [{ field: "source_url", message: "Invalid URL" }]);
  return n.slice(0, 500);
};
async function isSuppressed(tenantId: string, kind: "domain" | "email" | "phone", value: string | null | undefined) {
  if (!value) return false;
  const rows = await scoped<Suppression>("suppression", tenantId);
  const v = value.trim().toLowerCase();
  const doms = rows.filter((r) => r.kind === "domain").map((r) => r.value);
  if (kind === "domain") return doms.some((d) => v === d || v.endsWith("." + d));
  if (kind === "email") return rows.some((r) => r.kind === "email" && r.value === v) || doms.includes(v.split("@").pop() || "");
  return rows.some((r) => r.kind === "phone" && digits(r.value) === digits(v));
}
async function rescoreLocal(p: PRow, weights?: Record<string, number> | null): Promise<PRow> {
  const contacts = (await scoped<PCt>("lead_contacts", p.tenant_id)).filter((c) => c.prospect_id === p.id);
  const ev = (await scoped<PEv>("lead_evidence", p.tenant_id)).filter((e) => e.prospect_id === p.id && e.source_type === "user");
  const r = computeScore(p, contacts, ev, weights);
  const next = { ...p, score_total: r.total, score_class: r.score_class, confidence: r.confidence, updated_at: now() };
  await idb.put("prospects", next);
  await idb.put<PSc>("lead_scores", { ...r, id: uid(), tenant_id: p.tenant_id, prospect_id: p.id, created_at: now() });
  return next;
}
const pOut = (p: PRow): Prospect => { const { tenant_id, signals, assignments, ...rest } = p; void tenant_id; void signals; void assignments; return rest; }; // eslint-disable-line @typescript-eslint/no-unused-vars
async function evidenceAdd(p: PRow, field: string, source_type: string, url: string | null, excerpt: string, provider: string) {
  await idb.put<PEv>("lead_evidence", { id: uid(), tenant_id: p.tenant_id, client_id: p.client_id, prospect_id: p.id, source_type, source_ref: null, source_url: url,
    excerpt: excerpt.slice(0, 1000), quote_matched: false, field, provider, observed_at: now(), created_at: now() });
}
async function detailLocal(p: PRow): Promise<ProspectDetail> {
  const t = p.tenant_id;
  const scores = (await scoped<PSc>("lead_scores", t)).filter((s) => s.prospect_id === p.id).sort(byNewest);
  return { ...pOut(p), signals: p.signals || {},
    evidence: (await scoped<PEv>("lead_evidence", t)).filter((e) => e.prospect_id === p.id).sort((a, b) => a.created_at.localeCompare(b.created_at)).map(({ tenant_id, prospect_id, client_id, ...e }) => e), // eslint-disable-line @typescript-eslint/no-unused-vars
    contacts: (await scoped<PCt>("lead_contacts", t)).filter((c) => c.prospect_id === p.id).map(({ tenant_id, prospect_id, client_id, ...c }) => c), // eslint-disable-line @typescript-eslint/no-unused-vars
    fits: [], score: scores[0] ? (({ tenant_id, prospect_id, id, ...s }) => s)(scores[0]) as LeadScore : null, // eslint-disable-line @typescript-eslint/no-unused-vars
    verifications: (await scoped<PVer>("lead_verifications", t)).filter((v) => v.prospect_id === p.id).sort(byNewest).map(({ tenant_id, prospect_id, ...v }) => v), // eslint-disable-line @typescript-eslint/no-unused-vars
    assignments: p.assignments || [] };
}

const NO_CRAWL = "Website crawling, audits and competitor analysis run only on the GrowthCognix backend. This browser preview has no server, so nothing can be crawled here (and no results are simulated). You can still add and organise competitors.";
const REL_KEYS = ["product", "application", "customer", "geography"];
const host = (u?: string | null) => { try { return u ? new URL(u.includes("://") ? u : `https://${u}`).hostname.toLowerCase().replace(/^www\./, "") : null; } catch { return null; } };

async function cleanCompetitor(tenantId: string, client: Client, b: Partial<CompetitorInput>, selfId?: string) {
  const out: Partial<CompetitorInput> & { domain?: string | null } = {};
  if (b.name !== undefined) { if (!b.name || b.name.trim().length < 2) throw new ApiError(422, "Name must be at least 2 characters", [{ field: "name", message: "Required" }]); out.name = b.name.trim().slice(0, 200); }
  if (b.category !== undefined) { if (!["direct", "indirect", "substitute", "aspirational"].includes(b.category)) throw new ApiError(422, "Invalid category"); out.category = b.category; }
  if (b.relevance !== undefined) {
    const bad = Object.keys(b.relevance).filter((k) => !REL_KEYS.includes(k));
    if (bad.length) throw new ApiError(422, `relevance keys must be ${REL_KEYS.join(", ")}`);
    out.relevance = Object.fromEntries(Object.entries(b.relevance).map(([k, v]) => [k, (v || "").trim().slice(0, 300)]).filter(([, v]) => v));
  }
  if (b.geography !== undefined) out.geography = b.geography.map((g) => g.trim().slice(0, 100)).filter(Boolean).slice(0, 20);
  if (b.notes !== undefined) out.notes = b.notes || null;
  if (b.monitor_interval_days !== undefined) out.monitor_interval_days = b.monitor_interval_days || null;
  if (b.website !== undefined) {
    const d = host(b.website);
    if (b.website && !d) throw new ApiError(422, "Enter a valid website (e.g. competitor.com)", [{ field: "website", message: "Invalid" }]);
    if (d && d === host(client.website)) throw new ApiError(400, "That is the client's own website");
    if (d) {
      const dup = (await scoped<Competitor>("competitors", tenantId)).find((c) => c.client_id === client.id && c.domain === d && c.id !== selfId);
      if (dup) throw new ApiError(409, `${dup.name} already uses that domain`);
    }
    out.website = d ? `https://${d}/` : null; out.domain = d;
  }
  return out;
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
    for (const k of (await scoped<Competitor>("competitors", tenant.id)).filter((k) => k.client_id === id)) await idb.del("competitors", k.id);
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

  async crawlerStatus() {
    await ctx();
    return { provider: "none (browser preview)", firecrawl_configured: false, pagespeed_configured: false, max_pages_limit: 0, competitor_max_pages: 0,
      defaults: { max_pages: 50, max_depth: 3, delay_seconds: 1, concurrency: 2, retries: 1, include: [], exclude: [], use_sitemap: true } };
  },
  async getClientWebsite(cid) { const { tenant } = await ctx(); const c = await owned<Client>("clients", tenant.id, cid, "Client"); return { website: null, client_website: c.website ?? null, latest_crawl: null, latest_audit: null }; },
  async saveClientWebsite() { await ctx(); throw new ApiError(409, NO_CRAWL); },
  async startAudit() { await ctx(); throw new ApiError(409, NO_CRAWL); },
  async listCrawls(cid) { const { tenant } = await ctx(); await owned("clients", tenant.id, cid, "Client"); return { items: [] }; },
  async getCrawl() { await ctx(); throw new ApiError(404, "Crawl not found"); },
  async cancelCrawl() { await ctx(); throw new ApiError(404, "Crawl not found"); },
  async retryCrawl() { await ctx(); throw new ApiError(409, NO_CRAWL); },
  async listCrawlPages() { await ctx(); return { items: [], total: 0 }; },
  async getCrawledPage() { await ctx(); throw new ApiError(404, "Page not found"); },
  async listAudits(cid) { const { tenant } = await ctx(); await owned("clients", tenant.id, cid, "Client"); return { items: [] }; },
  async auditFindings() { await ctx(); return { items: [], total: 0 }; },
  async auditTopics() { await ctx(); return { items: [], basis: "" }; },
  async auditReport() { await ctx(); throw new ApiError(404, "Audit not found"); },
  async auditCsv() { await ctx(); throw new ApiError(404, "Audit not found"); },

  async listCompetitors(cid, status) {
    const { tenant } = await ctx(); await owned("clients", tenant.id, cid, "Client");
    const rows = (await scoped<Competitor>("competitors", tenant.id)).filter((c) => c.client_id === cid && (status ? c.status === status : ["active", "suggested"].includes(c.status)));
    rows.sort((a, b) => a.created_at.localeCompare(b.created_at));
    return { items: rows.map(strip) as Competitor[] };
  },
  async addCompetitor(cid, b) {
    const { user, tenant } = await ctx();
    const client = await owned<Client>("clients", tenant.id, cid, "Client");
    const active = (await scoped<Competitor>("competitors", tenant.id)).filter((c) => c.client_id === cid && c.status === "active").length;
    if (active >= 30) throw new ApiError(400, "A client can track up to 30 competitors");
    const data = await cleanCompetitor(tenant.id, client, { ...b, category: b.category || "direct", relevance: b.relevance || {}, geography: b.geography || [] });
    if (!data.name) throw new ApiError(422, "Name is required", [{ field: "name", message: "Required" }]);
    const c: Owned<Competitor> = { id: uid(), tenant_id: tenant.id, client_id: cid, name: data.name, website: data.website ?? null, domain: data.domain ?? null,
      category: data.category!, relevance: data.relevance || {}, geography: data.geography || [], notes: data.notes ?? null, monitor_interval_days: data.monitor_interval_days ?? null,
      origin: "user", status: "active", domain_valid: null, last_analysed_at: null, positioning: null, created_at: now(), updated_at: now() };
    await idb.put("competitors", c);
    await log(tenant.id, user.id, "competitor.added", "competitor", c.id, `Competitor ${c.name} added to ${client.company_name}`, { client_id: cid });
    return strip(c) as Competitor;
  },
  async editCompetitor(id, b) {
    const { user, tenant } = await ctx();
    const c = await owned<Competitor>("competitors", tenant.id, id, "Competitor");
    const client = await owned<Client>("clients", tenant.id, c.client_id, "Client");
    const { status, ...rest } = b;
    const data = await cleanCompetitor(tenant.id, client, rest, id);
    const next = { ...c, ...data, ...(status ? { status } : {}), updated_at: now() } as Owned<Competitor>;
    await idb.put("competitors", next);
    await log(tenant.id, user.id, "competitor.edited", "competitor", id, `Competitor ${next.name} updated`, { client_id: c.client_id });
    return strip(next) as Competitor;
  },
  async deleteCompetitor(id) {
    const { user, tenant } = await ctx("manager");
    const c = await owned<Competitor>("competitors", tenant.id, id, "Competitor");
    await idb.del("competitors", id);
    await log(tenant.id, user.id, "competitor.deleted", "competitor", id, `Competitor ${c.name} deleted`, { client_id: c.client_id });
  },
  async reviewCompetitor(id, action) {
    const { user, tenant } = await ctx("manager");
    const c = await owned<Competitor>("competitors", tenant.id, id, "Competitor");
    const next = { ...c, status: action === "accept" ? "active" : "rejected", updated_at: now() } as Owned<Competitor>;
    await idb.put("competitors", next);
    await log(tenant.id, user.id, `competitor.${action}ed`, "competitor", id, `Competitor ${c.name} ${action}ed`, { client_id: c.client_id });
    return strip(next) as Competitor;
  },
  async suggestCompetitors() { await ctx(); throw new ApiError(409, NO_AI); },
  async analyseCompetitor() { await ctx(); throw new ApiError(409, NO_CRAWL); },
  async competitorProfile(id) {
    const { tenant } = await ctx();
    const c = await owned<Competitor>("competitors", tenant.id, id, "Competitor");
    return { competitor: strip(c) as Competitor, latest_snapshot: null, snapshots: 0, latest_crawl: null };
  },
  async competitorChanges(id) { const { tenant } = await ctx(); await owned("competitors", tenant.id, id, "Competitor"); return { items: [] }; },
  async clientCompetitorChanges(cid) { const { tenant } = await ctx(); await owned("clients", tenant.id, cid, "Client"); return { items: [] }; },
  async comparison(cid) { const { tenant } = await ctx(); await owned("clients", tenant.id, cid, "Client"); return { items: [], basis: "" }; },

  async analyseOpportunities(cid) { const { tenant } = await ctx(); await owned("clients", tenant.id, cid, "Client"); return { created: 0, note: NO_CRAWL }; },
  async listOpportunities(cid) { const { tenant } = await ctx(); await owned("clients", tenant.id, cid, "Client"); return { items: [], total: 0 }; },
  async reviewOpportunity() { await ctx(); throw new ApiError(404, "Opportunity not found"); },
  async editOpportunity() { await ctx(); throw new ApiError(404, "Opportunity not found"); },
  async deleteOpportunity() { await ctx(); throw new ApiError(404, "Opportunity not found"); },

  // ---------------------------------------------------------------- Phase 4 (browser preview)
  async leadProviders() {
    await ctx();
    const manual = [
      ["searxng", "SearXNG (self-hosted)", "search"], ["google_pse", "Google Programmable Search", "search"], ["brave", "Brave Search API", "search"],
      ["directory", "Directory / association list (URL you provide)", "directory"], ["site_verification", "Company website verification", "verification"], ["un_comtrade", "UN Comtrade (trade statistics)", "market_data"],
    ].map(([key, label, kind]) => ({ key, label, kind, configured: false, daily_limit: null, used_today: null, cost: null, status: "backend_only", note: "Runs on the backend only" }));
    const off = [["bing", "Bing Search API", "retired", "Microsoft retired the Bing Search APIs in August 2025."],
      ["indiamart", "IndiaMART / TradeIndia", "manual_only", "Terms restrict automated scraping. Use listings as manual signals."],
      ["gem", "GeM (Government e-Marketplace)", "manual_only", "Add a public bid URL to a prospect as intent evidence."],
      ["mca", "MCA company master data", "manual_only", "Record the CIN/registered name with the MCA page as evidence."],
      ["data_gov_in", "data.gov.in datasets", "not_implemented", "Planned as an import adapter."],
      ["itc_trade_map", "ITC Trade Map", "manual_only", "Enter figures as market insights with the Trade Map URL."]]
      .map(([key, label, status, note]) => ({ key, label, kind: "manual", configured: false, daily_limit: null, used_today: null, cost: null, status, note }));
    return { providers: [...manual, ...off], weights: DEFAULT_WEIGHTS, classes: [{ min: 80, class: "very_high" as const }, { min: 65, class: "high" as const }, { min: 40, class: "medium" as const }, { min: 0, class: "low" as const }],
      verification_order: VERIFICATION_ORDER, buyer_types: ["end_user", "distributor", "importer", "dealer", "oem", "institutional", "project"] as const as never };
  },
  async geoReference() { await ctx(); return GEO_REFERENCE; },
  async listBuyerProfiles(cid) {
    const { tenant } = await ctx(); await owned("clients", tenant.id, cid, "Client");
    return (await scoped<Finding>("findings", tenant.id)).filter((f) => f.client_id === cid && f.type === "persona" && f.verification_status !== "rejected")
      .sort((a, b) => a.created_at.localeCompare(b.created_at)).map(strip) as Finding[];
  },
  async generateBuyerProfiles() { await ctx("manager"); throw new ApiError(409, NO_AI); },

  async listGeos(cid) {
    const { tenant } = await ctx(); await owned("clients", tenant.id, cid, "Client");
    return (await scoped<GeoArea>("geos", tenant.id)).filter((g) => g.client_id === cid).sort((a, b) => a.created_at.localeCompare(b.created_at)).map(strip) as GeoArea[];
  },
  async addGeo(cid, b) {
    const { user, tenant } = await ctx(); await owned("clients", tenant.id, cid, "Client");
    let name = (b.name || "").split(/\s+/).filter(Boolean).join(" ");
    if (name.length < 2) throw new ApiError(422, "Name must be at least 2 characters", [{ field: "name", message: "Required" }]);
    let parent: Owned<GeoArea> | null = null;
    if (b.parent_id) {
      parent = await owned<GeoArea>("geos", tenant.id, b.parent_id, "Parent area");
      if (parent.client_id !== cid) throw new ApiError(400, "Parent area belongs to another client");
      if (!(GEO_PARENT[b.level] || []).includes(parent.level)) throw new ApiError(422, `A ${b.level} cannot sit under a ${parent.level}`);
    } else if (!["global", "country"].includes(b.level)) throw new ApiError(422, `A ${b.level} needs a parent area`);
    let code = (b.code || "").trim().toUpperCase() || null; let cc: string | null = null;
    if (b.level === "country") {
      const ref = GEO_REFERENCE.countries.find((x) => x.name.toLowerCase() === name.toLowerCase() || x.code === code);
      if (ref) { name = ref.name; code = ref.code; }
      cc = code && code.length === 2 ? code : null;
    } else cc = parent?.country_code ?? null;
    if (b.level === "state" && parent?.country_code === "IN" && ![...GEO_REFERENCE.india.states, ...GEO_REFERENCE.india.union_territories].includes(name))
      throw new ApiError(422, "Not an Indian state or union territory name (check spelling)");
    const all = (await scoped<GeoArea>("geos", tenant.id)).filter((g) => g.client_id === cid);
    if (all.some((g) => g.level === b.level && (g.parent_id || null) === (parent?.id || null) && g.name.toLowerCase() === name.toLowerCase())) throw new ApiError(409, `${name} is already saved`);
    const g: Owned<GeoArea> = { id: uid(), tenant_id: tenant.id, client_id: cid, level: b.level, name, code, parent_id: parent?.id || null, country_code: cc,
      path: [...(parent?.path || []), ...(b.level === "global" ? [] : [name])], notes: b.notes || null, source_url: srcUrl(b.source_url), created_at: now() };
    await idb.put("geos", g);
    await log(tenant.id, user.id, "leads.area_added", "geo", g.id, `Research area ${g.path.join(" > ") || "Global"} added`, { client_id: cid });
    return strip(g) as GeoArea;
  },
  async deleteGeo(id) {
    const { tenant } = await ctx(); await owned("geos", tenant.id, id, "Area");
    const all = await scoped<GeoArea>("geos", tenant.id);
    const kill = new Set([id]); let grew = true;
    while (grew) { grew = false; all.forEach((g) => { if (g.parent_id && kill.has(g.parent_id) && !kill.has(g.id)) { kill.add(g.id); grew = true; } }); }
    for (const k of kill) await idb.del("geos", k);
  },

  async listLeadCampaigns(cid) { const { tenant } = await ctx(); await owned("clients", tenant.id, cid, "Client"); return []; },
  async createLeadCampaign() { await ctx("manager"); throw new ApiError(409, NO_DISCOVERY); },
  async getLeadCampaign() { await ctx(); throw new ApiError(404, "Campaign not found"); },
  async leadCampaignTargets() { await ctx(); return []; },
  async startLeadCampaign() { await ctx(); throw new ApiError(409, NO_DISCOVERY); },
  async pauseLeadCampaign() { await ctx(); throw new ApiError(404, "Campaign not found"); },
  async cancelLeadCampaign() { await ctx(); throw new ApiError(404, "Campaign not found"); },

  async listProspects(cid, q = {}) {
    const { tenant } = await ctx(); await owned("clients", tenant.id, cid, "Client");
    let rows = (await scoped<PRow>("prospects", tenant.id)).filter((p) => p.client_id === cid);
    if (!q.include_rejected && q.verification !== "rejected") rows = rows.filter((p) => p.verification_status !== "rejected");
    const lc = (s?: string | null) => (s || "").toLowerCase();
    if (q.q) rows = rows.filter((p) => [p.name, p.domain, p.description].some((x) => lc(x).includes(lc(q.q))));
    (["buyer_type", "score_class", "assigned_to", "crm_status"] as const).forEach((k) => { if (q[k]) rows = rows.filter((p) => p[k] === q[k]); });
    if (q.verification) rows = rows.filter((p) => p.verification_status === q.verification);
    if (q.industry) rows = rows.filter((p) => lc(p.industry).includes(lc(q.industry)) || lc(p.sub_industry).includes(lc(q.industry)));
    if (q.min_score !== undefined && q.min_score !== null) rows = rows.filter((p) => (p.score_total ?? -1) >= Number(q.min_score));
    if (q.source) rows = rows.filter((p) => p.providers.includes(q.source!));
    if (q.product_id) rows = [];
    const geo: [keyof Prospect, string | undefined, number][] = [["country", q.country, 0], ["state", q.state, 1], ["district", q.district, 2], ["city", q.city, 3]];
    rows = rows.filter((p) => geo.every(([f, want, i]) => !want || lc(p[f] as string) === lc(want) || p.searched_area.some((a) => lc(a[i]) === lc(want)) || p.observed_locations.some((x) => lc(x) === lc(want))));
    const sort = q.sort || "score";
    rows.sort((a, b) => sort === "name" ? a.name.localeCompare(b.name) : sort === "recent" ? b.created_at.localeCompare(a.created_at) : ((b.score_total ?? -1) - (a.score_total ?? -1)) || b.created_at.localeCompare(a.created_at));
    const off = q.offset || 0; const lim = q.limit || 100;
    return { total: rows.length, items: rows.slice(off, off + lim).map(pOut) };
  },
  async addProspect(cid, b) {
    const { user, tenant } = await ctx(); await owned("clients", tenant.id, cid, "Client");
    if (!b.name || b.name.trim().length < 2) throw new ApiError(422, "Name must be at least 2 characters", [{ field: "name", message: "Required" }]);
    const src = srcUrl(b.source_url, true);
    const site = b.website ? normaliseUrl(b.website) : null;
    if (b.website && !site) throw new ApiError(422, "Enter a valid website", [{ field: "website", message: "Invalid URL" }]);
    const d = host(site);
    if (d && isListingSite(d)) throw new ApiError(422, "That is a listing or social site, not the company's own website");
    if (d && await isSuppressed(tenant.id, "domain", d)) throw new ApiError(409, "This domain is on the do-not-contact list");
    if (d && (await scoped<PRow>("prospects", tenant.id)).some((p) => p.client_id === cid && p.domain === d)) throw new ApiError(409, "A prospect with this domain already exists");
    const t = (x?: string | null) => (x && x.trim() ? x.trim() : null);
    const p: PRow = { id: uid(), tenant_id: tenant.id, client_id: cid, name: b.name.trim().slice(0, 300), legal_name: null, website: site, domain: d, description: null,
      industry: t(b.industry), sub_industry: null, company_category: t(b.company_category), buyer_type: b.buyer_type || null, country: t(b.country), state: t(b.state),
      district: t(b.district), city: t(b.city), industrial_area: t(b.industrial_area), searched_area: [], observed_locations: [], qualification_reason: t(b.note),
      verification_status: "discovered", verified_fields: {}, providers: ["manual"], origin: "manual", last_verified_at: null, site_checked_at: null, site_status: null,
      score_total: null, score_class: null, confidence: null, crm_status: "none", crm_handoff_at: null, assigned_to: null, first_campaign_id: null,
      created_at: now(), updated_at: now(), signals: {}, assignments: [] };
    await idb.put("prospects", p);
    await evidenceAdd(p, "discovery", "user", src, b.note || "Added by the team", "manual");
    const next = await rescoreLocal(p);
    await log(tenant.id, user.id, "leads.prospect_added", "prospect", p.id, `Prospect ${p.name} added manually`, { client_id: cid });
    return pOut(next);
  },
  async getProspect(id) { const { tenant } = await ctx(); return detailLocal(await owned<PRow>("prospects", tenant.id, id, "Prospect")); },
  async editProspect(id, b) {
    const { tenant } = await ctx(); const p = await owned<PRow>("prospects", tenant.id, id, "Prospect");
    const clean = Object.fromEntries(Object.entries(b).map(([k, v]) => [k, typeof v === "string" ? (v.trim() || null) : v]));
    if ("name" in clean && (!clean.name || String(clean.name).length < 2)) throw new ApiError(422, "Name must be at least 2 characters");
    const next = { ...p, ...clean, updated_at: now() } as PRow; await idb.put("prospects", next); return pOut(next);
  },
  async deleteProspect(id) {
    const { user, tenant } = await ctx("manager"); const p = await owned<PRow>("prospects", tenant.id, id, "Prospect");
    for (const s of ["lead_evidence", "lead_contacts", "lead_scores", "lead_verifications"] as const)
      for (const r of (await scoped<{ id: string; prospect_id: string }>(s, tenant.id)).filter((r) => r.prospect_id === id)) await idb.del(s, r.id);
    await idb.del("prospects", id);
    await log(tenant.id, user.id, "leads.prospect_deleted", "prospect", id, `Prospect ${p.name} deleted`, { client_id: p.client_id });
  },
  async verifyProspect(id, b) {
    const { user, tenant } = await ctx(); let p = await owned<PRow>("prospects", tenant.id, id, "Prospect");
    const src = srcUrl(b.source_url);
    if (b.decision === "verified" && b.field !== "status" && !(src || b.note)) throw new ApiError(422, "Say how you verified it: add a source URL or a note");
    const vf = { ...p.verified_fields };
    let status: LeadVerification = p.verification_status; let crm = p.crm_status; let last = p.last_verified_at;
    if (b.field === "status") {
      if (b.decision === "verified") throw new ApiError(422, "Verify individual fields; status accepts rejected or needs_review");
      status = b.decision; if (b.decision === "rejected" && crm === "approved") crm = "none";
    } else if (b.decision === "verified") {
      vf[b.field] = { by: user.id, at: now(), note: b.note || null, source_url: src };
      if (status === "needs_review") status = "discovered";
      status = statusFromFields(status, vf); last = now();
    } else {
      delete vf[b.field];
      status = b.decision === "needs_review" ? "needs_review" : statusFromFields(status, vf);
    }
    p = { ...p, verified_fields: vf, verification_status: status, crm_status: crm, last_verified_at: last };
    await idb.put("prospects", p);
    if (b.decision === "verified" && src && b.field !== "status") await evidenceAdd(p, b.field, "user", src, b.note || `${b.field} verified`, "team");
    await idb.put<PVer>("lead_verifications", { id: uid(), tenant_id: tenant.id, prospect_id: id, field: b.field, decision: b.decision, note: b.note || null, source_url: src, user_id: user.id, created_at: now() });
    p = await rescoreLocal(p);
    await log(tenant.id, user.id, "leads.verified", "prospect", id, `${p.name}: ${b.field} ${b.decision}`, { client_id: p.client_id });
    return pOut(p);
  },
  async reopenProspect(id) {
    const { tenant } = await ctx(); const p = await owned<PRow>("prospects", tenant.id, id, "Prospect");
    const next = { ...p, verification_status: statusFromFields("discovered", p.verified_fields) };
    await idb.put("prospects", next); return pOut(await rescoreLocal(next));
  },
  async addProspectEvidence(id, b) {
    const { tenant } = await ctx(); const p = await owned<PRow>("prospects", tenant.id, id, "Prospect");
    if (!["fit", "need", "intent", "capacity", "company", "industry", "location", "other"].includes(b.field)) throw new ApiError(422, "Unknown evidence field");
    if (!b.excerpt || b.excerpt.trim().length < 3) throw new ApiError(422, "Describe what the source shows", [{ field: "excerpt", message: "Required" }]);
    await evidenceAdd(p, b.field, "user", srcUrl(b.source_url, true), b.excerpt.trim(), "team");
    return detailLocal(await rescoreLocal(p));
  },
  async addProspectContact(id, b) {
    const { tenant } = await ctx(); const p = await owned<PRow>("prospects", tenant.id, id, "Prospect");
    const src = srcUrl(b.source_url, true);
    let v = (b.value || "").trim() || null;
    if (b.kind === "role_email") { if (!v || !isEmail(v)) throw new ApiError(422, "Enter a valid email", [{ field: "value", message: "Invalid email" }]); v = v.toLowerCase(); }
    if (b.kind === "phone" && (!v || digits(v).length < 8)) throw new ApiError(422, "Enter a valid phone number", [{ field: "value", message: "Invalid phone" }]);
    if (b.kind === "person" && !(b.person_name && b.role)) throw new ApiError(422, "A business contact needs a name and a role as published on the source page");
    if (v && await isSuppressed(tenant.id, v.includes("@") ? "email" : "phone", v)) throw new ApiError(409, "This contact is on the do-not-contact list");
    const client = await owned<Client>("clients", tenant.id, p.client_id, "Client");
    const c: PCt = { id: uid(), tenant_id: tenant.id, client_id: p.client_id, prospect_id: id, kind: b.kind, value: v, person_name: b.person_name || null, role: b.role || null,
      source_url: src, observed_at: now(), origin: "user", verified: false, purpose: b.purpose || `B2B prospect research for ${client.company_name}` };
    await idb.put("lead_contacts", c); await rescoreLocal(p);
    const { tenant_id, prospect_id, client_id, ...out } = c; void tenant_id; void prospect_id; void client_id; return out; // eslint-disable-line @typescript-eslint/no-unused-vars
  },
  async verifyContact(id, verified) {
    const { tenant } = await ctx(); const c = await owned<PCt>("lead_contacts", tenant.id, id, "Contact");
    const next = { ...c, verified }; await idb.put("lead_contacts", next);
    await rescoreLocal(await owned<PRow>("prospects", tenant.id, c.prospect_id, "Prospect"));
    const { tenant_id, prospect_id, client_id, ...out } = next; void tenant_id; void prospect_id; void client_id; return out; // eslint-disable-line @typescript-eslint/no-unused-vars
  },
  async deleteContact(id) {
    const { tenant } = await ctx(); const c = await owned<PCt>("lead_contacts", tenant.id, id, "Contact");
    await idb.del("lead_contacts", id); await rescoreLocal(await owned<PRow>("prospects", tenant.id, c.prospect_id, "Prospect"));
  },
  async checkProspectSite() { await ctx(); throw new ApiError(409, NO_DISCOVERY); },
  async scoreHistory(id) {
    const { tenant } = await ctx(); await owned("prospects", tenant.id, id, "Prospect");
    return (await scoped<PSc>("lead_scores", tenant.id)).filter((s) => s.prospect_id === id).sort(byNewest).slice(0, 50).map(({ tenant_id, prospect_id, id: _i, ...s }) => s as LeadScore); // eslint-disable-line @typescript-eslint/no-unused-vars
  },
  async rescoreLeads(cid, b) {
    const { tenant } = await ctx("manager"); await owned("clients", tenant.id, cid, "Client");
    let w: Record<string, number>; try { w = normaliseWeights(b.weights || null); } catch (e) { throw new ApiError(422, (e as Error).message); }
    const rows = (await scoped<PRow>("prospects", tenant.id)).filter((p) => p.client_id === cid && (!b.prospect_ids?.length || b.prospect_ids.includes(p.id)));
    for (const p of rows) await rescoreLocal(p, w);
    return { rescored: rows.length, weights: w };
  },
  async assignLeads(cid, b) {
    const { user, tenant } = await ctx("manager"); await owned("clients", tenant.id, cid, "Client");
    if (b.user_id) { const u = await idb.get<StoredUser>("users", b.user_id); if (!u || u.tenant_id !== tenant.id || !u.is_active) throw new ApiError(400, "That team member was not found"); }
    const rows = (await scoped<PRow>("prospects", tenant.id)).filter((p) => p.client_id === cid && b.prospect_ids.includes(p.id));
    for (const p of rows) {
      const asg = (p.assignments || []).map((a) => (a.status === "active" ? { ...a, status: "released" } : a));
      if (b.user_id) asg.unshift({ id: uid(), user_id: b.user_id, assigned_by: user.id, status: "active", note: b.note || null, created_at: now() });
      await idb.put("prospects", { ...p, assigned_to: b.user_id, assignments: asg });
    }
    await log(tenant.id, user.id, "leads.assigned", "client", cid, `${rows.length} prospect(s) ${b.user_id ? "assigned" : "unassigned"}`, { client_id: cid });
    return { updated: rows.length };
  },
  async approveLeads(cid, b) {
    const { user, tenant } = await ctx("manager"); await owned("clients", tenant.id, cid, "Client");
    const rows = (await scoped<PRow>("prospects", tenant.id)).filter((p) => p.client_id === cid && b.prospect_ids.includes(p.id));
    const blocked: string[] = []; let ok = 0;
    for (const p of rows) {
      if (b.approved) {
        if (["rejected", "needs_review"].includes(p.verification_status)) { blocked.push(`${p.name} is ${p.verification_status.replace("_", " ")}`); continue; }
        if (!Object.entries(p.verified_fields).some(([f, v]) => f === "company" && v.by !== "system")) { blocked.push(`${p.name}: a person must verify the company first`); continue; }
        if (p.crm_status === "none") await idb.put("prospects", { ...p, crm_status: "approved" });
      } else if (p.crm_status === "approved") await idb.put("prospects", { ...p, crm_status: "none" });
      ok++;
    }
    await log(tenant.id, user.id, b.approved ? "leads.approved" : "leads.unapproved", "client", cid, `${ok} prospect(s) updated`, { client_id: cid });
    return { updated: ok, blocked };
  },
  async exportLeads(cid, format) {
    const { user, tenant } = await ctx("manager"); await owned("clients", tenant.id, cid, "Client");
    if (format === "xlsx") throw new ApiError(409, "Excel export is built on the backend. In this browser preview, export CSV (Excel opens it).");
    const users = (await scoped<StoredUser>("users", tenant.id));
    const rows = (await scoped<PRow>("prospects", tenant.id)).filter((p) => p.client_id === cid && ["approved", "handed_off"].includes(p.crm_status))
      .sort((a, b) => (b.score_total ?? -1) - (a.score_total ?? -1));
    if (!rows.length) throw new ApiError(404, "No approved prospects to export. Verify and approve prospects first.");
    const contacts = await scoped<PCt>("lead_contacts", tenant.id); const ev = await scoped<PEv>("lead_evidence", tenant.id);
    const out: Record<string, unknown>[] = [];
    for (const p of rows) {
      const cs = contacts.filter((c) => c.prospect_id === p.id);
      const emails: string[] = []; const phones: string[] = [];
      for (const c of cs) {
        if (c.kind === "role_email" && c.value && !(await isSuppressed(tenant.id, "email", c.value))) emails.push(c.value);
        if (c.kind === "phone" && c.value && !(await isSuppressed(tenant.id, "phone", c.value))) phones.push(c.value);
      }
      const r: Record<string, unknown> = {};
      EXPORT_COLUMNS.forEach((k) => (r[k] = (p as unknown as Record<string, unknown>)[k] ?? ""));
      Object.assign(r, { role_emails: emails.join("; "), phones: phones.join("; "), assigned_to: users.find((u) => u.id === p.assigned_to)?.full_name || "",
        evidence_urls: [...new Set(ev.filter((e) => e.prospect_id === p.id && e.source_url).map((e) => e.source_url))].slice(0, 5).join(" "), last_verified_at: p.last_verified_at || "" });
      out.push(r);
    }
    await log(tenant.id, user.id, "leads.exported", "client", cid, `Exported ${rows.length} approved prospect(s) as CSV`, { client_id: cid });
    return new Blob([toCsv(out)], { type: "text/csv" });
  },
  async crmHandoff(cid, ids) {
    const { user, tenant } = await ctx("manager"); await owned("clients", tenant.id, cid, "Client");
    const rows = (await scoped<PRow>("prospects", tenant.id)).filter((p) => p.client_id === cid && ids.includes(p.id));
    let done = 0; const skipped: string[] = [];
    for (const p of rows) {
      if (p.crm_status !== "approved") { skipped.push(`${p.name}: not approved`); continue; }
      await idb.put("prospects", { ...p, crm_status: "handed_off", crm_handoff_at: now() }); done++;
    }
    await log(tenant.id, user.id, "leads.crm_handoff", "client", cid, `${done} approved prospect(s) handed to CRM`, { client_id: cid });
    return { handed_off: done, skipped };
  },
  async leadSummary(cid) {
    const { tenant } = await ctx(); await owned("clients", tenant.id, cid, "Client");
    const rows = (await scoped<PRow>("prospects", tenant.id)).filter((p) => p.client_id === cid);
    const group = (k: keyof Prospect) => rows.reduce<Record<string, number>>((a, p) => { const v = String(p[k] ?? "unset"); a[v] = (a[v] || 0) + 1; return a; }, {});
    const scored = rows.filter((p) => p.score_total !== null);
    return { prospects: rows.length, by_class: group("score_class"), by_status: group("verification_status"), by_buyer_type: group("buyer_type"), by_crm: group("crm_status"),
      assigned: rows.filter((p) => p.assigned_to).length, campaigns: {},
      profiles: (await scoped<Finding>("findings", tenant.id)).filter((f) => f.client_id === cid && f.type === "persona" && f.verification_status !== "rejected").length,
      areas: (await scoped<GeoArea>("geos", tenant.id)).filter((g) => g.client_id === cid).length,
      avg_score: scored.length ? scored.reduce((a, p) => a + (p.score_total || 0), 0) / scored.length : null };
  },
  async verificationQueue(cid) {
    const { tenant } = await ctx(); await owned("clients", tenant.id, cid, "Client");
    return (await scoped<PRow>("prospects", tenant.id)).filter((p) => p.client_id === cid && ["discovered", "website_verified", "needs_review"].includes(p.verification_status))
      .sort((a, b) => Number(b.verification_status === "needs_review") - Number(a.verification_status === "needs_review") || (b.score_total ?? -1) - (a.score_total ?? -1)).slice(0, 100).map(pOut);
  },
  async listSuppression() { const { tenant } = await ctx(); return (await scoped<Suppression>("suppression", tenant.id)).sort(byNewest).map(strip) as Suppression[]; },
  async addSuppression(b) {
    const { user, tenant } = await ctx();
    let v = (b.value || "").trim().toLowerCase();
    if (b.kind === "domain") { v = host(v) || ""; if (!v || !v.includes(".")) throw new ApiError(422, "Enter a domain like example.com"); }
    else if (b.kind === "phone") { v = digits(v); if (v.length < 8) throw new ApiError(422, "Enter a valid phone number"); }
    else if (!isEmail(v)) throw new ApiError(422, "Enter a valid email");
    if ((await scoped<Suppression>("suppression", tenant.id)).some((s) => s.kind === b.kind && s.value === v)) throw new ApiError(409, "Already on the list");
    const s: Owned<Suppression> = { id: uid(), tenant_id: tenant.id, kind: b.kind, value: v, reason: b.reason || null, created_at: now() };
    await idb.put("suppression", s);
    await log(tenant.id, user.id, "leads.suppressed", "suppression", null, `Added ${b.kind} to do-not-contact list`);
    return strip(s) as Suppression;
  },
  async deleteSuppression(id) { const { tenant } = await ctx("manager"); await owned("suppression", tenant.id, id, "Entry"); await idb.del("suppression", id); },
  async listMarketInsights(cid, kind) {
    const { tenant } = await ctx(); await owned("clients", tenant.id, cid, "Client");
    return (await scoped<MarketInsight>("insights", tenant.id)).filter((i) => i.client_id === cid && (!kind || i.kind === kind)).sort(byNewest).map(strip) as MarketInsight[];
  },
  async fetchComtrade() { await ctx(); throw new ApiError(409, NO_DISCOVERY); },
  async addMarketInsight(cid, b) {
    const { user, tenant } = await ctx(); await owned("clients", tenant.id, cid, "Client");
    if (!["current_demand", "tariff", "certification", "regulation", "logistics", "trade_agreement", "hs_code"].includes(b.kind)) throw new ApiError(422, "Unknown insight type");
    if (!b.title || b.title.trim().length < 3) throw new ApiError(422, "Title must be at least 3 characters", [{ field: "title", message: "Required" }]);
    if (b.product_id) { const pr = await owned<Product>("products", tenant.id, b.product_id, "Product"); if (pr.client_id !== cid) throw new ApiError(400, "Product belongs to another client"); }
    const i: Owned<MarketInsight> = { id: uid(), tenant_id: tenant.id, client_id: cid, product_id: b.product_id || null, kind: b.kind, hs_code: b.hs_code || null, reporter: b.reporter || null,
      partner: null, flow: null, period: null, value_usd: null, quantity: null, quantity_unit: null, title: b.title.trim(), detail: b.detail || null, source: "user",
      source_url: srcUrl(b.source_url, true), retrieved_at: now(), created_at: now() };
    await idb.put("insights", i);
    await log(tenant.id, user.id, "leads.insight_added", "insight", i.id, `Market insight added: ${i.title}`, { client_id: cid });
    return strip(i) as MarketInsight;
  },
  async deleteMarketInsight(id) { const { tenant } = await ctx(); await owned("insights", tenant.id, id, "Insight"); await idb.del("insights", id); },
};
