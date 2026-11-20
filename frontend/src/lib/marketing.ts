/**
 * Phase 5 rules shared by the UI and the browser-preview driver. Ports of backend/app/services/marketing/*
 * (budget_planner, common.detect_claims/guarantee_issues, approval_service.ACTIONS, brand_asset_manager.validate).
 * tests/marketing.test.ts checks these against values produced by the Python code; keep them in step.
 */
import type { BudgetLine, BudgetSummary, CostKind, MkStatus, ReviewAction, Role } from "./types";

export const APPROVAL_STATUSES: MkStatus[] = ["draft", "ai_generated", "internal_review", "client_review", "approved", "scheduled", "published", "rejected", "failed"];
export const STATUS_LABEL: Record<MkStatus, string> = {
  draft: "Draft", ai_generated: "AI generated", internal_review: "Internal review", client_review: "Client review", approved: "Approved",
  scheduled: "Scheduled", published: "Published", rejected: "Rejected", failed: "Failed",
};
export const STATUS_TONE: Record<MkStatus, "slate" | "blue" | "green" | "amber" | "red" | "violet"> = {
  draft: "slate", ai_generated: "violet", internal_review: "amber", client_review: "amber", approved: "green", scheduled: "blue", published: "green", rejected: "red", failed: "red",
};

export const SOCIAL_PLATFORMS = ["instagram", "facebook", "linkedin", "youtube", "youtube_shorts"] as const;
export const PLATFORM_LABEL: Record<string, string> = {
  instagram: "Instagram", facebook: "Facebook", linkedin: "LinkedIn", youtube: "YouTube", youtube_shorts: "YouTube Shorts", website: "Website",
  meta: "Meta (Facebook & Instagram)", google: "Google Ads",
};
export const SOCIAL_KINDS = ["single_image_post", "carousel", "reel_script", "short_video_script", "long_video_script", "caption", "product_announcement",
  "educational", "case_study", "promotional", "seasonal"];
export const SEO_KINDS = ["keyword_cluster", "topic_map", "article_outline", "blog_article", "product_description", "industry_landing_page",
  "location_landing_page", "meta_tags", "faq", "internal_links"];
export const KIND_LABEL = (k: string) => ({ seasonal: "Festival / seasonal", meta_tags: "Meta title & description", faq: "FAQs" } as Record<string, string>)[k]
  || k.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
/** Published caption/body limits (characters). Instagram also caps hashtags at 30. */
export const LIMITS: Record<string, number> = { instagram: 2200, facebook: 63206, linkedin: 3000, youtube: 5000, youtube_shorts: 5000, website: 60000 };
export const AD_LIMITS: Record<string, { headline: number; copy: number }> = { google: { headline: 30, copy: 90 }, meta: { headline: 40, copy: 125 }, linkedin: { headline: 70, copy: 150 } };

// ---------------------------------------------------------------- budget planner (deterministic)
export const BUDGET_CATEGORIES = ["seo", "social_media", "content_production", "paid_search", "social_ads", "video_production", "email_marketing", "agency_services"];
export const COST_KINDS: CostKind[] = ["ad_spend", "agency_fee", "production"];
export const COST_LABEL: Record<CostKind, string> = { ad_spend: "Proposed ad spend", agency_fee: "Agency fees", production: "Production costs" };
export const TEMPLATE: Record<string, [number, CostKind]> = {
  seo: [0.15, "agency_fee"], social_media: [0.15, "agency_fee"], content_production: [0.12, "production"], paid_search: [0.2, "ad_spend"],
  social_ads: [0.15, "ad_spend"], video_production: [0.08, "production"], email_marketing: [0.05, "agency_fee"], agency_services: [0.1, "agency_fee"],
};
export const SCENARIOS: Record<string, number> = { base: 1, conservative: 0.7, growth: 1.4 };
export const BUDGET_LABELS: Record<string, string> = {
  seo: "SEO", social_media: "Social media management", content_production: "Content production", paid_search: "Paid search (Google Ads)",
  social_ads: "Social ads (Meta / LinkedIn)", video_production: "Video production", email_marketing: "Email marketing", agency_services: "Agency services & reporting",
};
export const r2 = (x: number) => Math.round((x + Number.EPSILON) * 100) / 100;

export function templateLines(monthlyTotal: number, categories?: string[] | null): BudgetLine[] {
  const cats = (categories && categories.length ? categories : BUDGET_CATEGORIES).filter((c) => c in TEMPLATE);
  if (!cats.length) throw new Error("Choose at least one budget category");
  const share = cats.reduce((a, c) => a + TEMPLATE[c][0], 0);
  let left = r2(monthlyTotal);
  return cats.map((c, i) => {
    const amt = i < cats.length - 1 ? r2((monthlyTotal * TEMPLATE[c][0]) / share) : r2(left);
    left -= amt;
    return { category: c, cost_kind: TEMPLATE[c][1], amount: amt, note: "Template share; adjust" };
  });
}

export function cleanLines(lines: BudgetLine[]): BudgetLine[] {
  if (lines.length > 40) throw new Error("Too many lines");
  return lines.map((l) => {
    if (!BUDGET_CATEGORIES.includes(l.category)) throw new Error(`Unknown category: ${l.category}`);
    if (!COST_KINDS.includes(l.cost_kind)) throw new Error(`cost_kind must be one of ${COST_KINDS.join(", ")}`);
    const amt = Number(l.amount ?? 0);
    if (Number.isNaN(amt)) throw new Error(`Amount for ${l.category} must be a number`);
    if (amt < 0) throw new Error("Amounts cannot be negative");
    return { category: l.category, cost_kind: l.cost_kind, amount: r2(amt), note: (l.note || "").slice(0, 300) || null };
  });
}

export const scenarioLines = (lines: BudgetLine[], scenario: string) =>
  SCENARIOS[scenario] === undefined ? lines : lines.map((l) => ({ ...l, amount: r2(l.amount * SCENARIOS[scenario]) }));

export function summarise(lines: BudgetLine[], overrides?: Record<string, number> | null): BudgetSummary {
  const monthly = r2(lines.reduce((a, l) => a + l.amount, 0));
  const by_cost_kind = Object.fromEntries(COST_KINDS.map((k) => [k, r2(lines.filter((l) => l.cost_kind === k).reduce((a, l) => a + l.amount, 0))])) as Record<CostKind, number>;
  const by_category: Record<string, number> = {};
  lines.forEach((l) => { by_category[l.category] = r2((by_category[l.category] || 0) + l.amount); });
  const q = Object.fromEntries(Object.entries(by_category).map(([c, v]) => [c, r2(Number(overrides?.[c] ?? v * 3))]));
  return { monthly_total: monthly, quarterly_total: r2(Object.values(q).reduce((a, b) => a + b, 0)), by_cost_kind, by_category, quarterly_by_category: q,
    share: Object.fromEntries(Object.entries(by_category).map(([c, v]) => [c, monthly ? Math.round((1000 * v) / monthly) / 10 : 0])) };
}

// ---------------------------------------------------------------- claims & promises
const GUARANTEE = /\b(guarantee[sd]?|guaranteed|assured (?:results|leads|roi|returns|sales)|100% (?:results|success)|(?:will|shall) (?:definitely|surely) (?:get|generate|double|triple)|risk[- ]free returns?)\b/gi;
const CLAIM_PATTERNS: [string, RegExp][] = [
  ["certification", /\b(ISO\s?\d{3,5}|CE\b|BIS\b|ISI\b|FDA|GMP|HACCP|FSSAI|NABL|UL\b|IATF|certified|certification)/i],
  ["award", /\b(award(?:-winning|ed)?|winner|ranked|best[- ]in[- ]class|no\.?\s?1|number one|#1|leading|market leader)\b/i],
  ["number", /\b\d[\d,.]*\s?(%|percent|years?|customers|clients|units|tonnes?|tons?|kg|lph|litres?|countries|installations|\+)/i],
  ["price", /(₹|rs\.?\s?\d|inr\s?\d|\$\s?\d|usd\s?\d|price|discount|% off|offer)/i],
  ["endorsement", /\b(trusted by|endorsed|recommended by|approved by|partner of|used by)\b/i],
  ["comparison", /\b(better than|cheaper than|faster than|unlike (?:other|competitors)|only (?:company|supplier|manufacturer))\b/i],
];
export const guaranteeIssues = (...texts: (string | null | undefined)[]) => texts.flatMap((t) => Array.from((t || "").matchAll(GUARANTEE), (m) => m[0]));
/** Sentences with certifications, awards, numbers, prices, endorsements or comparisons: a person must check each before publishing. */
export function detectClaims(text: string | null | undefined): string[] {
  const out: string[] = [];
  for (const sent of (text || "").split(/(?<=[.!?])\s+|\n+/)) {
    const s = sent.trim();
    if (s.length < 6) continue;
    const kinds = CLAIM_PATTERNS.filter(([, rx]) => rx.test(s)).map(([k]) => k);
    if (kinds.length) out.push(`[${kinds.join("/")}] ${s.slice(0, 280)}`);
  }
  return out.slice(0, 20);
}

// ---------------------------------------------------------------- approval workflow
const RANK: Record<Role, number> = { staff: 0, manager: 1, admin: 2, owner: 3 };
export const ACTIONS: Record<ReviewAction, { from: MkStatus[]; role: Role; label: string }> = {
  submit: { from: ["draft", "ai_generated", "rejected", "failed"], role: "staff", label: "Submit for review" },
  approve: { from: ["internal_review"], role: "manager", label: "Approve" },
  send_to_client: { from: ["internal_review"], role: "manager", label: "Send to client" },
  client_approve: { from: ["client_review"], role: "manager", label: "Record client approval" },
  reject: { from: ["internal_review", "client_review"], role: "manager", label: "Reject" },
  request_changes: { from: ["internal_review", "client_review"], role: "manager", label: "Request changes" },
};
export const allowedActions = (status: MkStatus, role: Role) =>
  (Object.keys(ACTIONS) as ReviewAction[]).filter((a) => ACTIONS[a].from.includes(status) && RANK[role] >= RANK[ACTIONS[a].role]);
/** Where an action leads (approve goes to client review when the client's calendar requires it). */
export function nextStatus(status: MkStatus, action: ReviewAction, requireClientReview = false): MkStatus {
  if (!ACTIONS[action].from.includes(status)) throw new Error(`Cannot ${action.replace(/_/g, " ")} an item that is ${status.replace(/_/g, " ")}`);
  return { submit: "internal_review", approve: requireClientReview ? "client_review" : "approved", send_to_client: "client_review",
    client_approve: "approved", reject: "rejected", request_changes: "draft" }[action] as MkStatus;
}
/** Editing content of an item under review or approved sends it back to internal review. */
export const statusAfterEdit = (s: MkStatus): MkStatus => (["approved", "scheduled", "client_review", "internal_review"].includes(s) ? "internal_review" : s);

// ---------------------------------------------------------------- brand assets
export const ASSET_KINDS = ["logo", "colour", "font", "product_image", "guideline", "template", "creative"];
const FILE_KINDS = new Set(["logo", "product_image", "guideline", "template", "creative"]);
export function validateAsset(kind: string, value: string | null | undefined, hasFile: boolean): string | null {
  if (!ASSET_KINDS.includes(kind)) throw new Error(`Asset type must be one of ${ASSET_KINDS.join(", ")}`);
  const v = (value || "").trim() || null;
  if (kind === "colour") { if (!v || !/^#(?:[0-9a-fA-F]{3}){1,2}$/.test(v)) throw new Error("Colour must be a hex value like #0B2A4A"); return v.toUpperCase(); }
  if (kind === "font") { if (!v) throw new Error("Enter the font name"); return v.slice(0, 120); }
  if (FILE_KINDS.has(kind) && !hasFile && !(v && v.startsWith("https://"))) throw new Error("Attach an uploaded file or give an https link to the asset");
  return v;
}

export const ANALYTICS_UNAVAILABLE: Record<string, string> = {
  linkedin: "Post statistics need LinkedIn's Community Management API (reviewed access).",
  youtube: "Needs the YouTube Analytics API (not connected in this phase).",
  website: "Sessions, leads and conversions need GA4 (not connected in this phase).",
  ads: "Ad spend, CPL, conversion rate and ROAS need an authorised ad-account connection (none in this phase).",
};
export const AD_ADAPTERS: Record<string, string> = {
  meta: "Not connected. Creating ads needs a Meta Marketing API app with ads_management (App Review) and access to the client's ad account.",
  google: "Not connected. Creating ads needs a Google Ads API developer token (approval required) and OAuth access to the client's account.",
  linkedin: "Not connected. Creating ads needs the LinkedIn Advertising API product (application required) and a role on the ad account.",
};
export const STRATEGY_SECTIONS = ["executive_summary", "positioning", "brand_messaging", "target_audience", "channel_strategy", "seo", "social_media", "paid_ads",
  "content", "lead_generation", "calendar", "budget_allocation", "kpis", "reporting"];
export const SECTION_LABEL = (k: string) => ({ seo: "SEO", kpis: "KPIs", paid_ads: "Paid ads" } as Record<string, string>)[k] || KIND_LABEL(k);
