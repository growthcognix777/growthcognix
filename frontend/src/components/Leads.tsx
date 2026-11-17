"use client";
import { Check, Download, ExternalLink, Globe, MapPin, Pause, Play, Plus, RefreshCw, Search, Send, ShieldOff, Sparkles, Square, Trash2, UserPlus, X } from "lucide-react";
import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { CampaignInput } from "@/lib/api/contract";
import { useAuth } from "@/lib/auth";
import { fmtDate, fmtDateTime } from "@/lib/format";
import { BUYER_TYPE_LABEL, CLASS_LABEL, CLASS_TONE, DEFAULT_WEIGHTS, STATUS_LABEL, WEIGHT_LABEL } from "@/lib/leads";
import { ApiError, type BuyerType, type DiscoveryCampaign, type Finding, type GeoArea, type GeoLevel, type LeadVerification, type Prospect, type ProspectDetail, type ProspectInput, type ProspectQuery } from "@/lib/types";
import { useAsync } from "@/lib/useAsync";
import { Badge, Button, Card, CardHeader, Empty, ErrorBox, Field, Input, Modal, Select, Skeleton, Stat, Table, TagInput, Textarea, cx } from "./ui";

const SCREENS = ["Overview", "Buyer profiles", "Market explorer", "India districts & clusters", "International markets", "Campaigns",
  "Prospect database", "Prospect detail", "Lead scoring", "Verification queue", "Assignment", "Export & CRM"] as const;
type Screen = (typeof SCREENS)[number];
const RANK = { staff: 0, manager: 1, admin: 2, owner: 3 } as const;
const BUYER_TYPES = Object.keys(BUYER_TYPE_LABEL) as BuyerType[];
const LEVEL_LABEL: Record<GeoLevel, string> = { global: "Global", country: "Country", state: "State", district: "District", city: "City", industrial_area: "Industrial area / cluster" };
const LABEL = (k: string) => k.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
const short = (u?: string | null) => (u ? u.replace(/^https?:\/\//, "").replace(/\/$/, "") : "—");
const local = () => api.mode === "local";
const fail = (e: unknown) => alert(e instanceof Error ? e.message : "Failed");
const errText = (e: unknown) => (e instanceof ApiError || e instanceof Error ? e.message : "Something went wrong");
const statusTone = (s: LeadVerification) => (s === "rejected" ? "red" : s === "needs_review" ? "amber" : s === "discovered" ? "slate" : "green");

function save(name: string, blob: Blob) {
  const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = name; a.click(); URL.revokeObjectURL(url);
}
function Note({ children, tone = "amber" }: { children: React.ReactNode; tone?: "amber" | "blue" }) {
  return <div className={cx("m-5 rounded-lg border p-3 text-sm", tone === "amber" ? "border-amber-200 bg-amber-50 text-amber-800" : "border-brand-100 bg-brand-50 text-brand-800")}>{children}</div>;
}
function LocalNote() {
  if (!local()) return null;
  return <Note>This browser preview has no server, so it can&apos;t search the web, check company websites or call UN Comtrade, and no prospects are simulated. You can build buyer profiles and research areas, and add prospects you found yourself with their source. Run the backend for discovery campaigns.</Note>;
}
function ScoreBadge({ p }: { p: Pick<Prospect, "score_total" | "score_class"> }) {
  if (p.score_total === null || !p.score_class) return <span className="text-navy-400">—</span>;
  return <Badge tone={CLASS_TONE[p.score_class]}>{p.score_total} · {CLASS_LABEL[p.score_class]}</Badge>;
}
function Err({ msg }: { msg: string | null }) { return msg ? <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{msg}</div> : null; }

// ------------------------------------------------------------------ overview
function Overview({ clientId, go }: { clientId: string; go: (s: Screen) => void }) {
  const sum = useAsync(() => api.leadSummary(clientId), [clientId]);
  const prov = useAsync(() => api.leadProviders());
  const s = sum.data; const has = !!s && s.prospects > 0;
  const n = (v: number | undefined) => (has ? v ?? 0 : null);
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Prospects" value={n(s?.prospects)} hint={has ? "Discovered or added, not rejected" : "No campaign has run yet"} />
        <Stat label="Very high + high" value={n((s?.by_class.very_high || 0) + (s?.by_class.high || 0))} hint="Score 65 or more" />
        <Stat label="Approved for CRM" value={n((s?.by_crm.approved || 0) + (s?.by_crm.handed_off || 0))} hint="Verified by a person, then approved" />
        <Stat label="Average score" value={has && s?.avg_score != null ? Math.round(s.avg_score) : null} hint="Out of 100; confidence shown separately" />
      </div>
      <Card><CardHeader title="Workflow" subtitle="Every step needs a person before leads reach the CRM" />
        <ol className="grid gap-3 p-5 text-sm md:grid-cols-3">
          {([["Buyer profiles", "Who buys, by application and need. AI drafts are hypotheses until approved.", s?.profiles],
            ["Market explorer", "Countries, Indian states, districts, cities and industrial clusters to search.", s?.areas],
            ["Campaigns", "Search each profile in each area with the configured sources.", s ? Object.values(s.campaigns).reduce((a, b) => a + b, 0) : undefined],
            ["Verification queue", "Confirm company, industry, product relevance and contact with a source.", s?.by_status.needs_review],
            ["Lead scoring", "Fit 30, need 25, intent 20, capacity 15, contact 10 (editable).", undefined],
            ["Export & CRM", "Approved leads only, without do-not-contact entries.", undefined]] as [Screen, string, number | undefined][]).map(([t, d, c], i) => (
            <li key={t}><button onClick={() => go(t)} className="h-full w-full rounded-lg border border-line p-4 text-left hover:border-brand-300 hover:bg-brand-50/40">
              <div className="flex items-center justify-between"><span className="font-medium text-navy-900">{i + 1}. {t}</span>{c !== undefined && <Badge>{c}</Badge>}</div>
              <p className="mt-1 text-navy-500">{d}</p></button></li>))}
        </ol></Card>
      <Card><CardHeader title="Discovery sources" subtitle="Keys live on the server only. Unconfigured sources are skipped, never simulated." />
        {prov.loading ? <Skeleton rows={3} /> : prov.error ? <ErrorBox message={prov.error} /> : (
          <Table head={["Source", "Status", "Today", "Cost / note"]}>
            {prov.data!.providers.map((p) => <tr key={p.key}><td className="px-5 py-2.5 font-medium text-navy-900">{p.label}</td>
              <td className="px-5 py-2.5"><Badge tone={p.configured ? "green" : p.status === "retired" ? "red" : p.status === "manual_only" ? "amber" : "slate"}>{LABEL(p.status)}</Badge></td>
              <td className="px-5 py-2.5 text-navy-600">{p.daily_limit ? `${p.used_today ?? 0} / ${p.daily_limit}` : "—"}</td>
              <td className="px-5 py-2.5 text-xs text-navy-500">{p.note || p.cost || "—"}</td></tr>)}
          </Table>)}
      </Card>
    </div>
  );
}

// ------------------------------------------------------------------ buyer profiles
const EMPTY_PROFILE = { name: "", buyer_type: "end_user", industry: "", industry_relation: "direct", company_types: [] as string[], application_categories: [] as string[],
  problems_solved: [] as string[], job_titles: [] as string[], substitutes: [] as string[], geography: [] as string[], rationale: "", product_id: "" };
function Profiles({ clientId, role }: { clientId: string; role: number }) {
  const rows = useAsync(() => api.listBuyerProfiles(clientId), [clientId]);
  const products = useAsync(() => api.listProducts({ client_id: clientId }), [clientId]);
  const [open, setOpen] = useState(false); const [v, setV] = useState(EMPTY_PROFILE); const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setErr(null); setBusy(true);
    try { await api.createFinding(clientId, "persona", { data: { ...v, product_id: v.product_id || null } }); setOpen(false); setV(EMPTY_PROFILE); rows.reload(); }
    catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  };
  const gen = async () => { setBusy(true); try { const r = await api.generateBuyerProfiles(clientId, {}); alert(`${r.created} buyer profile hypotheses created. Review and approve them before searching.`); rows.reload(); } catch (e) { fail(e); } finally { setBusy(false); } };
  const review = async (f: Finding, action: "approve" | "reject") => { try { await api.reviewFinding("persona", f.id, action); rows.reload(); } catch (e) { fail(e); } };
  const list = (x: unknown) => (Array.isArray(x) && x.length ? (x as string[]).join(", ") : "—");
  return (
    <Card><CardHeader title="Buyer profiles" subtitle="Think by application and operational need. AI drafts stay hypotheses until a manager approves them."
      action={<div className="flex gap-2">{role >= 1 && <Button variant="secondary" size="sm" loading={busy} onClick={gen}><Sparkles className="h-4 w-4" />Generate with AI</Button>}
        <Button size="sm" onClick={() => setOpen(true)}><Plus className="h-4 w-4" />Add profile</Button></div>} />
      {local() && <Note>AI generation needs the backend and a Gemini or Groq key. Profiles you add by hand work here.</Note>}
      {rows.loading ? <Skeleton /> : rows.error ? <ErrorBox message={rows.error} onRetry={rows.reload} /> : !rows.data!.length ? (
        <Empty title="No buyer profiles yet" body="Add who buys the product: their industry, company type, the application and the problem it solves." />
      ) : (
        <div className="divide-y divide-line">{rows.data!.map((f) => { const d = f.data as Record<string, unknown>; return (
          <div key={f.id} className="p-5 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2"><span className="font-medium text-navy-950">{String(d.name)}</span>
                {d.buyer_type ? <Badge tone="blue">{BUYER_TYPE_LABEL[String(d.buyer_type)] || String(d.buyer_type)}</Badge> : null}
                {d.industry_relation ? <Badge>{LABEL(String(d.industry_relation))} industry</Badge> : null}
                <Badge tone={f.approved ? "green" : f.origin === "user" ? "blue" : "violet"}>{f.approved ? "Approved" : f.origin === "user" ? "Added by team" : "AI hypothesis"}</Badge></div>
              {role >= 1 && <div className="flex gap-1">{!f.approved && <Button size="sm" variant="secondary" onClick={() => review(f, "approve")}><Check className="h-4 w-4" />Approve</Button>}
                <Button size="sm" variant="secondary" onClick={() => review(f, "reject")}><X className="h-4 w-4" />Reject</Button></div>}
            </div>
            <dl className="mt-3 grid gap-x-6 gap-y-1 text-navy-600 md:grid-cols-2">
              <div><dt className="inline text-navy-400">Industry: </dt><dd className="inline">{String(d.industry || "—")}</dd></div>
              <div><dt className="inline text-navy-400">Company types: </dt><dd className="inline">{list(d.company_types)}</dd></div>
              <div><dt className="inline text-navy-400">Applications: </dt><dd className="inline">{list(d.application_categories)}</dd></div>
              <div><dt className="inline text-navy-400">Problems solved: </dt><dd className="inline">{list(d.problems_solved)}</dd></div>
              <div><dt className="inline text-navy-400">Decision-makers: </dt><dd className="inline">{list(d.job_titles)}</dd></div>
              <div><dt className="inline text-navy-400">Substitutes: </dt><dd className="inline">{list(d.substitutes)}</dd></div>
            </dl>
            {d.rationale ? <p className="mt-2 text-navy-500">Why: {String(d.rationale)}</p> : null}
          </div>); })}</div>)}
      <Modal open={open} onClose={() => setOpen(false)} title="Add buyer profile">
        <form onSubmit={submit} className="space-y-4">
          <Err msg={err} />
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Profile name" required><Input value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} placeholder="Dairy plants with steam boilers" /></Field>
            <Field label="Product"><Select value={v.product_id} onChange={(e) => setV({ ...v, product_id: e.target.value })}><option value="">All products</option>
              {products.data?.items.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select></Field>
            <Field label="Buyer type"><Select value={v.buyer_type} onChange={(e) => setV({ ...v, buyer_type: e.target.value })}>{BUYER_TYPES.map((b) => <option key={b} value={b}>{BUYER_TYPE_LABEL[b]}</option>)}</Select></Field>
            <Field label="Industry"><Input value={v.industry} onChange={(e) => setV({ ...v, industry: e.target.value })} placeholder="Dairy" /></Field>
            <Field label="Industry relation" hint="Indirect: the industry is not named for the product, but needs it"><Select value={v.industry_relation} onChange={(e) => setV({ ...v, industry_relation: e.target.value })}><option value="direct">Direct</option><option value="indirect">Indirect</option></Select></Field>
            <Field label="Company types" hint="Used as search phrases. Press Enter after each."><TagInput value={v.company_types} onChange={(t) => setV({ ...v, company_types: t })} /></Field>
            <Field label="Applications" hint="Also searched"><TagInput value={v.application_categories} onChange={(t) => setV({ ...v, application_categories: t })} /></Field>
            <Field label="Problems the product solves" hint="Matched on prospect sites as need"><TagInput value={v.problems_solved} onChange={(t) => setV({ ...v, problems_solved: t })} /></Field>
            <Field label="Decision-maker roles"><TagInput value={v.job_titles} onChange={(t) => setV({ ...v, job_titles: t })} /></Field>
            <Field label="Substitutes they use today"><TagInput value={v.substitutes} onChange={(t) => setV({ ...v, substitutes: t })} /></Field>
          </div>
          <Field label="Rationale"><Textarea rows={2} value={v.rationale} onChange={(e) => setV({ ...v, rationale: e.target.value })} /></Field>
          <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" loading={busy}>Save profile</Button></div>
        </form>
      </Modal>
    </Card>
  );
}

// ------------------------------------------------------------------ geographies
function AreaForm({ clientId, areas, onSaved, fixedLevel, parentFilter }: { clientId: string; areas: GeoArea[]; onSaved: () => void; fixedLevel?: GeoLevel[]; parentFilter?: (g: GeoArea) => boolean }) {
  const levels = fixedLevel || (["global", "country", "state", "district", "city", "industrial_area"] as GeoLevel[]);
  const [v, setV] = useState({ level: levels[0], name: "", parent_id: "", source_url: "", notes: "" });
  const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const parents = areas.filter((a) => (parentFilter ? parentFilter(a) : true) && ({ country: ["global"], state: ["country"], district: ["state"], city: ["district", "state"], industrial_area: ["city", "district", "state"] } as Record<string, string[]>)[v.level]?.includes(a.level));
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setErr(null); setBusy(true);
    try { await api.addGeo(clientId, { level: v.level, name: v.name, parent_id: v.parent_id || null, source_url: v.source_url || null, notes: v.notes || null }); setV({ ...v, name: "", source_url: "", notes: "" }); onSaved(); }
    catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  };
  return (
    <form onSubmit={submit} className="space-y-3 p-5">
      <Err msg={err} />
      <div className="grid gap-3 md:grid-cols-4">
        <Field label="Level"><Select value={v.level} onChange={(e) => setV({ ...v, level: e.target.value as GeoLevel, parent_id: "" })}>{levels.map((l) => <option key={l} value={l}>{LEVEL_LABEL[l]}</option>)}</Select></Field>
        {!["global", "country"].includes(v.level) && <Field label="Inside" required><Select value={v.parent_id} onChange={(e) => setV({ ...v, parent_id: e.target.value })}><option value="">Choose…</option>
          {parents.map((p) => <option key={p.id} value={p.id}>{p.path.join(" > ")}</option>)}</Select></Field>}
        <Field label="Name" required><Input value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} placeholder={v.level === "industrial_area" ? "Udyambag Industrial Area" : v.level === "country" ? "India" : ""} /></Field>
        <Field label="Source URL" hint="e.g. the estate list"><Input value={v.source_url} onChange={(e) => setV({ ...v, source_url: e.target.value })} /></Field>
      </div>
      <div className="flex justify-end"><Button type="submit" size="sm" loading={busy}><Plus className="h-4 w-4" />Save area</Button></div>
    </form>
  );
}
function AreaTree({ areas, onDelete, filter }: { areas: GeoArea[]; onDelete: (id: string) => void; filter?: (g: GeoArea) => boolean }) {
  const rows = [...areas].filter((a) => !filter || filter(a)).sort((a, b) => a.path.join(">").localeCompare(b.path.join(">")));
  if (!rows.length) return <Empty title="No research areas saved" body="Add the places you want to search. Nothing is pre-filled beyond official country and state names." icon={<MapPin className="h-5 w-5" />} />;
  return <Table head={["Area", "Level", "Source", ""]}>{rows.map((a) => <tr key={a.id}>
    <td className="px-5 py-2.5" style={{ paddingLeft: 20 + Math.max(0, a.path.length - 1) * 16 }}><span className="font-medium text-navy-900">{a.name}</span>{a.path.length > 1 && <span className="ml-2 text-xs text-navy-400">{a.path.slice(0, -1).join(" > ")}</span>}</td>
    <td className="px-5 py-2.5 text-navy-600">{LEVEL_LABEL[a.level]}</td>
    <td className="px-5 py-2.5">{a.source_url ? <a className="inline-flex items-center gap-1 text-brand-600 hover:underline" href={a.source_url} target="_blank" rel="noopener noreferrer">{short(a.source_url).slice(0, 40)}<ExternalLink className="h-3 w-3" /></a> : "—"}</td>
    <td className="px-5 py-2.5 text-right"><button aria-label="Delete area" onClick={() => confirm(`Delete ${a.name} and the areas inside it?`) && onDelete(a.id)} className="text-navy-400 hover:text-red-600"><Trash2 className="h-4 w-4" /></button></td></tr>)}</Table>;
}
function Markets({ clientId }: { clientId: string }) {
  const areas = useAsync(() => api.listGeos(clientId), [clientId]);
  const del = async (id: string) => { try { await api.deleteGeo(id); areas.reload(); } catch (e) { fail(e); } };
  return <Card><CardHeader title="Geographic market explorer" subtitle="Global > Country > State > District > City > Industrial area" />
    <AreaForm clientId={clientId} areas={areas.data || []} onSaved={areas.reload} />
    {areas.loading ? <Skeleton /> : areas.error ? <ErrorBox message={areas.error} /> : <AreaTree areas={areas.data!} onDelete={del} />}</Card>;
}
function IndiaExplorer({ clientId }: { clientId: string }) {
  const areas = useAsync(() => api.listGeos(clientId), [clientId]);
  const ref = useAsync(() => api.geoReference());
  const [state, setState] = useState(""); const [busy, setBusy] = useState(false);
  const india = areas.data?.find((a) => a.level === "country" && a.country_code === "IN");
  const inIndia = (g: GeoArea) => g.path[0] === "India";
  const addState = async () => {
    setBusy(true);
    try {
      const country = india || await api.addGeo(clientId, { level: "country", name: "India" });
      await api.addGeo(clientId, { level: "state", name: state, parent_id: country.id }); setState(""); areas.reload();
    } catch (e) { fail(e); } finally { setBusy(false); }
  };
  const del = async (id: string) => { try { await api.deleteGeo(id); areas.reload(); } catch (e) { fail(e); } };
  return <div className="space-y-6">
    <Card><CardHeader title="Add a state or union territory" subtitle="Official names only, so searches and filters match" />
      <div className="flex flex-wrap items-end gap-3 p-5">
        <div className="min-w-[260px] flex-1"><Field label="State / UT"><Select value={state} onChange={(e) => setState(e.target.value)}><option value="">Choose…</option>
          {ref.data && <><optgroup label="States">{ref.data.india.states.map((s) => <option key={s}>{s}</option>)}</optgroup><optgroup label="Union territories">{ref.data.india.union_territories.map((s) => <option key={s}>{s}</option>)}</optgroup></>}</Select></Field></div>
        <Button onClick={addState} loading={busy} disabled={!state}><Plus className="h-4 w-4" />Add</Button>
      </div>
      <p className="px-5 pb-5 text-xs text-navy-500">{ref.data?.india.note} <a className="text-brand-600 hover:underline" href="https://lgdirectory.gov.in/" target="_blank" rel="noopener noreferrer">lgdirectory.gov.in</a></p></Card>
    <Card><CardHeader title="Districts, cities and industrial clusters" subtitle="Add a source URL for clusters, such as the state industrial development corporation's estate list" />
      <AreaForm clientId={clientId} areas={areas.data || []} onSaved={areas.reload} fixedLevel={["district", "city", "industrial_area"]} parentFilter={inIndia} />
      {areas.loading ? <Skeleton /> : <AreaTree areas={areas.data || []} onDelete={del} filter={inIndia} />}</Card>
  </div>;
}

// ------------------------------------------------------------------ international markets + trade data
function International({ clientId }: { clientId: string }) {
  const areas = useAsync(() => api.listGeos(clientId), [clientId]);
  const ref = useAsync(() => api.geoReference());
  const ins = useAsync(() => api.listMarketInsights(clientId), [clientId]);
  const products = useAsync(() => api.listProducts({ client_id: clientId }), [clientId]);
  const [ct, setCt] = useState({ hs_code: "", reporter: "", period: String(new Date().getFullYear() - 2), flow: "M" as "M" | "X", partner: "", product_id: "" });
  const [mi, setMi] = useState({ kind: "tariff", title: "", detail: "", source_url: "", product_id: "" });
  const [country, setCountry] = useState(""); const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<unknown>) => { setErr(null); setBusy(true); try { await fn(); ins.reload(); areas.reload(); } catch (e) { setErr(errText(e)); } finally { setBusy(false); } };
  const fmtUsd = (n: number | null) => (n === null ? "—" : n >= 1e9 ? `$${(n / 1e9).toFixed(2)} bn` : n >= 1e6 ? `$${(n / 1e6).toFixed(1)} m` : `$${Math.round(n).toLocaleString()}`);
  return <div className="space-y-6">
    <Card><CardHeader title="Target countries" subtitle="Saved as research areas for campaigns" />
      <div className="flex flex-wrap items-end gap-3 p-5">
        <div className="min-w-[240px] flex-1"><Field label="Country"><Select value={country} onChange={(e) => setCountry(e.target.value)}><option value="">Choose…</option>{ref.data?.countries.map((c) => <option key={c.code} value={c.name}>{c.name}</option>)}</Select></Field></div>
        <Button loading={busy} disabled={!country} onClick={() => run(() => api.addGeo(clientId, { level: "country", name: country }))}><Plus className="h-4 w-4" />Add country</Button>
      </div>
      <div className="flex flex-wrap gap-2 px-5 pb-5">{areas.data?.filter((a) => a.level === "country").map((a) => <Badge key={a.id} tone="blue">{a.name}</Badge>)}</div></Card>
    <Card><CardHeader title="UN Comtrade trade statistics" subtitle="Historical annual trade reported by countries. Not current demand, and not revenue a client can win." />
      {local() && <Note>UN Comtrade is called from the backend only.</Note>}
      <div className="grid gap-3 p-5 md:grid-cols-6">
        <Field label="HS code"><Input value={ct.hs_code} onChange={(e) => setCt({ ...ct, hs_code: e.target.value })} placeholder="8413" /></Field>
        <Field label="Reporter"><Input value={ct.reporter} onChange={(e) => setCt({ ...ct, reporter: e.target.value })} placeholder="India or IN" /></Field>
        <Field label="Year"><Input value={ct.period} onChange={(e) => setCt({ ...ct, period: e.target.value })} /></Field>
        <Field label="Flow"><Select value={ct.flow} onChange={(e) => setCt({ ...ct, flow: e.target.value as "M" | "X" })}><option value="M">Imports</option><option value="X">Exports</option></Select></Field>
        <Field label="Partner" hint="Empty = World"><Input value={ct.partner} onChange={(e) => setCt({ ...ct, partner: e.target.value })} /></Field>
        <div className="flex items-end"><Button loading={busy} onClick={() => run(() => api.fetchComtrade(clientId, { ...ct, partner: ct.partner || null, product_id: ct.product_id || null }))}><Globe className="h-4 w-4" />Fetch</Button></div>
      </div>
      <p className="px-5 pb-3 text-xs text-navy-500">Free public preview: no key, up to 500 rows per call, about one request per second.</p>
      <div className="px-5"><Err msg={err} /></div>
      <CardHeader title="Add a market insight" subtitle="Tariffs, certifications, regulations, logistics, trade agreements or a current demand signal, always with its source" />
      <div className="grid gap-3 p-5 md:grid-cols-4">
        <Field label="Type"><Select value={mi.kind} onChange={(e) => setMi({ ...mi, kind: e.target.value })}>{["current_demand", "tariff", "certification", "regulation", "logistics", "trade_agreement", "hs_code"].map((k) => <option key={k} value={k}>{LABEL(k)}</option>)}</Select></Field>
        <Field label="Title" required><Input value={mi.title} onChange={(e) => setMi({ ...mi, title: e.target.value })} /></Field>
        <Field label="Source URL" required><Input value={mi.source_url} onChange={(e) => setMi({ ...mi, source_url: e.target.value })} /></Field>
        <Field label="Product"><Select value={mi.product_id} onChange={(e) => setMi({ ...mi, product_id: e.target.value })}><option value="">—</option>{products.data?.items.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select></Field>
        <div className="md:col-span-3"><Field label="Detail"><Input value={mi.detail} onChange={(e) => setMi({ ...mi, detail: e.target.value })} /></Field></div>
        <div className="flex items-end"><Button variant="secondary" loading={busy} onClick={() => run(async () => { await api.addMarketInsight(clientId, { ...mi, detail: mi.detail || null, product_id: mi.product_id || null }); setMi({ ...mi, title: "", detail: "", source_url: "" }); })}><Plus className="h-4 w-4" />Add</Button></div>
      </div>
      {ins.loading ? <Skeleton /> : !ins.data?.length ? <Empty title="No market data yet" body="Fetch UN Comtrade figures or add an insight with its source." /> : (
        <Table head={["Insight", "Type", "Value", "Source", ""]}>{ins.data.map((i) => <tr key={i.id}>
          <td className="px-5 py-2.5"><div className="font-medium text-navy-900">{i.title}</div>{i.detail && <div className="text-xs text-navy-500">{i.detail}</div>}</td>
          <td className="px-5 py-2.5"><Badge tone={i.kind === "historical_trade" ? "slate" : "blue"}>{LABEL(i.kind)}</Badge></td>
          <td className="px-5 py-2.5 text-navy-700">{i.kind === "historical_trade" ? fmtUsd(i.value_usd) : "—"}</td>
          <td className="px-5 py-2.5">{i.source_url ? <a href={i.source_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-brand-600 hover:underline">{i.source === "un_comtrade" ? "UN Comtrade" : short(i.source_url).slice(0, 30)}<ExternalLink className="h-3 w-3" /></a> : "—"}</td>
          <td className="px-5 py-2.5 text-right"><button aria-label="Delete insight" className="text-navy-400 hover:text-red-600" onClick={() => api.deleteMarketInsight(i.id).then(ins.reload, fail)}><Trash2 className="h-4 w-4" /></button></td></tr>)}</Table>)}
    </Card>
  </div>;
}

// ------------------------------------------------------------------ campaigns
function Campaigns({ clientId, role, openProspects }: { clientId: string; role: number; openProspects: (q: ProspectQuery) => void }) {
  const rows = useAsync(() => api.listLeadCampaigns(clientId), [clientId]);
  const profiles = useAsync(() => api.listBuyerProfiles(clientId), [clientId]);
  const areas = useAsync(() => api.listGeos(clientId), [clientId]);
  const prov = useAsync(() => api.leadProviders());
  const [open, setOpen] = useState(false); const [sel, setSel] = useState<DiscoveryCampaign | null>(null);
  const [v, setV] = useState<CampaignInput>({ name: "", persona_ids: [], geography_ids: [], sources: [], directory_urls: [], results_per_query: 10, max_companies: 200 });
  const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const targets = useAsync(() => (sel ? api.leadCampaignTargets(sel.id) : Promise.resolve([])), [sel?.id]);
  const usable = profiles.data?.filter((f) => f.approved || f.origin === "user") || [];
  const sources = prov.data?.providers.filter((p) => ["search", "directory"].includes(p.kind)) || [];
  const toggle = (k: "persona_ids" | "geography_ids" | "sources", id: string) => setV({ ...v, [k]: v[k].includes(id) ? v[k].filter((x) => x !== id) : [...v[k], id] });
  const create = async (e: React.FormEvent) => {
    e.preventDefault(); setErr(null); setBusy(true);
    try { const c = await api.createLeadCampaign(clientId, v); setOpen(false); setSel(c); rows.reload(); } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  };
  const act = async (fn: () => Promise<DiscoveryCampaign>) => { try { const c = await fn(); setSel(c); rows.reload(); } catch (e) { fail(e); } };
  return <div className="space-y-6">
    <Card><CardHeader title="Discovery campaigns" subtitle="Each buyer profile is searched in each area with each source. Finished searches are kept if you pause or a source fails."
      action={role >= 1 && <Button size="sm" onClick={() => setOpen(true)} disabled={local()}><Plus className="h-4 w-4" />New campaign</Button>} />
      <LocalNote />
      {rows.loading ? <Skeleton /> : rows.error ? <ErrorBox message={rows.error} /> : !rows.data!.length ? <Empty title="No campaigns yet" body="Approve buyer profiles and save research areas, then start a campaign." icon={<Search className="h-5 w-5" />} /> : (
        <Table head={["Campaign", "Status", "Progress", "Found", "Created", ""]}>{rows.data!.map((c) => <tr key={c.id} className={cx("cursor-pointer hover:bg-canvas/60", sel?.id === c.id && "bg-brand-50/40")} onClick={() => setSel(c)}>
          <td className="px-5 py-2.5 font-medium text-navy-900">{c.name}</td>
          <td className="px-5 py-2.5"><Badge tone={c.status === "completed" ? "green" : c.status === "failed" ? "red" : c.status === "paused" ? "amber" : c.status === "cancelled" ? "slate" : "blue"}>{LABEL(c.status)}</Badge></td>
          <td className="px-5 py-2.5"><div className="h-1.5 w-24 rounded bg-canvas"><div className="h-1.5 rounded bg-brand-600" style={{ width: `${c.progress}%` }} /></div></td>
          <td className="px-5 py-2.5 text-navy-700">{c.counts.new_prospects ?? 0}</td>
          <td className="px-5 py-2.5 text-navy-500">{fmtDate(c.created_at)}</td>
          <td className="px-5 py-2.5 text-right" onClick={(e) => e.stopPropagation()}><div className="flex justify-end gap-1">
            {role >= 1 && ["draft", "paused", "failed", "completed"].includes(c.status) && <Button size="sm" variant="secondary" onClick={() => act(() => api.startLeadCampaign(c.id))}><Play className="h-4 w-4" />{c.status === "draft" ? "Start" : "Resume"}</Button>}
            {["queued", "running"].includes(c.status) && <Button size="sm" variant="secondary" onClick={() => act(() => api.pauseLeadCampaign(c.id))}><Pause className="h-4 w-4" />Pause</Button>}
            {!["completed", "cancelled"].includes(c.status) && <Button size="sm" variant="secondary" onClick={() => confirm("Cancel this campaign? Prospects found so far are kept.") && act(() => api.cancelLeadCampaign(c.id))}><Square className="h-4 w-4" />Cancel</Button>}
          </div></td></tr>)}</Table>)}
    </Card>
    {sel && <Card><CardHeader title={sel.name} subtitle={sel.error || (sel.stage ? `Stage: ${sel.stage}` : `Status: ${LABEL(sel.status)}`)}
      action={<div className="flex gap-2"><Button size="sm" variant="secondary" onClick={() => api.getLeadCampaign(sel.id).then((c) => { setSel(c); targets.reload(); }, fail)}><RefreshCw className="h-4 w-4" />Refresh</Button>
        <Button size="sm" variant="secondary" onClick={() => openProspects({ campaign_id: sel.id })}>View prospects</Button></div>} />
      <div className="flex flex-wrap gap-2 px-5 pt-4 text-xs">{Object.entries(sel.counts).map(([k, n]) => <Badge key={k}>{LABEL(k)}: {n}</Badge>)}</div>
      {targets.loading ? <Skeleton /> : <Table head={["Search", "Source", "Status", "Results", "New", "Note"]}>{(targets.data || []).map((t) => <tr key={t.id}>
        <td className="px-5 py-2 text-navy-900">{t.query}</td><td className="px-5 py-2 text-navy-600">{t.provider}</td>
        <td className="px-5 py-2"><Badge tone={t.status === "done" ? "green" : t.status === "failed" ? "red" : "slate"}>{LABEL(t.status)}</Badge></td>
        <td className="px-5 py-2">{t.results_count}</td><td className="px-5 py-2">{t.new_prospects}</td><td className="px-5 py-2 text-xs text-navy-500">{t.error || "—"}</td></tr>)}</Table>}
    </Card>}
    <Modal open={open} onClose={() => setOpen(false)} title="New discovery campaign">
      <form onSubmit={create} className="space-y-4">
        <Err msg={err} />
        <Field label="Name" required><Input value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} placeholder="Belagavi dairies, Q1" /></Field>
        <Field label="Buyer profiles" hint="Approved or team-added profiles only">{!usable.length ? <p className="text-sm text-navy-500">Approve a buyer profile first.</p> :
          <div className="space-y-1">{usable.map((f) => <label key={f.id} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={v.persona_ids.includes(f.id)} onChange={() => toggle("persona_ids", f.id)} />{String(f.data.name)}</label>)}</div>}</Field>
        <Field label="Research areas" hint="None selected searches without a place">{!areas.data?.length ? <p className="text-sm text-navy-500">No areas saved yet.</p> :
          <div className="grid max-h-40 gap-1 overflow-y-auto md:grid-cols-2">{areas.data.map((a) => <label key={a.id} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={v.geography_ids.includes(a.id)} onChange={() => toggle("geography_ids", a.id)} />{a.path.join(" > ") || "Global"}</label>)}</div>}</Field>
        <Field label="Sources"><div className="space-y-1">{sources.map((s) => <label key={s.key} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={v.sources.includes(s.key)} onChange={() => toggle("sources", s.key)} />{s.label}
          <Badge tone={s.configured ? "green" : "slate"}>{s.configured ? "Configured" : "Not configured"}</Badge></label>)}</div></Field>
        {v.sources.includes("directory") && <Field label="Directory URLs" hint="Public member or exhibitor lists you may use. robots.txt is obeyed."><TagInput value={v.directory_urls || []} onChange={(t) => setV({ ...v, directory_urls: t })} /></Field>}
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Results per search"><Input type="number" min={1} max={20} value={v.results_per_query} onChange={(e) => setV({ ...v, results_per_query: Number(e.target.value) })} /></Field>
          <Field label="Max new companies"><Input type="number" min={1} max={1000} value={v.max_companies} onChange={(e) => setV({ ...v, max_companies: Number(e.target.value) })} /></Field>
        </div>
        <p className="text-xs text-navy-500">Search results only make a company &quot;discovered&quot;. The worker then reads each company&apos;s own site (robots-aware) for application terms, buying signals and published role contacts. Marketplace and social pages are skipped.</p>
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" loading={busy}>Create campaign</Button></div>
      </form>
    </Modal>
  </div>;
}

// ------------------------------------------------------------------ prospects
const EMPTY_PROSPECT: ProspectInput = { name: "", website: "", source_url: "", buyer_type: null, industry: "", country: "India", state: "", district: "", city: "", industrial_area: "", note: "" };
function ProspectModal({ clientId, onClose, onSaved }: { clientId: string; onClose: () => void; onSaved: (p: Prospect) => void }) {
  const [v, setV] = useState<ProspectInput>(EMPTY_PROSPECT); const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const f = (k: keyof ProspectInput) => (e: React.ChangeEvent<HTMLInputElement>) => setV({ ...v, [k]: e.target.value });
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setErr(null); setBusy(true);
    try { const p = await api.addProspect(clientId, { ...v, website: v.website || null, buyer_type: v.buyer_type || null }); onSaved(p); onClose(); } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  };
  return <Modal open onClose={onClose} title="Add a prospect you found">
    <form onSubmit={submit} className="space-y-4">
      <Err msg={err} />
      <div className="grid gap-4 md:grid-cols-2">
        <Field label="Company name" required><Input value={v.name} onChange={f("name")} /></Field>
        <Field label="Company website" hint="Its own site, not a listing page"><Input value={v.website || ""} onChange={f("website")} /></Field>
        <div className="md:col-span-2"><Field label="Where you found it" required hint="A public URL: directory, tender, news item, association list"><Input value={v.source_url} onChange={f("source_url")} /></Field></div>
        <Field label="Buyer type"><Select value={v.buyer_type || ""} onChange={(e) => setV({ ...v, buyer_type: (e.target.value || null) as BuyerType | null })}><option value="">—</option>{BUYER_TYPES.map((b) => <option key={b} value={b}>{BUYER_TYPE_LABEL[b]}</option>)}</Select></Field>
        <Field label="Industry"><Input value={v.industry || ""} onChange={f("industry")} /></Field>
        <Field label="Country"><Input value={v.country || ""} onChange={f("country")} /></Field>
        <Field label="State"><Input value={v.state || ""} onChange={f("state")} /></Field>
        <Field label="District"><Input value={v.district || ""} onChange={f("district")} /></Field>
        <Field label="City"><Input value={v.city || ""} onChange={f("city")} /></Field>
      </div>
      <Field label="Why it may fit"><Textarea rows={2} value={v.note || ""} onChange={(e) => setV({ ...v, note: e.target.value })} /></Field>
      <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" loading={busy}>Add prospect</Button></div>
    </form>
  </Modal>;
}
function ProspectTable({ rows, onOpen, selected, onSelect, users }: { rows: Prospect[]; onOpen: (id: string) => void; selected?: Set<string>; onSelect?: (id: string) => void; users?: Record<string, string> }) {
  return <Table head={[...(onSelect ? [""] : []), "Company", "Area searched", "Buyer type", "Status", "Score", "Confidence", ...(users ? ["Assigned"] : [])]}>
    {rows.map((p) => <tr key={p.id} className="hover:bg-canvas/60">
      {onSelect && <td className="px-5 py-2.5"><input type="checkbox" aria-label={`Select ${p.name}`} checked={selected?.has(p.id)} onChange={() => onSelect(p.id)} /></td>}
      <td className="px-5 py-2.5"><button className="text-left font-medium text-navy-900 hover:text-brand-700" onClick={() => onOpen(p.id)}>{p.name}</button><div className="text-xs text-navy-500">{p.domain || "no website"}</div></td>
      <td className="px-5 py-2.5 text-navy-600">{[p.district, p.state, p.country].filter(Boolean).join(", ") || p.searched_area[0]?.slice(-2).reverse().join(", ") || "—"}</td>
      <td className="px-5 py-2.5 text-navy-600">{p.buyer_type ? BUYER_TYPE_LABEL[p.buyer_type] : "—"}</td>
      <td className="px-5 py-2.5"><Badge tone={statusTone(p.verification_status)}>{STATUS_LABEL[p.verification_status]}</Badge></td>
      <td className="px-5 py-2.5"><ScoreBadge p={p} /></td>
      <td className="px-5 py-2.5 text-navy-600">{p.confidence === null ? "—" : `${Math.round(p.confidence * 100)}%`}</td>
      {users && <td className="px-5 py-2.5 text-navy-600">{p.assigned_to ? users[p.assigned_to] || "—" : "—"}</td>}
    </tr>)}
  </Table>;
}
function Database({ clientId, initial, onOpen }: { clientId: string; initial: ProspectQuery; onOpen: (id: string) => void }) {
  const [q, setQ] = useState<ProspectQuery>({ sort: "score", ...initial }); const [adding, setAdding] = useState(false);
  const rows = useAsync(() => api.listProspects(clientId, q), [clientId, JSON.stringify(q)]);
  const products = useAsync(() => api.listProducts({ client_id: clientId }), [clientId]);
  const set = (k: keyof ProspectQuery) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setQ({ ...q, [k]: e.target.value || undefined });
  return <Card><CardHeader title="Prospect database" subtitle={rows.data ? `${rows.data.total} prospect(s)` : undefined} action={<Button size="sm" onClick={() => setAdding(true)}><Plus className="h-4 w-4" />Add prospect</Button>} />
    <div className="grid gap-3 border-b border-line p-5 md:grid-cols-4 lg:grid-cols-6">
      <Input placeholder="Search name or domain" value={q.q || ""} onChange={set("q")} />
      <Input placeholder="State" value={q.state || ""} onChange={set("state")} />
      <Input placeholder="District" value={q.district || ""} onChange={set("district")} />
      <Input placeholder="Industry" value={q.industry || ""} onChange={set("industry")} />
      <Select value={q.product_id || ""} onChange={set("product_id")}><option value="">All products</option>{products.data?.items.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select>
      <Select value={q.buyer_type || ""} onChange={set("buyer_type")}><option value="">All buyer types</option>{BUYER_TYPES.map((b) => <option key={b} value={b}>{BUYER_TYPE_LABEL[b]}</option>)}</Select>
      <Select value={q.score_class || ""} onChange={set("score_class")}><option value="">Any score</option>{Object.entries(CLASS_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select>
      <Select value={q.verification || ""} onChange={set("verification")}><option value="">Any status</option>{Object.entries(STATUS_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select>
      <Select value={q.source || ""} onChange={set("source")}><option value="">Any source</option>{["searxng", "google_pse", "brave", "directory", "manual"].map((s) => <option key={s} value={s}>{s}</option>)}</Select>
      <Select value={q.sort} onChange={set("sort")}><option value="score">Highest score</option><option value="recent">Newest</option><option value="name">Name</option></Select>
      {q.campaign_id && <button className="text-left text-sm text-brand-600" onClick={() => setQ({ ...q, campaign_id: undefined })}>Clear campaign filter ×</button>}
    </div>
    {rows.loading ? <Skeleton /> : rows.error ? <ErrorBox message={rows.error} /> : !rows.data!.items.length ? <Empty title="No prospects match" body={local() ? "In this preview, add prospects you found yourself with their source." : "Run a discovery campaign or add a prospect with its source."} /> : <ProspectTable rows={rows.data!.items} onOpen={onOpen} />}
    {adding && <ProspectModal clientId={clientId} onClose={() => setAdding(false)} onSaved={(p) => { rows.reload(); onOpen(p.id); }} />}
  </Card>;
}

// ------------------------------------------------------------------ detail & evidence
function VerifyModal({ p, field, onClose, onSaved }: { p: Prospect; field: string; onClose: () => void; onSaved: () => void }) {
  const [note, setNote] = useState(""); const [url, setUrl] = useState(""); const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const go = async (decision: "verified" | "rejected" | "needs_review") => {
    setErr(null); setBusy(true);
    try { await api.verifyProspect(p.id, { field: field as never, decision, note: note || null, source_url: url || null }); onSaved(); onClose(); } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  };
  return <Modal open onClose={onClose} title={field === "status" ? `Review ${p.name}` : `Verify ${LABEL(field).toLowerCase()} for ${p.name}`}>
    <div className="space-y-4"><Err msg={err} />
      <Field label="How you checked it" hint="Required to verify: a note, a source URL, or both"><Textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      <Field label="Source URL"><Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="MCA page, company page, tender notice…" /></Field>
      <div className="flex flex-wrap justify-end gap-2">
        {field === "status" ? <><Button variant="secondary" loading={busy} onClick={() => go("needs_review")}>Needs review</Button><Button variant="danger" loading={busy} onClick={() => go("rejected")}>Reject lead</Button></>
          : <><Button variant="secondary" loading={busy} onClick={() => go("rejected")}>Not confirmed</Button><Button loading={busy} onClick={() => go("verified")}><Check className="h-4 w-4" />Verified</Button></>}
      </div></div>
  </Modal>;
}
function Detail({ id, reload }: { id: string | null; reload?: () => void }) {
  const d = useAsync(() => (id ? api.getProspect(id) : Promise.resolve(null)), [id]);
  const [verify, setVerify] = useState<string | null>(null);
  const [ev, setEv] = useState({ field: "intent", source_url: "", excerpt: "" });
  const [ct, setCt] = useState({ kind: "role_email" as "role_email" | "phone" | "person", value: "", person_name: "", role: "", source_url: "" });
  const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  if (!id) return <Card><Empty title="No prospect selected" body="Open a prospect from the database, the queue or the scoring dashboard." /></Card>;
  if (d.loading) return <Card><Skeleton rows={6} /></Card>;
  if (d.error || !d.data) return <Card><ErrorBox message={d.error || "Not found"} /></Card>;
  const p: ProspectDetail = d.data;
  const done = () => { d.reload(); reload?.(); };
  const run = async (fn: () => Promise<unknown>) => { setErr(null); setBusy(true); try { await fn(); done(); } catch (e) { setErr(errText(e)); } finally { setBusy(false); } };
  const vf = p.verified_fields;
  return <div className="space-y-6">
    <Card><CardHeader title={p.name} subtitle={p.qualification_reason || undefined} action={<div className="flex gap-2">
      {p.website && <Button size="sm" variant="secondary" loading={busy} onClick={() => run(() => api.checkProspectSite(p.id))} disabled={local()}><RefreshCw className="h-4 w-4" />Re-check site</Button>}
      <Button size="sm" variant="secondary" onClick={() => setVerify("status")}>Review</Button>
      {["rejected", "needs_review"].includes(p.verification_status) && <Button size="sm" variant="secondary" onClick={() => run(() => api.reopenProspect(p.id))}>Reopen</Button>}</div>} />
      <div className="grid gap-6 p-5 text-sm lg:grid-cols-3">
        <dl className="space-y-1.5 lg:col-span-2">
          {[["Website", p.website ? <a href={p.website} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-brand-600 hover:underline">{short(p.website)}<ExternalLink className="h-3 w-3" /></a> : "—"],
            ["Status", <Badge key="s" tone={statusTone(p.verification_status)}>{STATUS_LABEL[p.verification_status]}</Badge>],
            ["Buyer type", p.buyer_type ? BUYER_TYPE_LABEL[p.buyer_type] : "—"], ["Industry", p.industry || "— (not verified)"],
            ["Location", [p.industrial_area, p.city, p.district, p.state, p.country].filter(Boolean).join(", ") || "—"],
            ["Area searched", p.searched_area.map((a) => a.join(" > ")).join("; ") || "—"], ["Places named on its site", p.observed_locations.join(", ") || "—"],
            ["Site check", p.site_checked_at ? `${p.site_status} · ${fmtDateTime(p.site_checked_at)}` : "Not checked"], ["Sources", p.providers.join(", ")],
            ["Description (from its site)", p.description || "—"]].map(([k, v]) => <div key={String(k)} className="flex gap-3"><dt className="w-44 shrink-0 text-navy-400">{k}</dt><dd className="text-navy-800">{v}</dd></div>)}
        </dl>
        <div><div className="mb-2 text-xs font-medium uppercase tracking-wide text-navy-400">Verification</div>
          <ul className="space-y-1.5">{["company", "website", "industry", "product_relevance", "contact"].map((f) => <li key={f} className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-2">{vf[f] ? <Check className="h-4 w-4 text-emerald-600" /> : <X className="h-4 w-4 text-navy-300" />}{LABEL(f)}{vf[f]?.by === "system" && <span className="text-xs text-navy-400">(site fetched)</span>}</span>
            <button className="text-xs text-brand-600 hover:underline" onClick={() => setVerify(f)}>{vf[f] ? "Update" : "Verify"}</button></li>)}</ul>
          <div className="mt-4 text-xs font-medium uppercase tracking-wide text-navy-400">Score</div>
          <div className="mt-1 flex items-center gap-2"><ScoreBadge p={p} /><span className="text-xs text-navy-500">confidence {p.confidence === null ? "—" : `${Math.round(p.confidence * 100)}%`}</span></div>
          {p.score && <ul className="mt-2 space-y-1 text-xs text-navy-600">{Object.entries(p.score.components).map(([k, c]) => <li key={k}><span className="font-medium text-navy-800">{WEIGHT_LABEL[k]} {c.points}/{c.max}</span>: {c.reasons.join("; ")}</li>)}</ul>}
        </div>
      </div></Card>
    <div className="px-1"><Err msg={err} /></div>
    <div className="grid gap-6 lg:grid-cols-2">
      <Card><CardHeader title="Observed on its own website" />
        {!p.signals.matched_terms?.length && !p.signals.intent?.length && !p.signals.capacity?.length ? <p className="p-5 text-sm text-navy-500">Nothing observed yet. {local() ? "Site checks run on the backend." : "Re-check the site or add evidence."}</p> : (
          <ul className="divide-y divide-line text-sm">{[...(p.signals.intent || []).map((i) => ({ k: `Buying signal (${i.strength})`, t: i.signal, url: i.url, ex: i.excerpt })),
            ...(p.signals.matched_terms || []).map((m) => ({ k: m.kind === "need" ? "Need" : "Fit", t: m.term, url: m.url, ex: m.excerpt })),
            ...(p.signals.capacity || []).map((c) => ({ k: "Capacity", t: c.value, url: c.url, ex: c.excerpt }))].map((x, i) => (
            <li key={i} className="px-5 py-2.5"><div className="flex items-center gap-2"><Badge tone={x.k.startsWith("Buying") ? "green" : "blue"}>{x.k}</Badge><span className="font-medium text-navy-900">{x.t}</span></div>
              <p className="mt-1 text-xs text-navy-500">&ldquo;{x.ex}&rdquo; <a className="text-brand-600 hover:underline" href={x.url} target="_blank" rel="noopener noreferrer">{short(x.url).slice(0, 50)}</a></p></li>))}</ul>)}</Card>
      <Card><CardHeader title="Business contacts" subtitle="Published role contacts only. Personal details are never collected automatically." />
        {!p.contacts.length ? <p className="p-5 text-sm text-navy-500">No contacts recorded.</p> : <ul className="divide-y divide-line text-sm">{p.contacts.map((c) => <li key={c.id} className="flex items-center justify-between gap-2 px-5 py-2.5">
          <div><div className="font-medium text-navy-900">{c.person_name ? `${c.person_name}, ${c.role}` : c.value}{c.person_name && c.value ? ` · ${c.value}` : ""}</div>
            <div className="text-xs text-navy-500">{LABEL(c.kind)} · {c.origin === "observed" ? "on its site" : "added by team"} · {c.source_url ? <a href={c.source_url} className="text-brand-600 hover:underline" target="_blank" rel="noopener noreferrer">source</a> : "no source"}</div></div>
          <div className="flex items-center gap-2"><button className={cx("text-xs", c.verified ? "text-emerald-700" : "text-brand-600 hover:underline")} onClick={() => run(() => api.verifyContact(c.id, !c.verified))}>{c.verified ? "Verified ✓" : "Mark verified"}</button>
            <button aria-label="Delete contact" className="text-navy-400 hover:text-red-600" onClick={() => run(() => api.deleteContact(c.id))}><Trash2 className="h-4 w-4" /></button></div></li>)}</ul>}
        <div className="grid gap-2 border-t border-line p-5 md:grid-cols-2">
          <Select value={ct.kind} onChange={(e) => setCt({ ...ct, kind: e.target.value as typeof ct.kind })}><option value="role_email">Role email</option><option value="phone">Phone</option><option value="person">Named business contact</option></Select>
          <Input placeholder={ct.kind === "phone" ? "+91 …" : "sales@company.com"} value={ct.value} onChange={(e) => setCt({ ...ct, value: e.target.value })} />
          {ct.kind === "person" && <><Input placeholder="Name as published" value={ct.person_name} onChange={(e) => setCt({ ...ct, person_name: e.target.value })} /><Input placeholder="Role, e.g. Purchase Manager" value={ct.role} onChange={(e) => setCt({ ...ct, role: e.target.value })} /></>}
          <Input className="md:col-span-2" placeholder="Public page where it is published (required)" value={ct.source_url} onChange={(e) => setCt({ ...ct, source_url: e.target.value })} />
          <div className="md:col-span-2 flex justify-end"><Button size="sm" variant="secondary" loading={busy} onClick={() => run(async () => { await api.addProspectContact(p.id, { ...ct, value: ct.value || null, person_name: ct.person_name || null, role: ct.role || null }); setCt({ ...ct, value: "", person_name: "", role: "", source_url: "" }); })}><Plus className="h-4 w-4" />Add contact</Button></div>
        </div></Card>
    </div>
    <Card><CardHeader title="Evidence" subtitle="Every item has its source. Intent only scores with real evidence: a tender, RFQ, procurement notice or explicit request." />
      <div className="grid gap-2 border-b border-line p-5 md:grid-cols-6">
        <Select value={ev.field} onChange={(e) => setEv({ ...ev, field: e.target.value })}>{["intent", "need", "fit", "capacity", "company", "industry", "location", "other"].map((f) => <option key={f} value={f}>{LABEL(f)}</option>)}</Select>
        <Input className="md:col-span-2" placeholder="Source URL (required)" value={ev.source_url} onChange={(e) => setEv({ ...ev, source_url: e.target.value })} />
        <Input className="md:col-span-2" placeholder="What the source shows" value={ev.excerpt} onChange={(e) => setEv({ ...ev, excerpt: e.target.value })} />
        <Button size="sm" variant="secondary" loading={busy} onClick={() => run(async () => { await api.addProspectEvidence(p.id, ev); setEv({ ...ev, source_url: "", excerpt: "" }); })}><Plus className="h-4 w-4" />Add</Button>
      </div>
      <Table head={["Supports", "Source", "Excerpt", "Observed"]}>{p.evidence.map((e) => <tr key={e.id}>
        <td className="px-5 py-2.5"><Badge>{LABEL(e.field || "other")}</Badge></td>
        <td className="px-5 py-2.5 text-navy-600">{e.provider || e.source_type}{e.source_url && <> · <a href={e.source_url} target="_blank" rel="noopener noreferrer" className="text-brand-600 hover:underline">{short(e.source_url).slice(0, 40)}</a></>}</td>
        <td className="px-5 py-2.5 text-xs text-navy-600">{e.excerpt}</td><td className="px-5 py-2.5 text-navy-500">{fmtDate(e.observed_at || e.created_at)}</td></tr>)}</Table>
      {!!p.verifications.length && <><CardHeader title="Verification history" /><ul className="divide-y divide-line text-sm">{p.verifications.map((v) => <li key={v.id} className="px-5 py-2 text-navy-600">{fmtDateTime(v.created_at)} · {LABEL(v.field)} {LABEL(v.decision).toLowerCase()}{v.note ? ` · ${v.note}` : ""}</li>)}</ul></>}
    </Card>
    {verify && <VerifyModal p={p} field={verify} onClose={() => setVerify(null)} onSaved={done} />}
  </div>;
}

// ------------------------------------------------------------------ scoring
function Scoring({ clientId, role, onOpen }: { clientId: string; role: number; onOpen: (id: string) => void }) {
  const sum = useAsync(() => api.leadSummary(clientId), [clientId]);
  const top = useAsync(() => api.listProspects(clientId, { sort: "score", limit: 25 }), [clientId]);
  const [w, setW] = useState<Record<string, number>>({ ...DEFAULT_WEIGHTS }); const [msg, setMsg] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const total = Object.values(w).reduce((a, b) => a + b, 0);
  const rescore = async () => { setBusy(true); setMsg(null); try { const r = await api.rescoreLeads(clientId, { weights: w }); setMsg(`Rescored ${r.rescored} prospect(s).`); sum.reload(); top.reload(); } catch (e) { setMsg(errText(e)); } finally { setBusy(false); } };
  const has = !!sum.data?.prospects;
  return <div className="space-y-6">
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{(["very_high", "high", "medium", "low"] as const).map((k) => <Stat key={k} label={CLASS_LABEL[k]} value={has ? sum.data!.by_class[k] || 0 : null} hint={k === "very_high" ? "80–100" : k === "high" ? "65–79" : k === "medium" ? "40–64" : "Below 40"} />)}</div>
    <Card><CardHeader title="Score weights" subtitle="Must add up to 100. The score never counts search appearance, and confidence is separate from the score." />
      <div className="grid gap-3 p-5 md:grid-cols-5">{Object.keys(DEFAULT_WEIGHTS).map((k) => <Field key={k} label={WEIGHT_LABEL[k]}><Input type="number" min={0} max={100} value={w[k]} onChange={(e) => setW({ ...w, [k]: Number(e.target.value) })} /></Field>)}</div>
      <div className="flex items-center justify-between px-5 pb-5 text-sm"><span className={total === 100 ? "text-navy-500" : "text-red-600"}>Total {total} / 100{msg ? ` · ${msg}` : ""}</span>
        {role >= 1 && <Button size="sm" loading={busy} disabled={total !== 100} onClick={rescore}>Rescore all</Button>}</div></Card>
    <Card><CardHeader title="Top prospects" />
      {top.loading ? <Skeleton /> : !top.data?.items.length ? <Empty title="No scored prospects yet" /> : <ProspectTable rows={top.data.items} onOpen={onOpen} />}</Card>
  </div>;
}

// ------------------------------------------------------------------ verification queue
function Queue({ clientId, onOpen }: { clientId: string; onOpen: (id: string) => void }) {
  const rows = useAsync(() => api.verificationQueue(clientId), [clientId]);
  const [v, setV] = useState<{ p: Prospect; field: string } | null>(null);
  return <Card><CardHeader title="Verification queue" subtitle="Needs-review first, then by score. Verify each field with a note or source; nothing is verified automatically except that the website loads." />
    {rows.loading ? <Skeleton /> : rows.error ? <ErrorBox message={rows.error} /> : !rows.data!.length ? <Empty title="Queue is clear" body="New prospects appear here until a person verifies them." icon={<Check className="h-5 w-5" />} /> : (
      <Table head={["Company", "Status", "Score", "Verify"]}>{rows.data!.map((p) => <tr key={p.id}>
        <td className="px-5 py-2.5"><button className="font-medium text-navy-900 hover:text-brand-700" onClick={() => onOpen(p.id)}>{p.name}</button><div className="text-xs text-navy-500">{p.domain || "no website"}</div></td>
        <td className="px-5 py-2.5"><Badge tone={statusTone(p.verification_status)}>{STATUS_LABEL[p.verification_status]}</Badge></td>
        <td className="px-5 py-2.5"><ScoreBadge p={p} /></td>
        <td className="px-5 py-2.5"><div className="flex flex-wrap gap-1">{["company", "industry", "product_relevance", "contact"].map((f) => <Button key={f} size="sm" variant="secondary" onClick={() => setV({ p, field: f })}>{p.verified_fields[f] ? "✓ " : ""}{LABEL(f)}</Button>)}
          <Button size="sm" variant="secondary" onClick={() => setV({ p, field: "status" })}><X className="h-4 w-4" />Reject</Button></div></td></tr>)}</Table>)}
    {v && <VerifyModal p={v.p} field={v.field} onClose={() => setV(null)} onSaved={rows.reload} />}
  </Card>;
}

// ------------------------------------------------------------------ assignment
function Assignment({ clientId, onOpen }: { clientId: string; onOpen: (id: string) => void }) {
  const users = useAsync(() => api.listUsers());
  const rows = useAsync(() => api.listProspects(clientId, { sort: "score", limit: 200 }), [clientId]);
  const [sel, setSel] = useState<Set<string>>(new Set()); const [to, setTo] = useState(""); const [busy, setBusy] = useState(false);
  const names = useMemo(() => Object.fromEntries((users.data || []).map((u) => [u.id, u.full_name])), [users.data]);
  const toggle = (id: string) => { const n = new Set(sel); n.has(id) ? n.delete(id) : n.add(id); setSel(n); };
  const assign = async (uid: string | null) => { setBusy(true); try { await api.assignLeads(clientId, { prospect_ids: [...sel], user_id: uid }); setSel(new Set()); rows.reload(); } catch (e) { fail(e); } finally { setBusy(false); } };
  return <Card><CardHeader title="Lead assignment" subtitle={`${sel.size} selected`} action={<div className="flex items-center gap-2">
    <Select value={to} onChange={(e) => setTo(e.target.value)}><option value="">Team member…</option>{users.data?.filter((u) => u.is_active).map((u) => <option key={u.id} value={u.id}>{u.full_name} ({u.role})</option>)}</Select>
    <Button size="sm" loading={busy} disabled={!to || !sel.size} onClick={() => assign(to)}><UserPlus className="h-4 w-4" />Assign</Button>
    <Button size="sm" variant="secondary" disabled={!sel.size} onClick={() => assign(null)}>Unassign</Button></div>} />
    {rows.loading ? <Skeleton /> : !rows.data?.items.length ? <Empty title="No prospects to assign" /> : <ProspectTable rows={rows.data.items} onOpen={onOpen} selected={sel} onSelect={toggle} users={names} />}
  </Card>;
}

// ------------------------------------------------------------------ export & CRM + suppression
function ExportCrm({ clientId, clientName, onOpen }: { clientId: string; clientName: string; onOpen: (id: string) => void }) {
  const cand = useAsync(() => api.listProspects(clientId, { sort: "score", limit: 200 }), [clientId]);
  const sup = useAsync(() => api.listSuppression());
  const [sel, setSel] = useState<Set<string>>(new Set()); const [msg, setMsg] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const [s, setS] = useState({ kind: "domain" as "domain" | "email" | "phone", value: "", reason: "" });
  const toggle = (id: string) => { const n = new Set(sel); n.has(id) ? n.delete(id) : n.add(id); setSel(n); };
  const run = async (fn: () => Promise<string>) => { setBusy(true); setMsg(null); try { setMsg(await fn()); cand.reload(); sup.reload(); } catch (e) { setMsg(errText(e)); } finally { setBusy(false); } };
  const slug = clientName.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "client";
  return <div className="space-y-6">
    <Card><CardHeader title="Approve, export and hand off" subtitle="Only approved leads export or reach the CRM. Approval needs a person to have verified the company. Nothing here contacts anyone." action={<div className="flex flex-wrap gap-2">
      <Button size="sm" variant="secondary" disabled={!sel.size} loading={busy} onClick={() => run(async () => { const r = await api.approveLeads(clientId, { prospect_ids: [...sel], approved: true }); setSel(new Set()); return `${r.updated} approved.${r.blocked.length ? " Not approved: " + r.blocked.join("; ") : ""}`; })}><Check className="h-4 w-4" />Approve</Button>
      <Button size="sm" variant="secondary" disabled={!sel.size} loading={busy} onClick={() => run(async () => { const r = await api.crmHandoff(clientId, [...sel]); setSel(new Set()); return `${r.handed_off} handed to CRM.${r.skipped.length ? " Skipped: " + r.skipped.join("; ") : ""}`; })}><Send className="h-4 w-4" />Hand off to CRM</Button>
      <Button size="sm" loading={busy} onClick={() => run(async () => { save(`${slug}-prospects.csv`, await api.exportLeads(clientId, "csv")); return "CSV downloaded."; })}><Download className="h-4 w-4" />CSV</Button>
      <Button size="sm" variant="secondary" loading={busy} onClick={() => run(async () => { save(`${slug}-prospects.xlsx`, await api.exportLeads(clientId, "xlsx")); return "Excel file downloaded."; })}><Download className="h-4 w-4" />Excel</Button></div>} />
      {msg && <Note tone="blue">{msg}</Note>}
      {cand.loading ? <Skeleton /> : !cand.data?.items.length ? <Empty title="No prospects yet" /> : (
        <Table head={["", "Company", "Status", "Score", "CRM"]}>{cand.data.items.map((p) => <tr key={p.id}>
          <td className="px-5 py-2.5"><input type="checkbox" aria-label={`Select ${p.name}`} checked={sel.has(p.id)} onChange={() => toggle(p.id)} /></td>
          <td className="px-5 py-2.5"><button className="font-medium text-navy-900 hover:text-brand-700" onClick={() => onOpen(p.id)}>{p.name}</button></td>
          <td className="px-5 py-2.5"><Badge tone={statusTone(p.verification_status)}>{STATUS_LABEL[p.verification_status]}</Badge></td>
          <td className="px-5 py-2.5"><ScoreBadge p={p} /></td>
          <td className="px-5 py-2.5"><Badge tone={p.crm_status === "handed_off" ? "green" : p.crm_status === "approved" ? "blue" : "slate"}>{p.crm_status === "none" ? "Not approved" : LABEL(p.crm_status)}</Badge></td></tr>)}</Table>)}
    </Card>
    <Card><CardHeader title="Do-not-contact list" subtitle="Agency-wide. Matching domains are never added as prospects, and matching emails or phones are never stored or exported." />
      <div className="grid gap-2 border-b border-line p-5 md:grid-cols-5">
        <Select value={s.kind} onChange={(e) => setS({ ...s, kind: e.target.value as typeof s.kind })}><option value="domain">Domain</option><option value="email">Email</option><option value="phone">Phone</option></Select>
        <Input className="md:col-span-2" placeholder={s.kind === "domain" ? "example.com" : s.kind === "email" ? "name@example.com" : "+91 …"} value={s.value} onChange={(e) => setS({ ...s, value: e.target.value })} />
        <Input placeholder="Reason" value={s.reason} onChange={(e) => setS({ ...s, reason: e.target.value })} />
        <Button size="sm" variant="secondary" loading={busy} onClick={() => run(async () => { await api.addSuppression({ ...s, reason: s.reason || null }); setS({ ...s, value: "", reason: "" }); return "Added to the do-not-contact list."; })}><ShieldOff className="h-4 w-4" />Add</Button>
      </div>
      {!sup.data?.length ? <p className="p-5 text-sm text-navy-500">The list is empty.</p> : <Table head={["Type", "Value", "Reason", "Added", ""]}>{sup.data.map((x) => <tr key={x.id}>
        <td className="px-5 py-2.5">{LABEL(x.kind)}</td><td className="px-5 py-2.5 font-medium text-navy-900">{x.value}</td><td className="px-5 py-2.5 text-navy-600">{x.reason || "—"}</td>
        <td className="px-5 py-2.5 text-navy-500">{fmtDate(x.created_at)}</td>
        <td className="px-5 py-2.5 text-right"><button aria-label="Remove entry" className="text-navy-400 hover:text-red-600" onClick={() => api.deleteSuppression(x.id).then(sup.reload, fail)}><Trash2 className="h-4 w-4" /></button></td></tr>)}</Table>}
    </Card>
  </div>;
}

// ------------------------------------------------------------------ shell
export function BuyerDiscovery({ clientId, clientName, archived }: { clientId: string; clientName: string; archived: boolean }) {
  const { session } = useAuth();
  const role = RANK[(session?.user.role || "staff") as keyof typeof RANK];
  const [screen, setScreen] = useState<Screen>("Overview");
  const [prospectId, setProspectId] = useState<string | null>(null);
  const [query, setQuery] = useState<ProspectQuery>({});
  const open = (id: string) => { setProspectId(id); setScreen("Prospect detail"); };
  return <div>
    {archived && <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">This client is archived. Restore it to run new campaigns.</div>}
    <div className="mb-6 flex flex-wrap gap-1.5">{SCREENS.map((s) => <button key={s} onClick={() => setScreen(s)} className={cx("rounded-full border px-3 py-1 text-xs transition",
      screen === s ? "border-brand-600 bg-brand-600 text-white" : "border-line bg-white text-navy-600 hover:border-brand-300")}>{s}</button>)}</div>
    {screen === "Overview" && <><LocalNote /><Overview clientId={clientId} go={setScreen} /></>}
    {screen === "Buyer profiles" && <Profiles clientId={clientId} role={role} />}
    {screen === "Market explorer" && <Markets clientId={clientId} />}
    {screen === "India districts & clusters" && <IndiaExplorer clientId={clientId} />}
    {screen === "International markets" && <International clientId={clientId} />}
    {screen === "Campaigns" && <Campaigns clientId={clientId} role={role} openProspects={(q) => { setQuery(q); setScreen("Prospect database"); }} />}
    {screen === "Prospect database" && <Database clientId={clientId} initial={query} onOpen={open} />}
    {screen === "Prospect detail" && <Detail id={prospectId} />}
    {screen === "Lead scoring" && <Scoring clientId={clientId} role={role} onOpen={open} />}
    {screen === "Verification queue" && <Queue clientId={clientId} onOpen={open} />}
    {screen === "Assignment" && <Assignment clientId={clientId} onOpen={open} />}
    {screen === "Export & CRM" && <ExportCrm clientId={clientId} clientName={clientName} onOpen={open} />}
  </div>;
}
