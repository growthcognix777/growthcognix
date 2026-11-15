"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { ApiError, type Client, type ClientInput, type FieldError } from "@/lib/types";
import { useAsync } from "@/lib/useAsync";
import { normaliseUrl, validateClient } from "@/lib/validate";
import { Button, Card, CardHeader, ErrorBox, Field, Input, Select, TagInput, Textarea } from "./ui";

const INDUSTRIES = ["Manufacturing", "Industrial equipment", "Water treatment", "Chemicals", "Food processing", "Pharmaceuticals", "Healthcare",
  "Textiles", "Automotive", "Construction", "Electronics", "Agriculture", "Logistics", "Retail", "Hospitality", "Education", "IT services", "Other"];
const TYPES = ["Manufacturer", "Exporter", "Distributor", "Trader", "Service provider", "Retailer", "OEM supplier", "Startup", "Other"];

const empty: ClientInput = { company_name: "", website: "", industry: "", business_type: "", description: "", address: "", contact_name: "",
  contact_email: "", contact_phone: "", target_markets: [], marketing_budget: null, budget_currency: "INR", business_objectives: "", assigned_user_id: "" };

export function ClientForm({ initial }: { initial?: Client }) {
  const router = useRouter();
  const users = useAsync(() => api.listUsers());
  const [v, setV] = useState<ClientInput>(initial ? { ...empty, ...initial } : empty);
  const [errs, setErrs] = useState<FieldError[]>([]); const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const fe = (f: string) => errs.find((e) => e.field === f)?.message;
  const set = (k: keyof ClientInput) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setV({ ...v, [k]: e.target.value });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setErr(null);
    const body: ClientInput = { ...v, website: normaliseUrl(v.website), budget_currency: v.budget_currency.toUpperCase(),
      marketing_budget: v.marketing_budget === null || (v.marketing_budget as unknown) === "" ? null : Number(v.marketing_budget),
      assigned_user_id: v.assigned_user_id || null };
    (Object.keys(body) as (keyof ClientInput)[]).forEach((k) => { if (body[k] === "") (body as unknown as Record<string, unknown>)[k] = null; });
    const ve = validateClient(body); setErrs(ve); if (ve.length) { window.scrollTo({ top: 0, behavior: "smooth" }); return; }
    setBusy(true);
    try {
      const saved = initial ? await api.updateClient(initial.id, body) : await api.createClient(body);
      router.push(`/clients/view/?id=${saved.id}`);
    } catch (e) { if (e instanceof ApiError) { setErr(e.message); setErrs(e.errors); } else setErr("Could not save the client"); }
    finally { setBusy(false); }
  };

  return (
    <form onSubmit={submit} noValidate className="space-y-6">
      {err && <Card><ErrorBox message={err} /></Card>}
      <Card>
        <CardHeader title="Company" subtitle="Who the client is and what they do." />
        <div className="grid gap-5 p-5 md:grid-cols-2">
          <Field label="Company name" required error={fe("company_name")}><Input value={v.company_name} onChange={set("company_name")} invalid={!!fe("company_name")} /></Field>
          <Field label="Website" error={fe("website")} hint="e.g. example.com"><Input value={v.website || ""} onChange={set("website")} invalid={!!fe("website")} /></Field>
          <Field label="Industry" error={fe("industry")}><Select value={v.industry || ""} onChange={set("industry")}><option value="">Select…</option>{INDUSTRIES.map((i) => <option key={i}>{i}</option>)}</Select></Field>
          <Field label="Business type" error={fe("business_type")}><Select value={v.business_type || ""} onChange={set("business_type")}><option value="">Select…</option>{TYPES.map((i) => <option key={i}>{i}</option>)}</Select></Field>
          <div className="md:col-span-2"><Field label="Description" error={fe("description")}><Textarea value={v.description || ""} onChange={set("description")} placeholder="What the company makes or offers, in its own words." /></Field></div>
          <div className="md:col-span-2"><Field label="Address" error={fe("address")}><Textarea className="min-h-[64px]" value={v.address || ""} onChange={set("address")} /></Field></div>
        </div>
      </Card>
      <Card>
        <CardHeader title="Primary contact" />
        <div className="grid gap-5 p-5 md:grid-cols-3">
          <Field label="Name" error={fe("contact_name")}><Input value={v.contact_name || ""} onChange={set("contact_name")} /></Field>
          <Field label="Email" error={fe("contact_email")}><Input type="email" value={v.contact_email || ""} onChange={set("contact_email")} invalid={!!fe("contact_email")} /></Field>
          <Field label="Phone" error={fe("contact_phone")}><Input value={v.contact_phone || ""} onChange={set("contact_phone")} invalid={!!fe("contact_phone")} placeholder="+91 …" /></Field>
        </div>
      </Card>
      <Card>
        <CardHeader title="Growth goals" subtitle="Used by later phases to plan research and campaigns." />
        <div className="grid gap-5 p-5 md:grid-cols-2">
          <div className="md:col-span-2"><Field label="Target markets" hint="Countries, states or cities. Press Enter after each."><TagInput value={v.target_markets} onChange={(t) => setV({ ...v, target_markets: t })} placeholder="e.g. Karnataka, UAE, Germany" /></Field></div>
          <div className="grid grid-cols-[1fr_96px] gap-3">
            <Field label="Monthly marketing budget" error={fe("marketing_budget")}><Input type="number" min={0} value={v.marketing_budget ?? ""} onChange={(e) => setV({ ...v, marketing_budget: e.target.value === "" ? null : Number(e.target.value) })} invalid={!!fe("marketing_budget")} /></Field>
            <Field label="Currency" error={fe("budget_currency")}><Input maxLength={3} value={v.budget_currency} onChange={(e) => setV({ ...v, budget_currency: e.target.value.toUpperCase() })} /></Field>
          </div>
          <Field label="Assigned agency staff" error={fe("assigned_user_id")}>
            <Select value={v.assigned_user_id || ""} onChange={set("assigned_user_id")}><option value="">Unassigned</option>{users.data?.map((u) => <option key={u.id} value={u.id}>{u.full_name} ({u.role})</option>)}</Select>
          </Field>
          <div className="md:col-span-2"><Field label="Business objectives" error={fe("business_objectives")}><Textarea value={v.business_objectives || ""} onChange={set("business_objectives")} placeholder="e.g. Enter UAE market, 20 new distributor leads per quarter." /></Field></div>
        </div>
      </Card>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={() => router.back()}>Cancel</Button>
        <Button type="submit" loading={busy}>{initial ? "Save changes" : "Create client"}</Button>
      </div>
    </form>
  );
}
