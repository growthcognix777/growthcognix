import { beforeEach, describe, expect, it } from "vitest";
import { localDriver as api } from "@/lib/api/local";
import { tokenStore } from "@/lib/api/token";
import { allowedActions, detectClaims, guaranteeIssues, nextStatus, statusAfterEdit, summarise, templateLines, validateAsset } from "@/lib/marketing";
import type { ContentItem, MarketingBudget } from "@/lib/types";

let n = 0;
const reg = (agency = "Mk Agency") => api.register({ agency_name: agency, full_name: "Owner One", email: `m${++n}@example.com`, password: "Passw0rd!" });
const client = () => api.createClient({ company_name: "AquaPure", target_markets: [], budget_currency: "INR", marketing_budget: 100000 });
beforeEach(() => tokenStore.clear());

describe("marketing rules (shared with the backend)", () => {
  it("budget template matches budget_planner.py", () => {
    // values produced by backend/app/services/marketing/budget_planner.py
    expect(templateLines(100000).map((l) => l.amount)).toEqual([15000, 15000, 12000, 20000, 15000, 8000, 5000, 10000]);
    expect(templateLines(1000, ["seo", "paid_search", "video_production"]).map((l) => l.amount)).toEqual([348.84, 465.12, 186.04]);
    expect(templateLines(99999.99).at(-1)!.amount).toBe(9999.99);
    const s = summarise(templateLines(200000));
    expect(s.monthly_total).toBe(200000); expect(s.quarterly_total).toBe(600000); expect(s.by_cost_kind.ad_spend).toBe(70000);
    expect(summarise(templateLines(1000, ["seo"]), { seo: 2500 }).quarterly_total).toBe(2500);
  });
  it("claims and guarantees match common.py", () => {
    const t = "AquaPure RO plants are ISO 9001 certified. Trusted by 500 customers across 12 countries! Price starts at Rs 2 lakh. Better than imported plants. Call us today.";
    expect(detectClaims(t)).toEqual(["[certification] AquaPure RO plants are ISO 9001 certified.", "[number/endorsement] Trusted by 500 customers across 12 countries!",
      "[price] Price starts at Rs 2 lakh.", "[comparison] Better than imported plants."]);
    expect(guaranteeIssues("We guarantee results and assured leads; you will definitely get more. Risk-free returns.")).toEqual(["guarantee", "assured leads", "will definitely get", "Risk-free returns"]);
  });
  it("approval transitions match approval_service.py", () => {
    expect(allowedActions("draft", "staff")).toEqual(["submit"]);
    expect(allowedActions("internal_review", "staff")).toEqual([]);
    expect(allowedActions("internal_review", "manager")).toEqual(["approve", "send_to_client", "reject", "request_changes"]);
    expect(nextStatus("internal_review", "approve", true)).toBe("client_review");
    expect(nextStatus("client_review", "client_approve")).toBe("approved");
    expect(() => nextStatus("approved", "approve")).toThrow();
    expect(statusAfterEdit("approved")).toBe("internal_review"); expect(statusAfterEdit("draft")).toBe("draft");
    expect(validateAsset("colour", "#0b2a4a", false)).toBe("#0B2A4A");
    expect(() => validateAsset("logo", null, false)).toThrow(/https/);
  });
});

describe("marketing in the browser preview", () => {
  it("refuses AI, OAuth and publishing instead of simulating them", async () => {
    await reg(); const c = await client();
    await expect(api.createStrategy(c.id, { title: "Plan" })).rejects.toThrow(/backend/);
    await expect(api.generateContent(c.id, { studio: "social", kind: "carousel", platform: "instagram" })).rejects.toThrow(/backend/);
    await expect(api.connectSocial(c.id, "facebook")).rejects.toThrow(/official APIs/);
    expect(await api.marketingAnalytics(c.id)).toMatchObject({ platform: [], calculated: [] });
    expect((await api.listSocialAccounts(c.id)).accounts).toEqual([]);
  });
  it("runs content through review; edits after approval need approval again", async () => {
    await reg(); const c = await client();
    await expect(api.addContent(c.id, { kind: "educational", platform: "linkedin", title: "Results", body: "Guaranteed leads in 30 days" })).rejects.toThrow(/guarantee/);
    const it = await api.addContent(c.id, { kind: "educational", platform: "linkedin", title: "Why RO", body: "ISO 9001 certified plants." });
    expect(it.status).toBe("draft"); expect(it.claims_to_check).toHaveLength(1);
    await expect(api.markPublished(it.id, { url: "https://example.com/p" })).rejects.toThrow(/approved/);
    await api.review("content", it.id, { action: "submit" });
    await expect(api.review("content", it.id, { action: "approve" })).rejects.toThrow(/fact-check/);
    await api.saveCalendarSettings(c.id, { timezone: "Asia/Kolkata", require_client_review: true, default_reviewer_id: null });
    expect(((await api.review("content", it.id, { action: "approve", note: "Certificate checked" })) as ContentItem).status).toBe("client_review");
    await expect(api.review("content", it.id, { action: "client_approve", note: "ok" })).rejects.toThrow(/who at the client/);
    const ok = (await api.review("content", it.id, { action: "client_approve", note: "By email", reviewer_name: "R. Shetty" })) as ContentItem;
    expect(ok.status).toBe("approved");
    const when = new Date(Date.now() + 864e5).toISOString();
    expect((await api.editContent(it.id, { scheduled_at: when })).status).toBe("approved");
    const cal = await api.calendar(c.id, new Date().toISOString(), new Date(Date.now() + 5 * 864e5).toISOString());
    expect(cal.items.map((i) => i.id)).toEqual([it.id]);
    const e = await api.editContent(it.id, { body: "New caption" });
    expect(e.status).toBe("internal_review"); expect(e.version).toBe(2);
    const h = await api.marketingHistory("content", it.id);
    expect(h.revisions[0].version).toBe(2); expect(h.approvals.some((a) => a.reviewer_name === "R. Shetty")).toBe(true);
  });
  it("plans budgets and records spend approval without spending", async () => {
    await reg(); const c = await client();
    const b = await api.createBudget(c.id, { name: "Q1" });
    expect(b.summary.monthly_total).toBe(100000);
    const g = await api.budgetScenario(b.id, "growth"); expect(g.summary.monthly_total).toBe(140000);
    await expect(api.editBudget(b.id, { lines: [{ ...b.lines[0], amount: -1 }] })).rejects.toThrow(/negative/);
    expect((await api.editBudget(b.id, { lines: b.lines.map((l, i) => (i === 0 ? { ...l, amount: 50000 } : l)) })).summary.monthly_total).toBe(135000);
    await api.review("budget", b.id, { action: "submit" });
    expect(((await api.review("budget", b.id, { action: "approve" })) as MarketingBudget).status).toBe("approved");
    const ad = await api.addAdPlan(c.id, { platform: "google", name: "RO plants", headlines: ["RO plants for dairies"], total_budget: 50000 });
    await expect(api.spendApproval(ad.id, { approved: true, spend_cap: 1000 })).rejects.toThrow(/Approve the ad plan/);
    await api.review("ad_plan", ad.id, { action: "submit" }); await api.review("ad_plan", ad.id, { action: "approve" });
    await expect(api.spendApproval(ad.id, { approved: true, spend_cap: 90000 })).rejects.toThrow(/exceed/);
    const s = await api.spendApproval(ad.id, { approved: true, spend_cap: 40000 });
    expect(s.spend_approved).toBe(true); expect(s.note).toMatch(/Not connected/);
    expect((await api.editAdPlan(ad.id, { daily_budget: 3000 })).spend_approved).toBe(false);
    const r = await api.createMarketingReport(c.id, { start: "2026-01-01", end: "2027-01-01" });
    expect(r.markdown).toContain("Approved budget: Q1"); expect(r.markdown).toContain("— No connected platform has reported metrics yet.");
  });
  it("isolates tenants and only attaches approved assets", async () => {
    await reg("Agency A"); const c = await client();
    const col = await api.addAsset(c.id, { kind: "colour", name: "Navy", value: "#0b2a4a" });
    const it = await api.addContent(c.id, { kind: "educational", platform: "facebook", title: "Hello", body: "Text" });
    await expect(api.editContent(it.id, { asset_ids: [col.id] })).rejects.toThrow(/approved/);
    await api.approveAsset(col.id, true);
    expect((await api.editContent(it.id, { asset_ids: [col.id] })).asset_ids).toEqual([col.id]);
    await reg("Agency B");
    await expect(api.getContent(it.id)).rejects.toThrow(/not found/);
    await expect(api.listContent(c.id)).rejects.toThrow(/not found/);
  });
});
