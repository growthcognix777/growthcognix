import { describe, expect, it } from "vitest";
import { normaliseUrl, validateClient, validateFile, validatePassword, validateRegister } from "@/lib/validate";

describe("validation", () => {
  it("normalises websites", () => { expect(normaliseUrl("acme.in")).toBe("https://acme.in"); expect(normaliseUrl("")).toBeNull(); });
  it("checks passwords", () => { expect(validatePassword("short1")).not.toBeNull(); expect(validatePassword("letters only")).not.toBeNull(); expect(validatePassword("Passw0rd!")).toBeNull(); });
  it("checks registration", () => { expect(validateRegister({ agency_name: "A", full_name: "", email: "x", password: "1" }).map((e) => e.field)).toEqual(["agency_name", "full_name", "email", "password"]); });
  it("checks clients", () => {
    const errs = validateClient({ company_name: "X", website: "not a url", contact_email: "bad", target_markets: [], budget_currency: "INR", marketing_budget: -5 });
    expect(errs.map((e) => e.field).sort()).toEqual(["company_name", "contact_email", "marketing_budget", "website"]);
  });
  it("checks files", () => {
    expect(validateFile({ name: "a.exe", size: 10 })).toMatch(/Only PDF/); expect(validateFile({ name: "a.pdf", size: 0 })).toMatch(/empty/);
    expect(validateFile({ name: "a.PNG", size: 100 })).toBeNull(); expect(validateFile({ name: "a.pdf", size: 30 * 1024 * 1024 })).toMatch(/larger/);
  });
});
