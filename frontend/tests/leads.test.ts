import { beforeEach, describe, expect, it } from "vitest";
import { localDriver as api } from "@/lib/api/local";
import { tokenStore } from "@/lib/api/token";
import { computeScore, normaliseWeights, statusFromFields, toCsv } from "@/lib/leads";
import type { BusinessContact, LeadEvidence } from "@/lib/types";

let n = 0;
const reg = (agency = "Lead Agency") => api.register({ agency_name: agency, full_name: "Owner One", email: `l${++n}@example.com`, password: "Passw0rd!" });
const client = () => api.createClient({ company_name: "Acme Water", website: "acme.in", target_markets: [], budget_currency: "INR" });
beforeEach(() => tokenStore.clear());

describe("lead scoring rules (shared with the backend)", () => {
  const p = {
    verified_fields: { company: { by: "u", at: "" }, industry: { by: "u", at: "" } }, providers: ["searxng", "brave"], site_status: "ok", last_verified_at: null,
    site_checked_at: null, verification_status: "industry_verified" as const,
    signals: { matched_terms: [{ term: "dairy", kind: "fit" }, { term: "cip", kind: "fit" }, { term: "scale", kind: "need" }],
      intent: [{ signal: "tender", strength: "strong" }, { signal: "expansion", strength: "timing" }], capacity: [{ value: "ISO 22000" }, { value: "450 employees" }] },
  };
  const contacts = [{ kind: "role_email", verified: false }, { kind: "phone", verified: false }] as BusinessContact[];
  const ev = [{ field: "intent" }, { field: "need" }] as LeadEvidence[];
  it("matches the Python scorer exactly", () => {
    // expected values produced by backend/app/services/leads/scoring.py for the same input
    const r = computeScore(p, contacts, ev);
    expect(r.total).toBe(77); expect(r.confidence).toBe(0.64);
    expect(Object.fromEntries(Object.entries(r.components).map(([k, c]) => [k, c.points]))).toEqual({ fit: 26, need: 12, intent: 20, capacity: 12, contact: 7 });
    const r2 = computeScore(p, contacts, ev, { fit: 20, need: 20, intent: 40, capacity: 10, contact: 10 });
    expect(r2.total).toBe(82); expect(r2.components.intent.points).toBe(40);
  });
  it("gives no points for search appearance and no intent without evidence", () => {
    const r = computeScore({ verified_fields: {}, providers: ["searxng"], site_status: null, last_verified_at: null, site_checked_at: null, verification_status: "discovered" }, [], []);
    expect(r.total).toBe(0); expect(r.confidence).toBe(0); expect(r.components.intent.reasons[0]).toMatch(/intent scores 0/);
    expect(() => normaliseWeights({ fit: 90 })).toThrow(/100/);
  });
  it("derives verification status and guards CSV formulas", () => {
    expect(statusFromFields("discovered", { company: {}, industry: {} })).toBe("industry_verified");
    expect(statusFromFields("needs_review", { company: {} })).toBe("needs_review");
    expect(toCsv([{ name: "=HYPERLINK(1)" }]).split("\r\n")[1]).toMatch(/^'=HYPERLINK/);
  });
});

describe("buyer discovery (browser sandbox)", () => {
  it("refuses discovery, AI profiles and Comtrade instead of simulating them", async () => {
    await reg(); const c = await client();
    await expect(api.createLeadCampaign(c.id, { name: "x", persona_ids: [], geography_ids: [], sources: ["searxng"] })).rejects.toThrow(/backend/);
    await expect(api.generateBuyerProfiles(c.id, {})).rejects.toThrow(/backend/);
    await expect(api.fetchComtrade(c.id, { hs_code: "8413", reporter: "IN", period: "2023", flow: "M" })).rejects.toThrow(/backend/);
    expect((await api.listProspects(c.id)).total).toBe(0);
    expect((await api.leadSummary(c.id)).prospects).toBe(0);
  });

  it("saves research areas with the hierarchy rules", async () => {
    await reg(); const c = await client();
    const india = await api.addGeo(c.id, { level: "country", name: "india" });
    expect(india.name).toBe("India"); expect(india.country_code).toBe("IN");
    await expect(api.addGeo(c.id, { level: "state", name: "Karnatka", parent_id: india.id })).rejects.toThrow(/state/);
    await expect(api.addGeo(c.id, { level: "district", name: "Udupi" })).rejects.toThrow(/parent/);
    const ka = await api.addGeo(c.id, { level: "state", name: "Karnataka", parent_id: india.id });
    const d = await api.addGeo(c.id, { level: "district", name: "Belagavi", parent_id: ka.id });
    expect(d.path).toEqual(["India", "Karnataka", "Belagavi"]);
    await expect(api.addGeo(c.id, { level: "district", name: "belagavi", parent_id: ka.id })).rejects.toThrow(/already/);
    await api.deleteGeo(ka.id);
    expect((await api.listGeos(c.id)).map((g) => g.name)).toEqual(["India"]);
  });

  it("runs manual prospects through verification, approval, export and CRM hand-off", async () => {
    await reg(); const c = await client();
    await expect(api.addProspect(c.id, { name: "Dairy One", source_url: "" })).rejects.toThrow(/source/i);
    await expect(api.addProspect(c.id, { name: "Dairy One", website: "indiamart.com/dairy", source_url: "https://indiamart.com/dairy" })).rejects.toThrow(/listing/);
    await api.addSuppression({ kind: "domain", value: "https://www.dnc.example.com/" });
    await expect(api.addProspect(c.id, { name: "DNC", website: "dnc.example.com", source_url: "https://x.example.org/" })).rejects.toThrow(/do-not-contact/);
    const p = await api.addProspect(c.id, { name: "Dairy One", website: "dairyone.example.com", source_url: "https://kiadb.example.in/estate", district: "Belagavi" });
    expect(p.verification_status).toBe("discovered"); expect(p.score_total).toBe(0);
    await expect(api.addProspect(c.id, { name: "Dup", website: "https://www.dairyone.example.com/about", source_url: "https://a.example.com" })).rejects.toThrow(/already/);
    expect((await api.listProspects(c.id, { district: "Belagavi" })).total).toBe(1);

    expect((await api.approveLeads(c.id, { prospect_ids: [p.id], approved: true })).blocked[0]).toMatch(/verify the company/);
    await expect(api.verifyProspect(p.id, { field: "company", decision: "verified" })).rejects.toThrow(/source URL or a note/);
    const v = await api.verifyProspect(p.id, { field: "company", decision: "verified", note: "CIN checked on MCA" });
    expect(v.verification_status).toBe("company_verified");
    const d = await api.addProspectEvidence(p.id, { field: "intent", source_url: "https://bidplus.gem.gov.in/bid/1", excerpt: "GeM bid for boiler chemicals" });
    expect(d.score!.components.intent.points).toBe(10);
    await api.addProspectContact(p.id, { kind: "role_email", value: "Sales@DairyOne.example.com", source_url: "https://dairyone.example.com/contact" });
    await expect(api.addProspectContact(p.id, { kind: "person", person_name: "R Kumar", source_url: "https://dairyone.example.com/team" })).rejects.toThrow(/role/);

    await expect(api.exportLeads(c.id, "csv")).rejects.toThrow(/No approved/);
    expect((await api.crmHandoff(c.id, [p.id])).handed_off).toBe(0);
    expect((await api.approveLeads(c.id, { prospect_ids: [p.id], approved: true })).updated).toBe(1);
    const csv = await (await api.exportLeads(c.id, "csv")).text();
    expect(csv.split("\r\n")[0]).toMatch(/^name,website,domain/); expect(csv).toContain("sales@dairyone.example.com");
    await api.addSuppression({ kind: "email", value: "sales@dairyone.example.com" });
    expect(await (await api.exportLeads(c.id, "csv")).text()).not.toContain("sales@dairyone.example.com");
    await expect(api.exportLeads(c.id, "xlsx")).rejects.toThrow(/CSV/);
    expect((await api.crmHandoff(c.id, [p.id])).handed_off).toBe(1);

    const me = (await api.me()).user;
    expect((await api.assignLeads(c.id, { prospect_ids: [p.id], user_id: me.id })).updated).toBe(1);
    expect((await api.listProspects(c.id, { assigned_to: me.id })).total).toBe(1);
    const r = await api.verifyProspect(p.id, { field: "status", decision: "rejected", note: "Not a buyer" });
    expect(r.confidence).toBe(0);
    expect((await api.listProspects(c.id)).total).toBe(0);

    await reg("Other Agency");
    await expect(api.getProspect(p.id)).rejects.toThrow(/not found/);
    expect(await api.listSuppression()).toEqual([]);
  });
});
