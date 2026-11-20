/**
 * Phase 5 in the browser preview. Stores only what the user creates (budgets, campaigns, content written by hand,
 * brand assets, ad plans, approvals, calendar). AI drafting, OAuth connections, publishing and analytics need the
 * backend, so they refuse with an explanation; nothing is simulated. Mirrors the backend's approval rules.
 */
import {
  ApiError, type AdPlan, type ApprovalRow, type BrandAsset, type CalendarSettings, type ContentItem, type MarketingBudget, type MarketingCampaign,
  type MarketingReport, type MkEntity, type MkStatus, type Product, type PublishingJob, type Revision, type Role, type Tenant, type User, type Client,
  type BudgetLine, type DocumentMeta,
} from "../types";
import {
  AD_ADAPTERS, AD_LIMITS, ANALYTICS_UNAVAILABLE, BUDGET_CATEGORIES, BUDGET_LABELS, COST_LABEL, LIMITS, SEO_KINDS, SOCIAL_KINDS, SOCIAL_PLATFORMS,
  STRATEGY_SECTIONS, APPROVAL_STATUSES, ACTIONS, SCENARIOS, cleanLines, detectClaims, guaranteeIssues, nextStatus, scenarioLines, summarise, templateLines, validateAsset,
} from "../marketing";
import { normaliseUrl } from "../validate";
import type { DataDriver } from "./contract";
import { idb, type Store } from "./idb";

type Owned<T> = T & { tenant_id: string };
type Ctx = { user: User & { tenant_id: string }; tenant: Tenant & { id: string } };
export interface LocalHelpers {
  ctx(minRole?: Role): Promise<Ctx>;
  owned<T>(store: Store, tenantId: string, id: string, label: string): Promise<Owned<T>>;
  scoped<T>(store: Store, tenantId: string): Promise<Owned<T>[]>;
  log(tenant_id: string, user_id: string, action: string, entity_type: string, entity_id: string | null, summary: string, meta?: Record<string, unknown>): Promise<void>;
}

const now = () => new Date().toISOString();
const uid = () => crypto.randomUUID();
const RANK: Record<Role, number> = { staff: 0, manager: 1, admin: 2, owner: 3 };
const strip = <T extends { tenant_id: string }>({ tenant_id, ...r }: T) => { void tenant_id; return r; };
const byNewest = <T extends { created_at: string }>(a: T, b: T) => b.created_at.localeCompare(a.created_at);
const STORE: Record<MkEntity, Store> = { strategy: "mk_strategies", budget: "mk_budgets", content: "mk_content", ad_plan: "mk_ad_plans" };
const FIELDS: Record<MkEntity, string[]> = {
  strategy: ["title", "sections", "status"],
  budget: ["name", "scenario", "currency", "lines", "quarterly_overrides", "monthly_total", "status"],
  content: ["title", "body", "data", "kind", "platform", "claims_to_check", "asset_ids", "scheduled_at", "status"],
  ad_plan: ["name", "objective", "audience", "geography", "creative_brief", "headlines", "ad_copy", "landing_page", "daily_budget", "total_budget", "bidding", "conversion_tracking", "ab_tests", "targets", "status"],
};
const NO_SERVER_AI = "AI drafting runs only on the GrowthCognix backend, where the Gemini/Groq keys are kept. This browser preview has no server, so nothing is generated here. You can write drafts yourself and run them through review.";
const NO_SERVER_SOCIAL = "Connecting accounts, publishing and reading analytics use Meta's and LinkedIn's official APIs from the GrowthCognix backend (OAuth tokens are kept encrypted on the server). This browser preview has no server, so nothing is connected or posted. Approved items can be recorded as published manually with their live URL.";
const DATA_KEYS = new Set(["hashtags", "cta", "slides", "scenes", "creative_brief", "keywords", "outline", "meta_title", "meta_description", "faqs", "internal_links", "image_url", "link", "notes"]);

type Rev = Owned<Revision> & { entity_type: MkEntity; entity_id: string };
type Appr = Owned<ApprovalRow> & { client_id: string };
type Cal = Owned<CalendarSettings> & { id: string; client_id: string };
type Rec = Owned<{ id: string; client_id: string; status: MkStatus; version: number; approved_at: string | null; approved_by: string | null; reviewed_by: string | null; reviewed_at: string | null; created_by: string | null; updated_at: string; created_at: string; claims_to_check?: string[]; title?: string; name?: string; platform?: string | null; kind?: string; job_status?: string }>;

const url = (u: string | null | undefined, required = false) => {
  if (!u || !u.trim()) { if (required) throw new ApiError(422, "A URL is required"); return null; }
  const n = normaliseUrl(u.trim());
  if (!n) throw new ApiError(422, "Enter a valid http(s) URL");
  return n.slice(0, 500);
};
const reviewable = (user: string) => ({ status: "draft" as MkStatus, origin: "user", provider: null, model: null, version: 1, reviewed_by: null, reviewed_at: null,
  approved_by: null, approved_at: null, created_by: user, created_at: now(), updated_at: now() });

function statusPayload() {
  return {
        ai: { configured: false, note: "Backend only" },
        publishing: ["facebook", "instagram", "linkedin", "youtube"].map((p) => ({ platform: p, automated: p !== "youtube", configured: false,
          note: p === "youtube" ? "Uploads are not automated; publish in YouTube Studio and record the URL." : "Runs on the backend with the official API.", missing: ["backend"] })),
        ad_platforms: AD_ADAPTERS, approval_statuses: APPROVAL_STATUSES, content_kinds: [...SOCIAL_KINDS, ...SEO_KINDS], social_kinds: [...SOCIAL_KINDS].sort(), seo_kinds: [...SEO_KINDS].sort(),
        budget_categories: BUDGET_CATEGORIES, budget_labels: BUDGET_LABELS, strategy_sections: STRATEGY_SECTIONS, analytics_unavailable: ANALYTICS_UNAVAILABLE,
        email_marketing: "Planned adapter (Listmonk + a free SMTP tier); not built in this phase.",
      };
    }

export function marketingLocal(h: LocalHelpers) {
  const { ctx, owned, scoped, log } = h;
  const client = async (tenantId: string, cid: string) => owned<Client>("clients", tenantId, cid, "Client");
  const requireClientReview = async (tenantId: string, cid: string) => !!(await scoped<Cal>("mk_calendars", tenantId)).find((c) => c.client_id === cid)?.require_client_review;
  const approval = (r: Rec, entity_type: MkEntity, stage: string, requested_by: string | null, note: string | null = null): Appr => ({
    id: uid(), tenant_id: r.tenant_id, client_id: r.client_id, entity_type, entity_id: r.id, stage, status: "pending", requested_by, reviewer_id: null,
    reviewer_name: null, note, decided_at: null, entity_version: r.version, created_at: now() });
  const pending = async (tenantId: string, e: MkEntity, id: string) =>
    (await scoped<Appr>("mk_approvals", tenantId)).filter((a) => a.entity_type === e && a.entity_id === id && a.status === "pending").sort(byNewest);
  async function revision(r: Rec, e: MkEntity, userId: string, note: string) {
    const snap = Object.fromEntries(FIELDS[e].map((f) => [f, (r as Record<string, unknown>)[f] ?? null]));
    await idb.put<Rev>("mk_revisions", { id: uid(), tenant_id: r.tenant_id, entity_type: e, entity_id: r.id, version: r.version, snapshot: snap, note, user_id: userId, created_at: now() });
  }
  /** After a content edit: new version + revision; anything under review or approved goes back to internal review. */
  async function edited<T extends Rec>(r: T, e: MkEntity, userId: string, note?: string | null): Promise<T> {
    r.version = (r.version || 1) + 1; r.updated_at = now();
    await revision(r, e, userId, note || "Edited");
    if (["approved", "scheduled", "client_review", "internal_review"].includes(r.status)) {
      const was = r.status;
      r.status = "internal_review"; r.approved_by = null; r.approved_at = null;
      for (const a of await pending(r.tenant_id, e, r.id)) await idb.put("mk_approvals", { ...a, status: "cancelled" });
      await idb.put("mk_approvals", approval(r, e, "internal_review", userId, `Edited while ${was.replace(/_/g, " ")}; needs approval again`));
      if (e === "content") (r as unknown as ContentItem).publishing_status = "not_scheduled";
      if (e === "ad_plan") Object.assign(r, { spend_approved: false, spend_approved_by: null, spend_approved_at: null });
    }
    return r;
  }
  const budgetOut = (b: Owned<MarketingBudget>): MarketingBudget => ({ ...strip(b), summary: summarise(b.lines, b.quarterly_overrides) } as MarketingBudget);
  const checkProduct = async (tenantId: string, cid: string, pid?: string | null) => {
    if (!pid) return null;
    const p = await owned<Product>("products", tenantId, pid, "Product");
    if (p.client_id !== cid) throw new ApiError(400, "Product belongs to another client");
    return p.id;
  };
  const checkCampaign = async (tenantId: string, cid: string, id?: string | null) => {
    if (id && (await owned<MarketingCampaign>("mk_campaigns", tenantId, id, "Campaign")).client_id !== cid) throw new ApiError(400, "Campaign belongs to another client");
  };
  const cleanData = (d: Record<string, unknown> = {}) => {
    const bad = Object.keys(d).filter((k) => !DATA_KEYS.has(k));
    if (bad.length) throw new ApiError(422, `Unknown content fields: ${bad.sort().join(", ")}`);
    if (d.image_url && !String(d.image_url).startsWith("https://")) throw new ApiError(422, "image_url must be a public https URL");
    if (d.link) d.link = url(String(d.link));
    return d;
  };

  return {
    async marketingStatus() {
      await ctx();
      return statusPayload();
    },
    async marketingOverview(cid: string) {
      const { tenant } = await ctx(); await client(tenant.id, cid);
      const count = async (s: Store) => (await scoped<Rec>(s, tenant.id)).filter((r) => r.client_id === cid).reduce<Record<string, number>>((a, r) => ({ ...a, [r.status]: (a[r.status] || 0) + 1 }), {});
      const content = (await scoped<ContentItem>("mk_content", tenant.id)).filter((i) => i.client_id === cid);
      const t = now();
      const budgets = (await scoped<MarketingBudget>("mk_budgets", tenant.id)).filter((b) => b.client_id === cid && b.status === "approved").sort((a, b) => (b.approved_at || "").localeCompare(a.approved_at || ""));
      return { strategies: await count("mk_strategies"), content: await count("mk_content"), ad_plans: await count("mk_ad_plans"), accounts: {},
        pending_approvals: (await scoped<Appr>("mk_approvals", tenant.id)).filter((a) => a.client_id === cid && a.status === "pending").length,
        upcoming: content.filter((i) => i.scheduled_at && i.scheduled_at >= t && ["approved", "scheduled"].includes(i.status)).sort((a, b) => a.scheduled_at!.localeCompare(b.scheduled_at!)).slice(0, 5).map(strip) as ContentItem[],
        approved_budget: budgets[0] ? budgetOut(budgets[0]) : null };
    },
    async marketingHistory(e: MkEntity, id: string) {
      const { tenant } = await ctx(); await owned(STORE[e], tenant.id, id, "Item");
      return { revisions: (await scoped<Rev>("mk_revisions", tenant.id)).filter((r) => r.entity_type === e && r.entity_id === id).sort(byNewest).map(({ tenant_id, entity_type, entity_id, ...r }) => { void tenant_id; void entity_type; void entity_id; return r; }),
        approvals: (await scoped<Appr>("mk_approvals", tenant.id)).filter((a) => a.entity_type === e && a.entity_id === id).sort(byNewest).map(strip) as ApprovalRow[] };
    },
    async marketingApprovals(cid: string, status: string | null = "pending") {
      const { tenant } = await ctx(); await client(tenant.id, cid);
      const rows = (await scoped<Appr>("mk_approvals", tenant.id)).filter((a) => a.client_id === cid && (!status || a.status === status)).sort(byNewest);
      const out: ApprovalRow[] = [];
      for (const a of rows) {
        const o = await idb.get<Rec>(STORE[a.entity_type], a.entity_id);
        if (!o || o.tenant_id !== tenant.id) continue;
        out.push({ ...strip(a), title: o.title || o.name || null, entity_status: o.status, platform: o.platform ?? null, kind: o.kind ?? null, claims_to_check: o.claims_to_check || [], current_version: o.version } as ApprovalRow);
      }
      return out;
    },
    async review(e: MkEntity, id: string, b: { action: keyof typeof ACTIONS; note?: string | null; reviewer_name?: string | null }) {
      const { user, tenant } = await ctx();
      const r = await owned<Rec>(STORE[e], tenant.id, id, "Item") as Rec;
      const spec = ACTIONS[b.action];
      if (!spec) throw new ApiError(422, `Unknown action ${b.action}`);
      if (RANK[user.role] < RANK[spec.role]) throw new ApiError(403, `Requires ${spec.role} role or higher`);
      if (!spec.from.includes(r.status)) throw new ApiError(409, `Cannot ${b.action.replace(/_/g, " ")} an item that is ${r.status.replace(/_/g, " ")}`);
      if (e === "content" && ["approve", "client_approve"].includes(b.action) && r.claims_to_check?.length && !(b.note || "").trim())
        throw new ApiError(422, "This draft has claims to fact-check. Add a note saying they were checked (or edit them out) before approving.");
      if (b.action === "client_approve" && !(b.reviewer_name || "").trim()) throw new ApiError(422, "Record who at the client approved it");
      const t = now();
      const pend = (await pending(tenant.id, e, id))[0];
      const next = nextStatus(r.status, b.action, b.action === "approve" && await requireClientReview(tenant.id, r.client_id));
      if (b.action === "submit") {
        if (pend) await idb.put("mk_approvals", { ...pend, status: "cancelled" });
        await idb.put("mk_approvals", approval(r, e, "internal_review", user.id, b.note || null));
      } else {
        const p = pend || approval(r, e, r.status, r.created_by);
        const decided = { approve: "approved", client_approve: "approved", send_to_client: "approved", reject: "rejected", request_changes: "changes_requested" }[b.action];
        await idb.put("mk_approvals", { ...p, reviewer_id: user.id, note: b.note || null, decided_at: t, status: decided, reviewer_name: b.action === "client_approve" ? b.reviewer_name!.trim().slice(0, 200) : p.reviewer_name });
        r.reviewed_by = user.id; r.reviewed_at = t;
        if (next === "client_review") await idb.put("mk_approvals", approval(r, e, "client_review", user.id));
        if (next === "approved") { r.approved_by = user.id; r.approved_at = t; }
      }
      r.status = next; r.updated_at = t;
      await idb.put(STORE[e], r);
      await log(tenant.id, user.id, `marketing.${b.action}`, e, id, `${e.replace("_", " ")} ${b.action.replace(/_/g, " ")}: ${r.title || r.name || ""}`, { client_id: r.client_id });
      return e === "budget" ? budgetOut(r as unknown as Owned<MarketingBudget>) : strip(r);
    },

    // strategies need AI; none can exist in the preview
    async listStrategies(cid: string) { const { tenant } = await ctx(); await client(tenant.id, cid); return []; },
    async createStrategy() { await ctx(); throw new ApiError(409, NO_SERVER_AI); },
    async getStrategy() { await ctx(); throw new ApiError(404, "Strategy not found"); },
    async editStrategy() { await ctx(); throw new ApiError(404, "Strategy not found"); },
    async retryStrategy() { await ctx(); throw new ApiError(409, NO_SERVER_AI); },
    async deleteStrategy() { await ctx("manager"); throw new ApiError(404, "Strategy not found"); },

    async budgetTemplate(m: number, cats?: string[]) {
      await ctx();
      try { const lines = templateLines(m, cats); return { lines, summary: summarise(lines), basis: "Planning template shares; adjust them. Not derived from performance data." }; }
      catch (e) { throw new ApiError(422, (e as Error).message); }
    },
    async listBudgets(cid: string) {
      const { tenant } = await ctx(); await client(tenant.id, cid);
      return (await scoped<MarketingBudget>("mk_budgets", tenant.id)).filter((b) => b.client_id === cid).sort(byNewest).map(budgetOut);
    },
    async createBudget(cid: string, b: { name: string; monthly_total?: number | null; currency?: string; categories?: string[] | null; lines?: BudgetLine[] | null; scenario?: string; notes?: string | null }) {
      const { user, tenant } = await ctx(); const c = await client(tenant.id, cid);
      if (!b.name || b.name.trim().length < 2) throw new ApiError(422, "Name must be at least 2 characters", [{ field: "name", message: "Required" }]);
      let lines: BudgetLine[];
      try {
        if (b.lines?.length) lines = cleanLines(b.lines);
        else {
          const total = b.monthly_total ?? (c.marketing_budget != null ? Number(c.marketing_budget) : null);
          if (total == null) throw new Error("Give a monthly total (the client has no marketing budget on record)");
          lines = scenarioLines(templateLines(total, b.categories), b.scenario || "base");
        }
      } catch (e) { throw new ApiError(422, (e as Error).message); }
      const s = summarise(lines);
      const r: Owned<MarketingBudget> = { ...reviewable(user.id), id: uid(), tenant_id: tenant.id, client_id: cid, name: b.name.trim().slice(0, 200), strategy_id: null,
        scenario: (b.lines?.length ? "custom" : b.scenario || "base") as MarketingBudget["scenario"], currency: (b.currency || c.budget_currency || "INR").toUpperCase(),
        monthly_total: s.monthly_total, lines, quarterly_overrides: {}, notes: b.notes || null, summary: s };
      await idb.put("mk_budgets", r);
      await log(tenant.id, user.id, "marketing.budget_created", "budget", r.id, `Budget created: ${r.name}`, { client_id: cid });
      return budgetOut(r);
    },
    async editBudget(id: string, b: { name?: string; currency?: string; lines?: BudgetLine[]; quarterly_overrides?: Record<string, number>; notes?: string | null }) {
      const { user, tenant } = await ctx(); const r = await owned<MarketingBudget>("mk_budgets", tenant.id, id, "Budget");
      try {
        if (b.lines) { r.lines = cleanLines(b.lines); r.scenario = "custom"; }
        if (b.quarterly_overrides) {
          for (const [k, v] of Object.entries(b.quarterly_overrides)) { if (!BUDGET_CATEGORIES.includes(k)) throw new Error(`Unknown category: ${k}`); if (v < 0) throw new Error("Amounts cannot be negative"); }
          r.quarterly_overrides = b.quarterly_overrides;
        }
      } catch (e) { throw new ApiError(422, (e as Error).message); }
      if (b.name) r.name = b.name.trim().slice(0, 200);
      if (b.currency) r.currency = b.currency.toUpperCase();
      if (b.notes !== undefined) r.notes = b.notes;
      r.monthly_total = summarise(r.lines).monthly_total;
      await idb.put("mk_budgets", await edited(r as unknown as Rec, "budget", user.id));
      return budgetOut(r);
    },
    async budgetScenario(id: string, scenario: "base" | "conservative" | "growth") {
      const { user, tenant } = await ctx(); const src = await owned<MarketingBudget>("mk_budgets", tenant.id, id, "Budget");
      if (!(scenario in SCENARIOS)) throw new ApiError(422, "Unknown scenario");
      const base = src.scenario in SCENARIOS && src.scenario !== "base" ? src.lines.map((l) => ({ ...l, amount: l.amount / SCENARIOS[src.scenario] })) : src.lines;
      const lines = scenarioLines(base, scenario);
      const r: Owned<MarketingBudget> = { ...reviewable(user.id), id: uid(), tenant_id: tenant.id, client_id: src.client_id, name: `${src.name.replace(/ \((conservative|growth|base)\)$/, "")} (${scenario})`.slice(0, 200),
        strategy_id: src.strategy_id, scenario, currency: src.currency, lines, monthly_total: summarise(lines).monthly_total, quarterly_overrides: {}, notes: src.notes, summary: summarise(lines) };
      await idb.put("mk_budgets", r);
      return budgetOut(r);
    },
    async deleteBudget(id: string) { const { tenant } = await ctx("manager"); await owned("mk_budgets", tenant.id, id, "Budget"); await idb.del("mk_budgets", id); },

    async listMarketingCampaigns(cid: string) {
      const { tenant } = await ctx(); await client(tenant.id, cid);
      return (await scoped<MarketingCampaign>("mk_campaigns", tenant.id)).filter((c) => c.client_id === cid).sort(byNewest).map(strip) as MarketingCampaign[];
    },
    async createMarketingCampaign(cid: string, b: Partial<MarketingCampaign> & { name: string }) {
      const { user, tenant } = await ctx(); await client(tenant.id, cid);
      if (!b.name || b.name.trim().length < 2) throw new ApiError(422, "Name must be at least 2 characters", [{ field: "name", message: "Required" }]);
      if (b.start_date && b.end_date && b.end_date < b.start_date) throw new ApiError(422, "End date is before the start date");
      const c: Owned<MarketingCampaign> = { id: uid(), tenant_id: tenant.id, client_id: cid, name: b.name.trim(), objective: b.objective || null, strategy_id: null, budget_id: b.budget_id || null,
        start_date: b.start_date || null, end_date: b.end_date || null, status: b.status || "planned", created_at: now() };
      await idb.put("mk_campaigns", c);
      await log(tenant.id, user.id, "marketing.campaign_created", "campaign", c.id, `Campaign created: ${c.name}`, { client_id: cid });
      return strip(c) as MarketingCampaign;
    },
    async editMarketingCampaign(id: string, b: Partial<MarketingCampaign>) {
      const { tenant } = await ctx(); const c = await owned<MarketingCampaign>("mk_campaigns", tenant.id, id, "Campaign");
      const n = { ...c, ...b, tenant_id: tenant.id, id };
      if (n.start_date && n.end_date && n.end_date < n.start_date) throw new ApiError(422, "End date is before the start date");
      await idb.put("mk_campaigns", n); return strip(n) as MarketingCampaign;
    },
    async deleteMarketingCampaign(id: string) { const { tenant } = await ctx("manager"); await owned("mk_campaigns", tenant.id, id, "Campaign"); await idb.del("mk_campaigns", id); },

    async generateContent() { await ctx(); throw new ApiError(409, NO_SERVER_AI); },
    async addContent(cid: string, b: { studio?: "social" | "seo"; kind: string; platform?: string | null; title: string; body?: string | null; data?: Record<string, unknown>; product_id?: string | null; campaign_id?: string | null; scheduled_at?: string | null; assigned_to?: string | null }) {
      const { user, tenant } = await ctx(); await client(tenant.id, cid);
      const studio = b.studio || "social";
      const kinds = studio === "social" ? SOCIAL_KINDS : SEO_KINDS;
      if (!kinds.includes(b.kind)) throw new ApiError(422, `kind must be one of ${[...kinds].sort().join(", ")}`);
      if (studio === "social" && !(SOCIAL_PLATFORMS as readonly string[]).includes(b.platform || "")) throw new ApiError(422, "Choose a platform");
      if (!b.title || b.title.trim().length < 2) throw new ApiError(422, "Title must be at least 2 characters", [{ field: "title", message: "Required" }]);
      const platform = studio === "social" ? b.platform! : "website";
      if ((b.body || "").length > LIMITS[platform]) throw new ApiError(422, `${platform} allows ${LIMITS[platform]} characters`);
      if (guaranteeIssues(b.title, b.body).length) throw new ApiError(422, "Remove outcome guarantees; content cannot promise results");
      await checkProduct(tenant.id, cid, b.product_id); await checkCampaign(tenant.id, cid, b.campaign_id);
      const it: Owned<ContentItem> = { ...reviewable(user.id), id: uid(), tenant_id: tenant.id, client_id: cid, campaign_id: b.campaign_id || null, product_id: b.product_id || null, persona_id: null,
        studio, kind: b.kind, platform, title: b.title.trim().slice(0, 300), body: b.body || null, data: cleanData({ ...(b.data || {}) }), claims_to_check: detectClaims(`${b.title}. ${b.body || ""}`),
        asset_ids: [], scheduled_at: b.scheduled_at || null, published_at: null, publishing_status: "not_scheduled", assigned_to: b.assigned_to || null };
      await idb.put("mk_content", it);
      return strip(it) as ContentItem;
    },
    async listContent(cid: string, q: { studio?: string; status?: string; platform?: string; campaign_id?: string } = {}) {
      const { tenant } = await ctx(); await client(tenant.id, cid);
      return (await scoped<ContentItem>("mk_content", tenant.id)).filter((i) => i.client_id === cid && (!q.studio || i.studio === q.studio) && (!q.status || i.status === q.status)
        && (!q.platform || i.platform === q.platform) && (!q.campaign_id || i.campaign_id === q.campaign_id)).sort(byNewest).map(strip) as ContentItem[];
    },
    async getContent(id: string) { const { tenant } = await ctx(); return strip(await owned<ContentItem>("mk_content", tenant.id, id, "Content")) as ContentItem; },
    async editContent(id: string, b: Record<string, unknown> & { note?: string | null; clear_schedule?: boolean }) {
      const { user, tenant } = await ctx(); const it = await owned<ContentItem>("mk_content", tenant.id, id, "Content");
      if (it.status === "published") throw new ApiError(409, "Published content cannot be edited; duplicate it instead");
      const { note, clear_schedule, ...ch } = b;
      if ("asset_ids" in ch) {
        const ids = (ch.asset_ids as string[]) || [];
        const assets = (await scoped<BrandAsset>("mk_assets", tenant.id)).filter((a) => ids.includes(a.id));
        if (assets.length !== new Set(ids).size || assets.some((a) => a.client_id !== it.client_id)) throw new ApiError(400, "Some assets were not found for this client");
        if (assets.some((a) => !a.approved)) throw new ApiError(409, "Only approved brand assets can be attached");
      }
      if ("data" in ch) ch.data = cleanData({ ...((ch.data as Record<string, unknown>) || {}) });
      if (guaranteeIssues(ch.title as string, ch.body as string).length) throw new ApiError(422, "Remove outcome guarantees; content cannot promise results");
      if ("campaign_id" in ch) await checkCampaign(tenant.id, it.client_id, ch.campaign_id as string);
      const touched = ["title", "body", "data", "kind", "platform", "claims_to_check", "asset_ids"].some((k) => k in ch);
      for (const k of ["title", "body", "data", "kind", "platform", "claims_to_check", "asset_ids", "assigned_to", "campaign_id"]) if (k in ch) (it as unknown as Record<string, unknown>)[k] = ch[k];
      if (clear_schedule) it.scheduled_at = null; else if ("scheduled_at" in ch) it.scheduled_at = (ch.scheduled_at as string) || null;
      it.updated_at = now();
      if (touched) {
        if ("body" in ch || "title" in ch) it.claims_to_check = Array.from(new Set([...((ch.claims_to_check as string[]) || []), ...detectClaims(`${it.title}. ${it.body || ""}`)]));
        await edited(it as unknown as Rec, "content", user.id, note);
      }
      await idb.put("mk_content", it);
      return strip(it) as ContentItem;
    },
    async deleteContent(id: string) {
      const { user, tenant } = await ctx("manager"); const it = await owned<ContentItem>("mk_content", tenant.id, id, "Content");
      await idb.del("mk_content", id);
      await log(tenant.id, user.id, "marketing.content_deleted", "content", id, `Content deleted: ${it.title}`, { client_id: it.client_id });
    },

    async calendar(cid: string, start: string, end: string) {
      const { tenant } = await ctx(); await client(tenant.id, cid);
      if (end <= start) throw new ApiError(422, "Choose a range of up to 400 days");
      const cal = (await scoped<Cal>("mk_calendars", tenant.id)).find((c) => c.client_id === cid);
      const inR = (d: string | null) => !!d && d >= start && d <= end;
      return { settings: { timezone: cal?.timezone || "Asia/Kolkata", require_client_review: !!cal?.require_client_review, default_reviewer_id: cal?.default_reviewer_id || null },
        items: (await scoped<ContentItem>("mk_content", tenant.id)).filter((i) => i.client_id === cid && (inR(i.scheduled_at) || inR(i.published_at)))
          .sort((a, b) => (a.scheduled_at || a.published_at || "").localeCompare(b.scheduled_at || b.published_at || "")).map(strip) as ContentItem[] };
    },
    async saveCalendarSettings(cid: string, b: CalendarSettings) {
      const { tenant } = await ctx("manager"); await client(tenant.id, cid);
      try { new Intl.DateTimeFormat("en", { timeZone: b.timezone }); } catch { throw new ApiError(422, "Unknown time zone"); }
      const cur = (await scoped<Cal>("mk_calendars", tenant.id)).find((c) => c.client_id === cid);
      const next: Cal = { id: cur?.id || uid(), tenant_id: tenant.id, client_id: cid, timezone: b.timezone, require_client_review: !!b.require_client_review, default_reviewer_id: b.default_reviewer_id || null };
      await idb.put("mk_calendars", next);
      return { timezone: next.timezone, require_client_review: next.require_client_review, default_reviewer_id: next.default_reviewer_id };
    },

    async listAssets(cid: string, kind?: string) {
      const { tenant } = await ctx(); await client(tenant.id, cid);
      return (await scoped<BrandAsset>("mk_assets", tenant.id)).filter((a) => a.client_id === cid && (!kind || a.kind === kind)).sort(byNewest).map(strip) as BrandAsset[];
    },
    async addAsset(cid: string, b: { kind: string; name: string; document_id?: string | null; value?: string | null; product_id?: string | null; tags?: string[]; notes?: string | null }) {
      const { tenant, user } = await ctx(); await client(tenant.id, cid);
      if (!b.name || b.name.trim().length < 2) throw new ApiError(422, "Name must be at least 2 characters", [{ field: "name", message: "Required" }]);
      if (b.document_id && (await owned<DocumentMeta>("documents", tenant.id, b.document_id, "Document")).client_id !== cid) throw new ApiError(400, "Document belongs to another client");
      let value: string | null;
      try { value = validateAsset(b.kind, b.value, !!b.document_id); } catch (e) { throw new ApiError(422, (e as Error).message); }
      const a: Owned<BrandAsset> = { id: uid(), tenant_id: tenant.id, client_id: cid, kind: b.kind, name: b.name.trim().slice(0, 200), document_id: b.document_id || null, value,
        product_id: await checkProduct(tenant.id, cid, b.product_id), tags: (b.tags || []).map((t) => t.trim().slice(0, 40)).filter(Boolean), notes: b.notes || null,
        approved: false, approved_by: null, approved_at: null, created_at: now() };
      await idb.put("mk_assets", a);
      await log(tenant.id, user.id, "marketing.asset_added", "asset", a.id, `Brand asset added: ${a.name}`, { client_id: cid });
      return strip(a) as BrandAsset;
    },
    async approveAsset(id: string, approved: boolean) {
      const { user, tenant } = await ctx("manager"); const a = await owned<BrandAsset>("mk_assets", tenant.id, id, "Asset");
      Object.assign(a, { approved, approved_by: approved ? user.id : null, approved_at: approved ? now() : null });
      await idb.put("mk_assets", a); return strip(a) as BrandAsset;
    },
    async deleteAsset(id: string) { const { tenant } = await ctx("manager"); await owned("mk_assets", tenant.id, id, "Asset"); await idb.del("mk_assets", id); },

    async listAdPlans(cid: string) {
      const { tenant } = await ctx(); await client(tenant.id, cid);
      return (await scoped<AdPlan>("mk_ad_plans", tenant.id)).filter((a) => a.client_id === cid).sort(byNewest).map(strip) as AdPlan[];
    },
    async generateAdPlan() { await ctx(); throw new ApiError(409, NO_SERVER_AI); },
    async addAdPlan(cid: string, b: Partial<AdPlan> & { name: string; platform: AdPlan["platform"] }) {
      const { user, tenant } = await ctx(); await client(tenant.id, cid);
      if (!["meta", "google", "linkedin"].includes(b.platform)) throw new ApiError(422, "Choose Meta, Google or LinkedIn");
      if (!b.name || b.name.trim().length < 2) throw new ApiError(422, "Name must be at least 2 characters", [{ field: "name", message: "Required" }]);
      const lim = AD_LIMITS[b.platform];
      if ((b.headlines || []).some((x) => x.length > lim.headline)) throw new ApiError(422, `Headlines are limited to ${lim.headline} characters on ${b.platform}`);
      if (guaranteeIssues(...(b.headlines || []), ...(b.ad_copy || [])).length) throw new ApiError(422, "Remove outcome guarantees from the ad copy");
      const ad: Owned<AdPlan> = { ...reviewable(user.id), id: uid(), tenant_id: tenant.id, client_id: cid, campaign_id: b.campaign_id || null, platform: b.platform, name: b.name.trim(),
        objective: b.objective || null, audience: b.audience || {}, geography: b.geography || [], creative_brief: b.creative_brief || null, headlines: b.headlines || [], ad_copy: b.ad_copy || [],
        landing_page: url(b.landing_page), currency: (b.currency || "INR").toUpperCase(), daily_budget: b.daily_budget ?? null, total_budget: b.total_budget ?? null, bidding: b.bidding || null,
        conversion_tracking: b.conversion_tracking || null, ab_tests: b.ab_tests || [], targets: b.targets || {}, claims_to_check: detectClaims([...(b.headlines || []), ...(b.ad_copy || [])].join(" ")),
        spend_approved: false, spend_cap: null, spend_approved_by: null, spend_approved_at: null };
      await idb.put("mk_ad_plans", ad);
      return strip(ad) as AdPlan;
    },
    async editAdPlan(id: string, b: Partial<AdPlan>) {
      const { user, tenant } = await ctx(); const ad = await owned<AdPlan>("mk_ad_plans", tenant.id, id, "Ad plan");
      const keys = ["name", "objective", "audience", "geography", "creative_brief", "headlines", "ad_copy", "landing_page", "daily_budget", "total_budget", "bidding", "conversion_tracking", "ab_tests", "targets"] as const;
      for (const k of keys) if (k in b) (ad as unknown as Record<string, unknown>)[k] = k === "landing_page" ? url(b.landing_page) : b[k];
      if (guaranteeIssues(...ad.headlines, ...ad.ad_copy).length) throw new ApiError(422, "Remove outcome guarantees from the ad copy");
      await idb.put("mk_ad_plans", await edited(ad as unknown as Rec, "ad_plan", user.id));
      return strip(ad) as AdPlan;
    },
    async spendApproval(id: string, b: { approved: boolean; spend_cap?: number | null; note?: string | null }) {
      const { user, tenant } = await ctx("admin"); const ad = await owned<AdPlan>("mk_ad_plans", tenant.id, id, "Ad plan");
      if (b.approved) {
        if (ad.status !== "approved") throw new ApiError(409, "Approve the ad plan before approving spend");
        if (!b.spend_cap || b.spend_cap <= 0) throw new ApiError(422, "Set a spend cap");
        if (ad.total_budget != null && b.spend_cap > ad.total_budget) throw new ApiError(422, "The spend cap cannot exceed the plan's total budget");
      }
      Object.assign(ad, { spend_approved: b.approved, spend_cap: b.approved ? b.spend_cap : null, spend_approved_by: b.approved ? user.id : null, spend_approved_at: b.approved ? now() : null });
      await idb.put("mk_ad_plans", ad);
      await idb.put<Appr>("mk_approvals", { id: uid(), tenant_id: tenant.id, client_id: ad.client_id, entity_type: "ad_plan", entity_id: ad.id, stage: "spend", status: b.approved ? "approved" : "rejected",
        requested_by: user.id, reviewer_id: user.id, reviewer_name: null, note: b.note || null, decided_at: now(), entity_version: ad.version, created_at: now() });
      await log(tenant.id, user.id, b.approved ? "marketing.spend_approved" : "marketing.spend_withdrawn", "ad_plan", ad.id, `Ad spend ${b.approved ? `approved up to ${b.spend_cap} ${ad.currency}` : "withdrawn"} for ${ad.name}`, { client_id: ad.client_id });
      return { ...(strip(ad) as AdPlan), note: AD_ADAPTERS[ad.platform] };
    },
    async deleteAdPlan(id: string) { const { tenant } = await ctx("manager"); await owned("mk_ad_plans", tenant.id, id, "Ad plan"); await idb.del("mk_ad_plans", id); },

    async listSocialAccounts(cid: string) {
      const { tenant } = await ctx(); await client(tenant.id, cid);
      return { accounts: [], platforms: statusPayload().publishing };
    },
    async connectSocial() { await ctx("manager"); throw new ApiError(409, NO_SERVER_SOCIAL); },
    async disconnectSocial() { await ctx("manager"); throw new ApiError(404, "Account not found"); },
    async publishContent() { await ctx("manager"); throw new ApiError(409, NO_SERVER_SOCIAL); },
    async markPublished(id: string, b: { url: string; published_at?: string | null }) {
      const { user, tenant } = await ctx("manager"); const it = await owned<ContentItem>("mk_content", tenant.id, id, "Content");
      if (!["approved", "scheduled"].includes(it.status) || !it.approved_at) throw new ApiError(409, "Only approved content can be marked published");
      const u = url(b.url, true)!; const t = b.published_at || now();
      await idb.put<Owned<PublishingJob>>("mk_jobs", { id: uid(), tenant_id: tenant.id, client_id: it.client_id, content_item_id: it.id, social_account_id: null, platform: it.platform || "website",
        status: "published", scheduled_at: null, attempts: 0, error: null, external_post_id: null, external_url: u, content_version: it.version, requested_by: user.id, published_at: t, created_at: now(), updated_at: now() });
      Object.assign(it, { status: "published", publishing_status: "manual", published_at: t, data: { ...it.data, external_url: u }, updated_at: now() });
      await idb.put("mk_content", it);
      await log(tenant.id, user.id, "marketing.marked_published", "content", it.id, `'${it.title}' recorded as published manually`, { client_id: it.client_id, url: u });
      return strip(it) as ContentItem;
    },
    async publishingJobs(cid: string, status?: string) {
      const { tenant } = await ctx(); await client(tenant.id, cid);
      const titles = Object.fromEntries((await scoped<ContentItem>("mk_content", tenant.id)).map((i) => [i.id, i.title]));
      return (await scoped<PublishingJob>("mk_jobs", tenant.id)).filter((j) => j.client_id === cid && (!status || j.status === status)).sort(byNewest).map((j) => ({ ...strip(j), title: titles[j.content_item_id] ?? null })) as PublishingJob[];
    },
    async cancelPublishingJob() { await ctx("manager"); throw new ApiError(409, "Only queued jobs can be cancelled; the preview queues none."); },
    async retryPublishingJob() { await ctx("manager"); throw new ApiError(409, NO_SERVER_SOCIAL); },
    async refreshAnalytics(cid: string) { const { tenant } = await ctx(); await client(tenant.id, cid); return { posts_updated: 0, errors: [NO_SERVER_SOCIAL], not_available: [], notes: ANALYTICS_UNAVAILABLE }; },
    async marketingAnalytics(cid: string) { const { tenant } = await ctx(); await client(tenant.id, cid); return { platform: [], calculated: [], not_available: ANALYTICS_UNAVAILABLE }; },

    async createMarketingReport(cid: string, b: { start: string; end: string; title?: string | null }) {
      const { user, tenant } = await ctx(); const c = await client(tenant.id, cid);
      if (b.end < b.start) throw new ApiError(422, "End date is before the start date");
      const items = (await scoped<ContentItem>("mk_content", tenant.id)).filter((i) => i.client_id === cid);
      const by: Record<string, number> = {}; items.forEach((i) => { by[i.status] = (by[i.status] || 0) + 1; });
      const inP = (d: string | null) => !!d && d.slice(0, 10) >= b.start && d.slice(0, 10) <= b.end;
      const published = items.filter((i) => i.status === "published" && inP(i.published_at)).sort((x, y) => x.published_at!.localeCompare(y.published_at!));
      const scheduled = items.filter((i) => i.status === "scheduled" && i.scheduled_at);
      const budget = (await scoped<MarketingBudget>("mk_budgets", tenant.id)).filter((x) => x.client_id === cid && x.status === "approved").sort((x, y) => (y.approved_at || "").localeCompare(x.approved_at || ""))[0];
      const ads = (await scoped<AdPlan>("mk_ad_plans", tenant.id)).filter((a) => a.client_id === cid);
      const f = (n: number) => n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      const L = [`# Marketing report — ${c.company_name}`, `Period: ${b.start} to ${b.end}`, "",
        "Everything below comes from GrowthCognix records and connected platform APIs. Values that are not connected are shown as —.", "",
        "## Strategy", "No approved strategy yet.", "", "## Budget"];
      if (budget) {
        const s = summarise(budget.lines, budget.quarterly_overrides);
        L.push(`Approved budget: ${budget.name}, ${f(s.monthly_total)} ${budget.currency} per month (${(Object.keys(COST_LABEL) as (keyof typeof COST_LABEL)[]).map((k) => `${COST_LABEL[k].toLowerCase()} ${f(s.by_cost_kind[k])}`).join(", ")}).`);
        Object.entries(s.by_category).forEach(([k, v]) => L.push(`- ${BUDGET_LABELS[k] || k}: ${f(v)}`));
      } else L.push("No approved budget yet.");
      L.push("", "## Content", "Status | Items", "--- | ---", ...Object.keys(by).sort().map((k) => `${k.replace(/_/g, " ")} | ${by[k]}`), "",
        `Published in this period: ${published.length}`, ...published.map((i) => `- ${i.published_at!.slice(0, 10)} ${i.platform}: ${i.title}${i.data?.external_url ? ` (${i.data.external_url})` : ""}`),
        `Scheduled: ${scheduled.length}`, "Publishing failures in this period: 0", "",
        "## Platform metrics (reported by the platform)", "— No connected platform has reported metrics yet.", "", "## Calculated by GrowthCognix", "—", "",
        "## Not available", ...Object.values(ANALYTICS_UNAVAILABLE).map((v) => `- ${v}`), "", "## Ad plans (plans only; nothing is launched from GrowthCognix)",
        ...(ads.length ? ads.map((a) => `- ${a.platform}: ${a.name} — ${a.status.replace(/_/g, " ")}; spend ${a.spend_approved ? `approved up to ${f(a.spend_cap || 0)} ${a.currency}` : "not approved"}`) : ["None."]));
      const r: Owned<MarketingReport> = { id: uid(), tenant_id: tenant.id, client_id: cid, title: b.title || `Marketing report ${b.start} – ${b.end}`, period_start: b.start, period_end: b.end,
        markdown: L.join("\n") + "\n", data: { content_by_status: by, published: published.length, scheduled: scheduled.length, failed: 0, metrics: 0, ad_plans: ads.length }, created_at: now() };
      await idb.put("mk_reports", r);
      await log(tenant.id, user.id, "marketing.report_created", "report", r.id, `Report created: ${r.title}`, { client_id: cid });
      return strip(r) as MarketingReport;
    },
    async listMarketingReports(cid: string) {
      const { tenant } = await ctx(); await client(tenant.id, cid);
      return (await scoped<MarketingReport>("mk_reports", tenant.id)).filter((r) => r.client_id === cid).sort(byNewest).map(({ markdown, ...r }) => { void markdown; return strip(r); }) as MarketingReport[];
    },
    async marketingReportMarkdown(id: string) { const { tenant } = await ctx(); return (await owned<MarketingReport>("mk_reports", tenant.id, id, "Report")).markdown || ""; },
    async deleteMarketingReport(id: string) { const { tenant } = await ctx("manager"); await owned("mk_reports", tenant.id, id, "Report"); await idb.del("mk_reports", id); },
  };
}
