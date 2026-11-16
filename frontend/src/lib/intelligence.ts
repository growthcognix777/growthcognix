// Mirrors backend/app/routers/intelligence.py field rules so both drivers validate findings the same way.
import { ApiError, type Finding, type FindingType, type VerificationStatus } from "./types";

type Kind = "str" | "list" | "dict";
export const FIELDS: Record<FindingType, Record<string, Kind>> = {
  profile: { summary: "str", value_proposition: "str", facts: "dict" },
  application: { product_id: "str", application: "str", application_type: "str", industry: "str", description: "str",
    businesses_needing: "list", buyer_categories: "list", pain_points: "list", purchase_reasons: "list", substitutes: "list" },
  market: { product_id: "str", scope: "str", name: "str", parent: "str", rationale: "str", priority: "str" },
  persona: { product_id: "str", name: "str", buyer_category: "str", industry: "str", company_size: "str", job_titles: "list",
    departments: "list", pain_points: "list", purchase_reasons: "list", description: "str" },
  insight: { product_id: "str", category: "str", field: "str", title: "str", detail: "str" },
};
export const REQUIRED: Record<FindingType, string[]> = {
  profile: ["summary"], application: ["product_id", "application"], market: ["scope", "name"], persona: ["name"], insight: ["category", "title"],
};
export const ENUMS: Record<string, string[]> = {
  application_type: ["direct", "indirect"],
  scope: ["india", "state", "district_city", "country", "export_market"],
  priority: ["high", "medium", "low"],
  category: ["product_fact", "advantage", "differentiation", "industry_usage", "opportunity", "risk", "gap"],
};
export const INFERRED_TYPES: FindingType[] = ["persona", "market"];

export const STATUS_LABEL: Record<VerificationStatus, string> = {
  verified: "Verified", ai_hypothesis: "AI hypothesis", needs_review: "Needs review", rejected: "Rejected",
};
export const SCOPE_LABEL: Record<string, string> = {
  india: "India", state: "State", district_city: "District / city", country: "Country", export_market: "Export market",
};
export const CATEGORY_LABEL: Record<string, string> = {
  product_fact: "Product fact", advantage: "Advantage", differentiation: "Differentiation", industry_usage: "Industry usage",
  opportunity: "Opportunity", risk: "Risk", gap: "Information gap",
};
export const LABEL = (k: string) => k.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

/** Validate and normalise human-entered finding data. Throws ApiError(422) like the backend. */
export function cleanFinding(type: FindingType, data: Record<string, unknown>, partial: boolean): Record<string, unknown> {
  const spec = FIELDS[type];
  const unknown = Object.keys(data).filter((k) => !(k in spec));
  if (unknown.length) throw new ApiError(422, `Unknown fields: ${unknown.sort().join(", ")}`);
  const out: Record<string, unknown> = {};
  for (const [k, raw] of Object.entries(data)) {
    const t = spec[k];
    const empty = raw === "" || raw === null || raw === undefined || (Array.isArray(raw) && !raw.length);
    if (empty) {
      if (REQUIRED[type].includes(k)) throw new ApiError(422, `${LABEL(k)} is required`, [{ field: k, message: "Required" }]);
      out[k] = t === "list" ? [] : t === "dict" ? {} : null;
      continue;
    }
    let v: unknown = raw;
    if (t === "str") {
      if (typeof raw !== "string") throw new ApiError(422, `${LABEL(k)} must be text`);
      v = raw.trim().slice(0, 4000);
    } else if (t === "list") {
      if (!Array.isArray(raw)) throw new ApiError(422, `${LABEL(k)} must be a list`);
      v = raw.map((x) => String(x).trim().slice(0, 200)).filter(Boolean).slice(0, 30);
    } else {
      if (typeof raw !== "object" || Array.isArray(raw) || !Object.values(raw as object).every((x) => typeof x === "string"))
        throw new ApiError(422, `${LABEL(k)} must be an object of text values`);
      v = Object.fromEntries(Object.entries(raw as Record<string, string>).filter(([, b]) => b.trim()).map(([a, b]) => [a.slice(0, 60), b.trim().slice(0, 500)]));
    }
    if (ENUMS[k] && !ENUMS[k].includes(v as string)) throw new ApiError(422, `${LABEL(k)} must be one of ${ENUMS[k].join(", ")}`, [{ field: k, message: "Invalid choice" }]);
    out[k] = v;
  }
  if (!partial) {
    const missing = REQUIRED[type].filter((k) => !out[k]);
    if (missing.length) throw new ApiError(422, `Missing required fields: ${missing.map(LABEL).join(", ")}`, missing.map((f) => ({ field: f, message: "Required" })));
  }
  return out;
}

export function isInferred(type: FindingType, data: Record<string, unknown>): boolean {
  return INFERRED_TYPES.includes(type) || ["opportunity", "risk", "gap", "differentiation"].includes(String(data.category))
    || data.application_type === "indirect";
}

/** The status a reviewer's approval produces: inferences are never shown as verified facts. */
export function approvedStatus(f: Pick<Finding, "is_inferred">): VerificationStatus {
  return f.is_inferred ? "ai_hypothesis" : "verified";
}

export function statusText(f: Pick<Finding, "verification_status" | "approved">): string {
  const s = STATUS_LABEL[f.verification_status];
  return f.approved && f.verification_status === "ai_hypothesis" ? `${s} (approved)` : s;
}

/** Markdown business-intelligence report, same layout as the backend's report.md. Shows only stored findings. */
export function buildReportMarkdown(clientName: string, byType: Record<FindingType, Finding[]>, products: { id: string; name: string }[]): string {
  const live = (t: FindingType) => byType[t].filter((f) => f.verification_status !== "rejected");
  const d = (f: Finding, k: string) => (f.data[k] as string | null) ?? "";
  const L: string[] = [`# Business Intelligence Report — ${clientName}`, "",
    "Statuses: Verified = confirmed by a reviewer; Needs review = awaiting review; AI hypothesis = inferred, not verified.", "",
    "## Company overview", ""];
  const p = live("profile").slice(-1)[0];
  if (p) {
    L.push(`_${statusText(p)}_`, "", d(p, "summary") || "—", "");
    if (d(p, "value_proposition")) L.push(`**Value proposition:** ${d(p, "value_proposition")}`, "");
    Object.entries((p.data.facts as Record<string, string>) || {}).forEach(([k, v]) => L.push(`- **${LABEL(k)}:** ${v}`));
    L.push("");
  } else L.push("— Not analysed yet.", "");
  L.push("## Products", "");
  for (const pr of products) {
    L.push(`### ${pr.name}`, "");
    const facts = live("insight").filter((i) => i.data.product_id === pr.id && i.data.category === "product_fact");
    facts.forEach((f) => L.push(`- ${d(f, "title")}: ${d(f, "detail")} — _${statusText(f)}_`));
    if (!facts.length) L.push("- — No product facts yet.");
    const apps = live("application").filter((a) => a.data.product_id === pr.id);
    if (apps.length) { L.push("", "Applications:"); apps.forEach((a) => L.push(`- ${d(a, "application")} (${d(a, "application_type") || "—"}${d(a, "industry") ? ", " + d(a, "industry") : ""}) — _${statusText(a)}_`)); }
    L.push("");
  }
  const per = live("persona");
  L.push("## Buyer personas", "", ...(per.length ? per.map((x) => `- ${d(x, "name")} — _${statusText(x)}_`) : ["- —"]), "");
  const mk = live("market");
  L.push("## Target markets", "", ...(mk.length ? mk.map((x) => `- [${d(x, "scope")}] ${d(x, "name")}${d(x, "parent") ? ` (${d(x, "parent")})` : ""}: ${d(x, "rationale") || "—"} — _${statusText(x)}_`) : ["- —"]), "");
  const op = live("insight").filter((i) => ["opportunity", "risk", "gap"].includes(String(i.data.category)));
  L.push("## Opportunities, risks and gaps", "", ...(op.length ? op.map((x) => `- **${LABEL(d(x, "category"))}: ${d(x, "title")}** — ${d(x, "detail") || "—"} — _${statusText(x)}_`) : ["- —"]));
  return L.join("\n") + "\n";
}
