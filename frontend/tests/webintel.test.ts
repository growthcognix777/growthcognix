import { beforeEach, describe, expect, it } from "vitest";
import { localDriver as api } from "@/lib/api/local";
import { tokenStore } from "@/lib/api/token";

let n = 0;
const reg = (agency = "Web Agency") => api.register({ agency_name: agency, full_name: "Owner One", email: `w${++n}@example.com`, password: "Passw0rd!" });
beforeEach(() => tokenStore.clear());

describe("website & competitors (browser sandbox)", () => {
  it("never simulates crawls or audits", async () => {
    await reg(); const c = await api.createClient({ company_name: "Acme", website: "acme.in", target_markets: [], budget_currency: "INR" });
    await expect(api.startAudit(c.id)).rejects.toThrow(/backend/);
    expect((await api.getClientWebsite(c.id)).latest_audit).toBeNull();
    expect((await api.listOpportunities(c.id)).total).toBe(0);
  });
  it("manages competitors with validation", async () => {
    await reg(); const c = await api.createClient({ company_name: "Acme", website: "acme.in", target_markets: [], budget_currency: "INR" });
    await expect(api.addCompetitor(c.id, { name: "Self", website: "www.acme.in", category: "direct", relevance: { product: "x" }, geography: [] })).rejects.toThrow(/own website/);
    const r = await api.addCompetitor(c.id, { name: "Rival", website: "rival.com", category: "direct", relevance: { product: "pumps" }, geography: ["India"] });
    expect(r.domain).toBe("rival.com"); expect(r.domain_valid).toBeNull();
    await expect(api.addCompetitor(c.id, { name: "Dup", website: "https://www.rival.com/x", category: "direct", relevance: { product: "p" }, geography: [] })).rejects.toThrow(/already/);
    await expect(api.addCompetitor(c.id, { name: "Bad", category: "direct", relevance: { keyword: "p" }, geography: [] })).rejects.toThrow(/relevance/);
    await expect(api.analyseCompetitor(r.id)).rejects.toThrow(/backend/);
    expect((await api.editCompetitor(r.id, { name: "Rival Pumps" })).name).toBe("Rival Pumps");
    await reg("Other Agency");
    await expect(api.competitorProfile(r.id)).rejects.toThrow(/not found/);
  });
});
