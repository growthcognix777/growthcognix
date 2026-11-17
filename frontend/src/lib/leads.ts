// Phase 4 shared rules. Mirrors backend/app/services/leads/scoring.py and the verification rules in
// backend/app/routers/leads.py so the browser preview and the API score and verify leads the same way.
import type { BusinessContact, GeoReference, LeadEvidence, LeadScore, LeadVerification, Prospect, ScoreClass } from "./types";

export const DEFAULT_WEIGHTS: Record<string, number> = { fit: 30, need: 25, intent: 20, capacity: 15, contact: 10 };
export const WEIGHT_LABEL: Record<string, string> = { fit: "Product & industry fit", need: "Business need", intent: "Buying intent & timing", capacity: "Purchase capacity", contact: "Contact quality" };
export const CLASSES: [number, ScoreClass][] = [[80, "very_high"], [65, "high"], [40, "medium"], [0, "low"]];
export const CLASS_LABEL: Record<ScoreClass, string> = { very_high: "Very high", high: "High", medium: "Medium", low: "Low" };
export const CLASS_TONE: Record<ScoreClass, "green" | "blue" | "amber" | "slate"> = { very_high: "green", high: "blue", medium: "amber", low: "slate" };
export const VERIFICATION_ORDER: LeadVerification[] = ["discovered", "company_verified", "website_verified", "industry_verified", "product_relevance_verified", "contact_verified"];
export const STATUS_LABEL: Record<LeadVerification, string> = {
  discovered: "Discovered", company_verified: "Company verified", website_verified: "Website verified", industry_verified: "Industry verified",
  product_relevance_verified: "Product relevance verified", contact_verified: "Contact verified", needs_review: "Needs review", rejected: "Rejected",
};
export const FIELD_STATUS: Record<string, LeadVerification> = { company: "company_verified", website: "website_verified", industry: "industry_verified", product_relevance: "product_relevance_verified", contact: "contact_verified" };
export const BUYER_TYPE_LABEL: Record<string, string> = { end_user: "End user", distributor: "Distributor", importer: "Importer", dealer: "Dealer", oem: "OEM", institutional: "Institutional", project: "Project / EPC" };
export const LISTING_DOMAINS = ["indiamart.com", "tradeindia.com", "justdial.com", "exportersindia.com", "alibaba.com", "made-in-china.com", "amazon.", "flipkart.com",
  "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com", "youtube.com", "wikipedia.org", "quora.com", "reddit.com", "medium.com", "pinterest.",
  "glassdoor.", "naukri.com", "indeed.", "zaubacorp.com", "tofler.in", "crunchbase.com", "dnb.com", "google.", "bing.com", "yelp.", "yellowpages", "kompass.com",
  "europages.", "thomasnet.com", "blogspot.com", "wordpress.com", "wix.com", "sulekha.com"];
export const isListingSite = (d: string | null) => !!d && LISTING_DOMAINS.some((x) => d === x || d.endsWith("." + x) || (x.endsWith(".") && (d.startsWith(x) || d.includes("." + x))));
export const classify = (t: number): ScoreClass => CLASSES.find(([m]) => t >= m)![1];

export function normaliseWeights(w?: Record<string, number> | null): Record<string, number> {
  const out: Record<string, number> = {};
  Object.keys(DEFAULT_WEIGHTS).forEach((k) => (out[k] = Math.trunc(Number(w?.[k] ?? DEFAULT_WEIGHTS[k]))));
  if (Object.values(out).some((v) => !(v >= 0)) || Object.values(out).reduce((a, b) => a + b, 0) !== 100) throw new Error("Weights must be non-negative and add up to 100");
  return out;
}

type P = Pick<Prospect, "verified_fields" | "providers" | "site_status" | "last_verified_at" | "site_checked_at" | "verification_status"> & { signals?: { matched_terms?: { term: string; kind: string }[]; intent?: { signal: string; strength: string }[]; capacity?: { value: string }[] } };
// Python round() is banker's rounding; match it so both drivers give the same points
const pyRound = (x: number) => { const f = Math.floor(x); const d = x - f; if (Math.abs(d - 0.5) < 1e-9) return f % 2 === 0 ? f : f + 1; return Math.round(x); };

export function computeScore(p: P, contacts: BusinessContact[], userEvidence: LeadEvidence[], weights?: Record<string, number> | null): Omit<LeadScore, "created_at"> {
  const w = normaliseWeights(weights);
  const v = p.verified_fields || {};
  const sig = p.signals || {};
  const terms = (sig.matched_terms || []).filter((t) => (t.kind || "fit") === "fit");
  const need = (sig.matched_terms || []).filter((t) => t.kind === "need");
  const intent = sig.intent || []; const capacity = sig.capacity || [];
  const uev = (f: string) => userEvidence.filter((e) => e.field === f);
  const comps: Record<string, { points: number; max: number; reasons: string[] }> = {};
  const part = (k: string, frac: number, reasons: string[]) => { frac = Math.max(0, Math.min(1, frac)); comps[k] = { points: pyRound(w[k] * frac), max: w[k], reasons: reasons.length ? reasons : ["No supporting evidence yet"] }; };

  let r: string[] = []; let f = 0;
  if ("product_relevance" in v) { f = 1; r.push("Product relevance verified by a person"); }
  else if ("industry" in v) { f = 0.7; r.push("Industry verified by a person"); }
  if (f < 1 && terms.length) { const add = Math.min(0.5, 0.17 * terms.length); f = f === 0 ? Math.max(f, add) : Math.min(1, f + add / 2); r.push(`Its site mentions ${terms.length} relevant application/industry term(s): ` + terms.slice(0, 4).map((t) => t.term).join(", ")); }
  if (uev("fit").length) { f = Math.max(f, 0.5); r.push(`${uev("fit").length} fit evidence item(s) added by the team`); }
  if (!r.length) r.push("No fit evidence beyond appearing in a search or directory");
  part("fit", f, r);

  r = []; f = 0;
  if ("product_relevance" in v) { f += 0.5; r.push("A person confirmed the product meets a need this company has"); }
  if (need.length) { f += Math.min(0.5, 0.2 * need.length); r.push(`Its site describes ${need.length} problem(s) the product addresses: ` + need.slice(0, 3).map((t) => t.term).join(", ")); }
  if (uev("need").length) { f += 0.3; r.push(`${uev("need").length} need evidence item(s) added by the team`); }
  part("need", f, r);

  const strong = intent.filter((i) => i.strength === "strong"); const timing = intent.filter((i) => i.strength === "timing");
  r = []; f = 0;
  if (strong.length) { f += 0.5 * Math.min(2, strong.length); r.push("Buying signal on its site: " + strong.slice(0, 2).map((i) => i.signal).join("; ")); }
  if (timing.length) { f += 0.25; r.push("Timing signal on its site: " + timing[0].signal); }
  if (uev("intent").length) { f += 0.5 * Math.min(2, uev("intent").length); r.push(`${uev("intent").length} intent evidence item(s) with a source URL (e.g. tender, enquiry)`); }
  if (!r.length) r.push("No observable buying signal (tender, RFQ, procurement notice or explicit request), so intent scores 0");
  part("intent", f, r);

  r = []; f = 0;
  if (capacity.length) { f += Math.min(0.7, 0.25 * capacity.length); r.push("Capacity signals on its site: " + capacity.slice(0, 3).map((c) => c.value).join(", ")); }
  if ("company" in v) { f += 0.3; r.push("Company verified by a person"); }
  if (uev("capacity").length) { f += 0.3; r.push(`${uev("capacity").length} capacity evidence item(s) added by the team`); }
  part("capacity", f, r);

  r = []; f = 0;
  if (contacts.some((c) => c.kind === "person" && c.verified)) { f = 1; r.push("Verified business decision-maker with a public source"); }
  else {
    if (contacts.some((c) => c.kind === "role_email")) { f += 0.4; r.push("Role email published on its site"); }
    if (contacts.some((c) => c.kind === "phone")) { f += 0.3; r.push("Business phone published on its site"); }
    if ("contact" in v) { f += 0.3; r.push("Contact details verified by a person"); }
  }
  part("contact", f, r);

  const total = Object.values(comps).reduce((a, c) => a + c.points, 0);
  const why = Object.keys(DEFAULT_WEIGHTS).map((k) => `${k[0].toUpperCase() + k.slice(1)} ${comps[k].points}/${comps[k].max}: ${comps[k].reasons[0]}`);
  let conf = 0;
  if (p.site_status === "ok") conf += 0.2;
  conf += 0.12 * ["company", "website", "industry", "product_relevance", "contact"].filter((k) => k in v).length;
  if ((p.providers || []).length >= 2) conf += 0.1;
  if (terms.length || need.length) conf += 0.05;
  if (userEvidence.length) conf += 0.05;
  const last = p.last_verified_at || p.site_checked_at;
  if (last && (Date.now() - new Date(last).getTime()) / 86400000 > 180) { conf *= 0.6; why.push("Confidence reduced: last verified more than 180 days ago"); }
  if (p.verification_status === "rejected") conf = 0;
  conf = Math.round(Math.min(1, conf) * 100) / 100;
  return { total, score_class: classify(total), confidence: conf, components: comps, weights: w, explanation: why, version: "v1" };
}

/** Highest verified status from the fields a person (or the site check) verified. */
export function statusFromFields(current: LeadVerification, vf: Record<string, unknown>): LeadVerification {
  if (current === "rejected" || current === "needs_review") return current;
  let best: LeadVerification = "discovered";
  Object.entries(FIELD_STATUS).forEach(([f, st]) => { if (f in vf && VERIFICATION_ORDER.indexOf(st) > VERIFICATION_ORDER.indexOf(best)) best = st; });
  return best;
}

export const EXPORT_COLUMNS = ["name", "website", "domain", "buyer_type", "industry", "company_category", "country", "state", "district", "city",
  "industrial_area", "verification_status", "score_total", "score_class", "confidence", "qualification_reason", "role_emails", "phones", "assigned_to",
  "evidence_urls", "last_verified_at"];

export function toCsv(rows: Record<string, unknown>[]): string {
  const esc = (v: unknown) => {
    let s = v === null || v === undefined ? "" : String(v);
    if (/^[=+\-@]/.test(s)) s = "'" + s; // spreadsheet formula injection guard
    return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [EXPORT_COLUMNS.join(","), ...rows.map((r) => EXPORT_COLUMNS.map((k) => esc(r[k])).join(","))].join("\r\n") + "\r\n";
}

export const GEO_PARENT: Record<string, string[]> = { country: ["global"], state: ["country"], district: ["state"], city: ["district", "state"], industrial_area: ["city", "district", "state"] };

export const GEO_REFERENCE: GeoReference = {
  levels: ["global", "country", "state", "district", "city", "industrial_area"],
  countries: ([
    ["India", "IN", 699], ["United Arab Emirates", "AE", 784], ["Saudi Arabia", "SA", 682], ["Qatar", "QA", 634], ["Oman", "OM", 512], ["Kuwait", "KW", 414],
    ["Bahrain", "BH", 48], ["Bangladesh", "BD", 50], ["Nepal", "NP", 524], ["Sri Lanka", "LK", 144], ["Singapore", "SG", 702], ["Malaysia", "MY", 458],
    ["Indonesia", "ID", 360], ["Vietnam", "VN", 704], ["Thailand", "TH", 764], ["China", "CN", 156], ["Japan", "JP", 392], ["South Korea", "KR", 410],
    ["Australia", "AU", 36], ["Kenya", "KE", 404], ["Nigeria", "NG", 566], ["South Africa", "ZA", 710], ["Egypt", "EG", 818], ["Turkey", "TR", 792],
    ["Germany", "DE", 276], ["France", "FR", 251], ["Italy", "IT", 380], ["Spain", "ES", 724], ["Netherlands", "NL", 528], ["United Kingdom", "GB", 826],
    ["United States", "US", 842], ["Canada", "CA", 124], ["Mexico", "MX", 484], ["Brazil", "BR", 76],
  ] as [string, string, number][]).map(([name, code, comtrade]) => ({ name, code, comtrade })),
  india: {
    states: ["Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
      "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu",
      "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal"],
    union_territories: ["Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry"],
    note: "Districts, cities and industrial clusters are added as saved research areas. India's Local Government Directory (lgdirectory.gov.in) is the official district list.",
  },
  sources: [{ name: "UN Comtrade", url: "https://comtradeplus.un.org/" }, { name: "Local Government Directory (India)", url: "https://lgdirectory.gov.in/" }],
};
