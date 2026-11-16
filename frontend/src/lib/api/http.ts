import { ApiError, type Page } from "../types";
import type { DataDriver } from "./contract";
import { tokenStore } from "./token";

const BASE = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

function qs(q?: Record<string, unknown>) {
  if (!q) return "";
  const p = new URLSearchParams();
  Object.entries(q).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") p.set(k, String(v)); });
  const s = p.toString();
  return s ? `?${s}` : "";
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const t = tokenStore.get();
  if (t) headers.set("Authorization", `Bearer ${t}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Can't reach the GrowthCognix API. Is the backend running on " + BASE + "?");
  }
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 401) tokenStore.clear();
    const msg = typeof body.detail === "string" ? body.detail : "Something went wrong";
    throw new ApiError(res.status, msg, body.errors || []);
  }
  return body as T;
}

const json = (b: unknown) => JSON.stringify(b);

export const httpDriver: DataDriver = {
  mode: "api",
  register: (b) => request("/api/v1/auth/register", { method: "POST", body: json(b) }),
  login: (b) => request("/api/v1/auth/login", { method: "POST", body: json(b) }),
  logout: () => request("/api/v1/auth/logout", { method: "POST" }),
  me: () => request("/api/v1/auth/me"),

  getAgency: () => request("/api/v1/agency"),
  updateAgency: (b) => request("/api/v1/agency", { method: "PATCH", body: json(b) }),
  listUsers: () => request("/api/v1/users"),
  createUser: (b) => request("/api/v1/users", { method: "POST", body: json(b) }),
  changeRole: (id, role) => request(`/api/v1/users/${id}/role`, { method: "PATCH", body: json({ role }) }),

  listClients: (q) => request(`/api/v1/clients${qs(q)}`),
  getClient: (id) => request(`/api/v1/clients/${id}`),
  createClient: (b) => request("/api/v1/clients", { method: "POST", body: json(b) }),
  updateClient: (id, b) => request(`/api/v1/clients/${id}`, { method: "PATCH", body: json(b) }),
  archiveClient: (id) => request(`/api/v1/clients/${id}/archive`, { method: "POST" }),
  restoreClient: (id) => request(`/api/v1/clients/${id}/restore`, { method: "POST" }),
  deleteClient: (id) => request(`/api/v1/clients/${id}`, { method: "DELETE" }),

  listProducts: (q) => request(`/api/v1/products${qs(q)}`),
  createProduct: (b) => request("/api/v1/products", { method: "POST", body: json(b) }),
  updateProduct: (id, b) => request(`/api/v1/products/${id}`, { method: "PATCH", body: json(b) }),
  deleteProduct: (id) => request(`/api/v1/products/${id}`, { method: "DELETE" }),

  listDocuments: (q) => request(`/api/v1/documents${qs(q)}`),
  uploadDocument: (file, clientId, productId, onProgress) =>
    new Promise((resolve, reject) => {
      const fd = new FormData();
      fd.append("file", file); fd.append("client_id", clientId);
      if (productId) fd.append("product_id", productId);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${BASE}/api/v1/documents`);
      const t = tokenStore.get(); if (t) xhr.setRequestHeader("Authorization", `Bearer ${t}`);
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(Math.round((e.loaded / e.total) * 100));
      xhr.onload = () => {
        const body = JSON.parse(xhr.responseText || "{}");
        xhr.status < 300 ? resolve(body) : reject(new ApiError(xhr.status, body.detail || "Upload failed", body.errors || []));
      };
      xhr.onerror = () => reject(new ApiError(0, "Upload failed: can't reach the API"));
      xhr.send(fd);
    }),
  downloadDocument: async (id) => {
    const res = await fetch(`${BASE}/api/v1/documents/${id}/download`, { headers: { Authorization: `Bearer ${tokenStore.get()}` } });
    if (!res.ok) throw new ApiError(res.status, "Download failed");
    return res.blob();
  },
  deleteDocument: (id) => request(`/api/v1/documents/${id}`, { method: "DELETE" }),

  listJobs: (q) => request<Page<never>>(`/api/v1/jobs${qs(q)}`),
  cancelJob: (id) => request(`/api/v1/jobs/${id}/cancel`, { method: "POST" }),
  listAgents: () => request("/api/v1/agents"),

  listActivity: (q) => request(`/api/v1/activity${qs(q)}`),
  dashboard: () => request("/api/v1/dashboard/summary"),

  intelligenceProviders: () => request("/api/v1/intelligence/providers"),
  startAnalysis: (cid, b) => request(`/api/v1/clients/${cid}/intelligence/analyses`, { method: "POST", body: json(b || {}) }),
  listAnalyses: (cid) => request(`/api/v1/clients/${cid}/intelligence/analyses`),
  retryAnalysis: (id) => request(`/api/v1/intelligence/analyses/${id}/retry`, { method: "POST" }),
  cancelAnalysis: (id) => request(`/api/v1/intelligence/analyses/${id}/cancel`, { method: "POST" }),
  intelligenceSummary: (cid) => request(`/api/v1/clients/${cid}/intelligence`),
  listFindings: (cid, type, q) => request(`/api/v1/clients/${cid}/intelligence/findings/${type}${qs(q)}`),
  createFinding: (cid, type, b) => request(`/api/v1/clients/${cid}/intelligence/findings/${type}`, { method: "POST", body: json(b) }),
  editFinding: (type, id, data) => request(`/api/v1/intelligence/findings/${type}/${id}`, { method: "PATCH", body: json({ data }) }),
  reviewFinding: (type, id, action, note) => request(`/api/v1/intelligence/findings/${type}/${id}/review`, { method: "POST", body: json({ action, note: note || null }) }),
  deleteFinding: (type, id) => request(`/api/v1/intelligence/findings/${type}/${id}`, { method: "DELETE" }),
  reportMarkdown: async (cid) => {
    const res = await fetch(`${BASE}/api/v1/clients/${cid}/intelligence/report.md`, { headers: { Authorization: `Bearer ${tokenStore.get()}` } });
    if (!res.ok) throw new ApiError(res.status, "Could not build the report");
    return res.text();
  },

  crawlerStatus: () => request("/api/v1/crawler/status"),
  getClientWebsite: (cid) => request(`/api/v1/clients/${cid}/website`),
  saveClientWebsite: (cid, b) => request(`/api/v1/clients/${cid}/website`, { method: "PUT", body: json(b) }),
  startAudit: (cid, config) => request(`/api/v1/clients/${cid}/website-audits`, { method: "POST", body: json({ crawl_config: config || null }) }),
  listCrawls: (cid, kind) => request(`/api/v1/clients/${cid}/crawls${qs({ kind })}`),
  getCrawl: (id) => request(`/api/v1/crawls/${id}`),
  cancelCrawl: (id) => request(`/api/v1/crawls/${id}/cancel`, { method: "POST" }),
  retryCrawl: (id) => request(`/api/v1/crawls/${id}/retry`, { method: "POST" }),
  listCrawlPages: (id, q) => request(`/api/v1/crawls/${id}/pages${qs(q)}`),
  getCrawledPage: (id) => request(`/api/v1/crawled-pages/${id}`),
  listAudits: (cid) => request(`/api/v1/clients/${cid}/website-audits`),
  auditFindings: (id, q) => request(`/api/v1/website-audits/${id}/findings${qs(q)}`),
  auditTopics: (id) => request(`/api/v1/website-audits/${id}/topics`),
  auditReport: (id) => text(`/api/v1/website-audits/${id}/report.md`),
  auditCsv: (id) => text(`/api/v1/website-audits/${id}/findings.csv`),

  listCompetitors: (cid, status) => request(`/api/v1/clients/${cid}/competitors${qs({ status })}`),
  addCompetitor: (cid, b) => request(`/api/v1/clients/${cid}/competitors`, { method: "POST", body: json(b) }),
  editCompetitor: (id, b) => request(`/api/v1/competitors/${id}`, { method: "PATCH", body: json(b) }),
  deleteCompetitor: (id) => request(`/api/v1/competitors/${id}`, { method: "DELETE" }),
  reviewCompetitor: (id, action) => request(`/api/v1/competitors/${id}/review`, { method: "POST", body: json({ action }) }),
  suggestCompetitors: (cid) => request(`/api/v1/clients/${cid}/competitors/suggest`, { method: "POST" }),
  analyseCompetitor: (id) => request(`/api/v1/competitors/${id}/analyse`, { method: "POST", body: json({}) }),
  competitorProfile: (id) => request(`/api/v1/competitors/${id}`),
  competitorChanges: (id) => request(`/api/v1/competitors/${id}/changes`),
  clientCompetitorChanges: (cid) => request(`/api/v1/clients/${cid}/competitor-changes`),
  comparison: (cid) => request(`/api/v1/clients/${cid}/competitors/comparison`),

  analyseOpportunities: (cid) => request(`/api/v1/clients/${cid}/opportunities/analyse`, { method: "POST" }),
  listOpportunities: (cid, q) => request(`/api/v1/clients/${cid}/opportunities${qs(q)}`),
  reviewOpportunity: (id, action, note) => request(`/api/v1/opportunities/${id}/review`, { method: "POST", body: json({ action, note: note || null }) }),
  editOpportunity: (id, b) => request(`/api/v1/opportunities/${id}`, { method: "PATCH", body: json(b) }),
  deleteOpportunity: (id) => request(`/api/v1/opportunities/${id}`, { method: "DELETE" }),
};

async function text(path: string): Promise<string> {
  const res = await fetch(`${BASE}${path}`, { headers: { Authorization: `Bearer ${tokenStore.get()}` } });
  if (!res.ok) throw new ApiError(res.status, "Download failed");
  return res.text();
}
