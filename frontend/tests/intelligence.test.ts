import { beforeEach, describe, expect, it } from "vitest";
import { localDriver as api } from "@/lib/api/local";
import { tokenStore } from "@/lib/api/token";
import { buildReportMarkdown, cleanFinding } from "@/lib/intelligence";

let n = 0;
const reg = (agency = "Intel") => api.register({ agency_name: agency, full_name: "Owner One", email: `i${++n}@example.com`, password: "Passw0rd!" });
beforeEach(() => tokenStore.clear());

describe("client intelligence (browser sandbox)", () => {
  it("refuses AI analysis honestly instead of faking results", async () => {
    await reg(); const c = await api.createClient({ company_name: "NoAI", target_markets: [], budget_currency: "INR" });
    await expect(api.startAnalysis(c.id)).rejects.toThrow(/backend/);
    expect(await api.listAnalyses(c.id)).toEqual([]);
  });
  it("adds, edits and reviews findings with status rules", async () => {
    await reg(); const c = await api.createClient({ company_name: "Pumps Co", target_markets: [], budget_currency: "INR" });
    const p = await api.createProduct({ client_id: c.id, kind: "product", name: "Pump X", target_industries: [] });
    const app = await api.createFinding(c.id, "application", { data: { product_id: p.id, application: "Irrigation", application_type: "direct" }, note: "Catalogue p.3" });
    expect(app.verification_status).toBe("needs_review"); expect(app.is_inferred).toBe(false); expect(app.evidence[0].excerpt).toBe("Catalogue p.3");
    expect((await api.reviewFinding("application", app.id, "approve")).verification_status).toBe("verified");
    const edited = await api.editFinding("application", app.id, { industry: "Agriculture" });
    expect(edited.approved).toBe(false); expect(edited.verification_status).toBe("needs_review");
    const per = await api.createFinding(c.id, "persona", { data: { name: "Farm co-op buyer" } });
    expect((await api.reviewFinding("persona", per.id, "approve")).verification_status).toBe("ai_hypothesis");
    await api.reviewFinding("persona", per.id, "reject");
    expect((await api.listFindings(c.id, "persona")).total).toBe(0);
    expect((await api.listFindings(c.id, "persona", { include_rejected: true })).total).toBe(1);
  });
  it("blocks applications on another client's product and other tenants' findings", async () => {
    await reg("Agency A"); const c1 = await api.createClient({ company_name: "One", target_markets: [], budget_currency: "INR" });
    const c2 = await api.createClient({ company_name: "Two", target_markets: [], budget_currency: "INR" });
    const p2 = await api.createProduct({ client_id: c2.id, kind: "product", name: "Other", target_industries: [] });
    await expect(api.createFinding(c1.id, "application", { data: { product_id: p2.id, application: "X" } })).rejects.toThrow(/does not belong/);
    const f = await api.createFinding(c1.id, "market", { data: { scope: "country", name: "Germany" } });
    await reg("Agency B");
    await expect(api.editFinding("market", f.id, { name: "France" })).rejects.toThrow(/not found/);
  });
  it("validates fields and keeps unknown data empty", () => {
    expect(() => cleanFinding("market", { scope: "planet", name: "Mars" }, false)).toThrow(/Scope/);
    expect(() => cleanFinding("persona", {}, false)).toThrow(/Name/);
    expect(() => cleanFinding("persona", { name: "X", salary: "1" }, false)).toThrow(/Unknown/);
    const md = buildReportMarkdown("Empty Co", { profile: [], application: [], market: [], persona: [], insight: [] }, []);
    expect(md).toContain("— Not analysed yet."); expect(md).toContain("## Buyer personas\n\n- —");
  });
});
