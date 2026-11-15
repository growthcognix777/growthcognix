import { beforeEach, describe, expect, it } from "vitest";
import { localDriver as api } from "@/lib/api/local";
import { tokenStore } from "@/lib/api/token";

let n = 0;
const reg = (agency = "Acme") => api.register({ agency_name: agency, full_name: "Owner One", email: `o${++n}@example.com`, password: "Passw0rd!" });
beforeEach(() => tokenStore.clear());

describe("browser sandbox driver", () => {
  it("registers, starts empty and logs activity", async () => {
    await reg();
    expect(await api.dashboard()).toEqual({ active_clients: 0, archived_clients: 0, products: 0, documents: 0, team_members: 1, jobs_running: 0 });
    expect((await api.listActivity()).items[0].action).toBe("agency.registered");
  });
  it("rejects bad login", async () => { await expect(api.login({ email: "nobody@example.com", password: "x" })).rejects.toThrow(/Incorrect/); });
  it("creates, searches, archives clients", async () => {
    await reg();
    const c = await api.createClient({ company_name: "AquaPure", website: "aquapure.in", target_markets: ["UAE"], budget_currency: "INR" });
    expect(c.website).toBe("https://aquapure.in");
    expect((await api.listClients({ q: "aqua" })).total).toBe(1);
    await expect(api.deleteClient(c.id)).rejects.toThrow(/Archive/);
    await api.archiveClient(c.id);
    expect((await api.listClients()).total).toBe(0);
  });
  it("isolates tenants", async () => {
    await reg("Agency A"); const c = await api.createClient({ company_name: "Secret", target_markets: [], budget_currency: "INR" });
    await reg("Agency B");
    await expect(api.getClient(c.id)).rejects.toThrow(/not found/);
    expect((await api.listClients()).total).toBe(0);
  });
  it("validates document type and content", async () => {
    await reg(); const c = await api.createClient({ company_name: "Docs Co", target_markets: [], budget_currency: "INR" });
    const pdf = new File([new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d])], "cat.pdf", { type: "application/pdf" });
    const d = await api.uploadDocument(pdf, c.id);
    expect(d.file_ext).toBe("pdf"); expect((await api.getClient(c.id)).document_count).toBe(1);
    const fake = new File([new Uint8Array([0x4d, 0x5a, 0, 0])], "evil.pdf");
    await expect(api.uploadDocument(fake, c.id)).rejects.toThrow(/does not match/);
  });
  it("lists all 8 agents as planned with no runs", async () => {
    await reg(); const a = await api.listAgents();
    expect(a).toHaveLength(8); expect(a.every((x) => x.status === "planned" && x.total_jobs === 0)).toBe(true);
  });
});
