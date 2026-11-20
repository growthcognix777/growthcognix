"use client";
import { CalendarDays, Check, ChevronLeft, ChevronRight, Download, ExternalLink, History, Link2, Plus, RefreshCw, Send, Sparkles, Trash2, Unplug } from "lucide-react";
import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, fmtDateTime, fmtMoney } from "@/lib/format";
import {
  AD_LIMITS, ASSET_KINDS, BUDGET_CATEGORIES, BUDGET_LABELS, COST_KINDS, COST_LABEL, KIND_LABEL, LIMITS, PLATFORM_LABEL, SECTION_LABEL, SEO_KINDS, SOCIAL_KINDS,
  SOCIAL_PLATFORMS, STATUS_LABEL, STATUS_TONE, ACTIONS, allowedActions,
} from "@/lib/marketing";
import type { AdPlan, ApprovalRow, BudgetLine, ContentItem, MarketingBudget, MarketingStrategy, MkEntity, MkStatus, Product, ReviewAction, Role } from "@/lib/types";
import { useAsync } from "@/lib/useAsync";
import { Badge, Button, Card, CardHeader, Empty, ErrorBox, Field, Input, Modal, Select, Skeleton, Stat, Table, TagInput, Textarea, cx } from "./ui";

const SCREENS = ["Overview", "AI strategy", "Budget planner", "Social studio", "SEO studio", "Creative assets", "Ad planner", "Calendar",
  "Approval centre", "Social accounts", "Publishing history", "Analytics", "Reports"] as const;
type Screen = (typeof SCREENS)[number];
const local = () => api.mode === "local";
const fail = (e: unknown) => alert(e instanceof Error ? e.message : "Failed");
const label = (k: string) => k.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
const num = (v: string) => (v.trim() === "" ? null : Number(v));

function Note({ children, tone = "amber" }: { children: React.ReactNode; tone?: "amber" | "blue" }) {
  return <div className={cx("rounded-lg border p-3 text-sm", tone === "amber" ? "border-amber-200 bg-amber-50 text-amber-800" : "border-brand-100 bg-brand-50 text-brand-800")}>{children}</div>;
}
function LocalNote({ what }: { what: string }) {
  return local() ? <Note>This browser preview has no server, so {what} can&apos;t run here and nothing is simulated. Run the backend for it; everything you write by hand works here.</Note> : null;
}
function StatusBadge({ s }: { s: MkStatus }) { return <Badge tone={STATUS_TONE[s]}>{STATUS_LABEL[s]}</Badge>; }

// ------------------------------------------------------------------ review bar (shared approval workflow)
function ReviewBar({ entity, id, status, role, claims, onDone }: { entity: MkEntity; id: string; status: MkStatus; role: Role; claims?: string[]; onDone: () => void }) {
  const acts = allowedActions(status, role);
  const [note, setNote] = useState(""); const [who, setWho] = useState(""); const [busy, setBusy] = useState<ReviewAction | null>(null);
  const [hist, setHist] = useState(false);
  if (!acts.length) return <div className="flex items-center gap-2"><HistoryButton entity={entity} id={id} open={hist} setOpen={setHist} /></div>;
  const run = async (a: ReviewAction) => { setBusy(a); try { await api.review(entity, id, { action: a, note: note || null, reviewer_name: who || null }); setNote(""); onDone(); } catch (e) { fail(e); } finally { setBusy(null); } };
  return <div className="space-y-2 rounded-lg bg-canvas/60 p-3">
    {acts.some((a) => a !== "submit") && <Input placeholder={claims?.length ? "Review note (required: say how the flagged claims were checked)" : "Review note (optional)"} value={note} onChange={(e) => setNote(e.target.value)} />}
    {status === "client_review" && <Input placeholder="Who at the client approved it (name)" value={who} onChange={(e) => setWho(e.target.value)} />}
    <div className="flex flex-wrap gap-2">
      {acts.map((a) => <Button key={a} size="sm" variant={a === "approve" || a === "client_approve" || a === "submit" ? "primary" : a === "reject" ? "danger" : "secondary"} loading={busy === a} onClick={() => run(a)}>{ACTIONS[a].label}</Button>)}
      <HistoryButton entity={entity} id={id} open={hist} setOpen={setHist} />
    </div>
  </div>;
}
function HistoryButton({ entity, id, open, setOpen }: { entity: MkEntity; id: string; open: boolean; setOpen: (b: boolean) => void }) {
  return <><Button size="sm" variant="ghost" onClick={() => setOpen(true)}><History className="h-4 w-4" />History</Button>
    {open && <Modal open title="Revisions & approvals" onClose={() => setOpen(false)}><HistoryView entity={entity} id={id} /></Modal>}</>;
}
function HistoryView({ entity, id }: { entity: MkEntity; id: string }) {
  const h = useAsync(() => api.marketingHistory(entity, id), [entity, id]);
  if (h.loading) return <Skeleton rows={3} />;
  if (h.error) return <ErrorBox message={h.error} />;
  return <div className="space-y-4 text-sm">
    <div><div className="mb-1 font-medium text-navy-900">Approvals</div>
      {h.data!.approvals.length ? <ul className="divide-y divide-line">{h.data!.approvals.map((a) => <li key={a.id} className="py-2">
        <Badge tone={a.status === "approved" ? "green" : a.status === "rejected" ? "red" : a.status === "pending" ? "amber" : "slate"}>{label(a.status)}</Badge>
        <span className="ml-2 text-navy-700">{label(a.stage)} · v{a.entity_version}{a.reviewer_name ? ` · client: ${a.reviewer_name}` : ""}</span>
        <span className="ml-2 text-xs text-navy-400">{fmtDateTime(a.decided_at || a.created_at)}</span>{a.note && <p className="mt-1 text-navy-500">{a.note}</p>}</li>)}</ul> : <p className="text-navy-500">None yet.</p>}</div>
    <div><div className="mb-1 font-medium text-navy-900">Revisions</div>
      {h.data!.revisions.length ? <ul className="divide-y divide-line">{h.data!.revisions.map((r) => <li key={r.id} className="py-2">v{r.version} · {r.note || "Edited"} <span className="text-xs text-navy-400">{fmtDateTime(r.created_at)}</span></li>)}</ul> : <p className="text-navy-500">No edits yet.</p>}</div>
  </div>;
}

// ------------------------------------------------------------------ overview
function Overview({ clientId, go }: { clientId: string; go: (s: Screen) => void }) {
  const ov = useAsync(() => api.marketingOverview(clientId), [clientId]);
  const st = useAsync(() => api.marketingStatus());
  const o = ov.data; const sum = (r?: Record<string, number>) => (r ? Object.values(r).reduce((a, b) => a + b, 0) : 0);
  return <div className="space-y-6">
    <LocalNote what="AI drafting, account connections, publishing and analytics" />
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <Stat label="Content items" value={o ? sum(o.content) : null} hint={o && sum(o.content) ? `${o.content.published || 0} published, ${o.content.approved || 0} approved` : "Nothing drafted yet"} />
      <Stat label="Waiting for approval" value={o ? o.pending_approvals : null} hint="Internal or client review" />
      <Stat label="Approved monthly budget" value={o?.approved_budget ? fmtMoney(o.approved_budget.summary.monthly_total, o.approved_budget.currency) : null} hint={o?.approved_budget ? o.approved_budget.name : "No budget approved yet"} />
      <Stat label="Connected accounts" value={o ? o.accounts.connected || 0 : null} hint="Official APIs only" />
    </div>
    <Card><CardHeader title="Workflow" subtitle="AI drafts are never published or spent without a person approving them" />
      <ol className="grid gap-3 p-5 text-sm md:grid-cols-3">
        {([["AI strategy", "14-section plan from the client's real records; facts, assumptions and suggestions kept apart."],
          ["Budget planner", "Monthly and quarterly; ad spend, agency fees and production costs separate."],
          ["Social studio", "Posts, carousels and scripts for Instagram, Facebook, LinkedIn and YouTube."],
          ["Approval centre", "Internal review, optional client review, revision history."],
          ["Calendar", "Schedule approved items; editing sends them back to review."],
          ["Analytics", "Only numbers the platforms report, kept apart from our calculations."]] as [Screen, string][]).map(([t, d], i) =>
          <li key={t}><button onClick={() => go(t)} className="h-full w-full rounded-lg border border-line p-4 text-left hover:border-brand-300 hover:bg-brand-50/40">
            <span className="font-medium text-navy-900">{i + 1}. {t}</span><p className="mt-1 text-navy-500">{d}</p></button></li>)}
      </ol></Card>
    <div className="grid gap-6 lg:grid-cols-2">
      <Card><CardHeader title="Coming up" subtitle="Approved items with a date" />
        {ov.loading ? <Skeleton rows={2} /> : o?.upcoming.length ? <ul className="divide-y divide-line">{o.upcoming.map((i) => <li key={i.id} className="flex justify-between px-5 py-2.5 text-sm"><span>{PLATFORM_LABEL[i.platform || ""] || i.platform} · {i.title}</span><span className="text-navy-400">{fmtDateTime(i.scheduled_at)}</span></li>)}</ul>
          : <Empty title="Nothing scheduled" body="Approve an item, then give it a date on the calendar." />}</Card>
      <Card><CardHeader title="Publishing channels" subtitle="Configured on the server; never simulated" />
        {st.loading ? <Skeleton rows={3} /> : st.error ? <ErrorBox message={st.error} /> : <Table head={["Channel", "Status", "Note"]}>
          {st.data!.publishing.map((p) => <tr key={p.platform}><td className="px-5 py-2.5 font-medium">{PLATFORM_LABEL[p.platform]}</td>
            <td className="px-5 py-2.5"><Badge tone={p.configured ? "green" : p.automated ? "slate" : "amber"}>{p.configured ? "Ready" : p.automated ? "Not configured" : "Manual"}</Badge></td>
            <td className="px-5 py-2.5 text-xs text-navy-500">{p.note}</td></tr>)}</Table>}
        {st.data && <p className="px-5 pb-4 text-xs text-navy-500">Email marketing: {st.data.email_marketing}</p>}</Card>
    </div>
  </div>;
}

// ------------------------------------------------------------------ strategy
function Strategy({ clientId, role, products }: { clientId: string; role: Role; products: Product[] }) {
  const list = useAsync(() => api.listStrategies(clientId), [clientId]);
  const [f, setF] = useState({ title: "", objectives: "", monthly_budget: "", sales_capacity: "", channels: [] as string[], product_ids: [] as string[] });
  const [busy, setBusy] = useState(false); const [open, setOpen] = useState<string | null>(null);
  const create = async () => {
    setBusy(true);
    try { const s = await api.createStrategy(clientId, { title: f.title, objectives: f.objectives || null, monthly_budget: num(f.monthly_budget), sales_capacity: f.sales_capacity || null, channels_in_use: f.channels, product_ids: f.product_ids }); setOpen(s.id); list.reload(); }
    catch (e) { fail(e); } finally { setBusy(false); }
  };
  return <div className="space-y-6">
    <LocalNote what="AI strategy generation" />
    <Card><CardHeader title="Generate a strategy" subtitle="Built from the client profile, products, approved buyer profiles, markets, competitors, website audit and brand assets" />
      <div className="grid gap-4 p-5 md:grid-cols-2">
        <Field label="Title" required><Input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder="FY27 growth plan" /></Field>
        <Field label="Monthly budget" hint="Leave empty to use the client's budget on record"><Input type="number" min={0} value={f.monthly_budget} onChange={(e) => setF({ ...f, monthly_budget: e.target.value })} /></Field>
        <Field label="Objectives"><Textarea rows={2} value={f.objectives} onChange={(e) => setF({ ...f, objectives: e.target.value })} placeholder="More dealer enquiries from Gujarat and the UAE" /></Field>
        <Field label="Sales capacity"><Textarea rows={2} value={f.sales_capacity} onChange={(e) => setF({ ...f, sales_capacity: e.target.value })} placeholder="2 sales engineers, can follow up within 48 hours" /></Field>
        <Field label="Channels already in use"><TagInput value={f.channels} onChange={(v) => setF({ ...f, channels: v })} placeholder="LinkedIn, trade fairs…" /></Field>
        <Field label="Focus products" hint="None selected = all products">
          <div className="flex flex-wrap gap-1.5">{products.map((p) => <button key={p.id} onClick={() => setF({ ...f, product_ids: f.product_ids.includes(p.id) ? f.product_ids.filter((x) => x !== p.id) : [...f.product_ids, p.id] })}
            className={cx("rounded-full border px-2.5 py-0.5 text-xs", f.product_ids.includes(p.id) ? "border-brand-600 bg-brand-50 text-brand-700" : "border-line")}>{p.name}</button>)}{!products.length && <span className="text-sm text-navy-500">No products yet.</span>}</div></Field>
      </div>
      <div className="flex justify-end border-t border-line px-5 py-3"><Button loading={busy} disabled={f.title.trim().length < 3} onClick={create}><Sparkles className="h-4 w-4" />Generate draft</Button></div></Card>
    <Card><CardHeader title="Strategies" action={<Button size="sm" variant="ghost" onClick={list.reload}><RefreshCw className="h-4 w-4" /></Button>} />
      {list.loading ? <Skeleton /> : list.error ? <ErrorBox message={list.error} /> : !list.data!.length ? <Empty title="No strategies yet" body="Generated strategies appear here as drafts for review." /> :
        <ul className="divide-y divide-line">{list.data!.map((s) => <li key={s.id} className="px-5 py-3">
          <button className="flex w-full items-center justify-between text-left" onClick={() => setOpen(open === s.id ? null : s.id)}>
            <span className="font-medium text-navy-900">{s.title} <span className="text-xs text-navy-400">v{s.version}</span></span>
            <span className="flex items-center gap-2">{s.job_status !== "completed" ? <Badge tone={s.job_status === "failed" ? "red" : "blue"}>{label(s.job_status)}</Badge> : <StatusBadge s={s.status} />}<span className="text-xs text-navy-400">{fmtDate(s.created_at)}</span></span></button>
          {open === s.id && <StrategyView id={s.id} role={role} onChange={list.reload} />}</li>)}</ul>}</Card>
  </div>;
}
function StrategyView({ id, role, onChange }: { id: string; role: Role; onChange: () => void }) {
  const s = useAsync(() => api.getStrategy(id), [id]);
  const [edit, setEdit] = useState<{ key: string; summary: string } | null>(null);
  if (s.loading) return <Skeleton rows={3} />;
  if (s.error) return <ErrorBox message={s.error} />;
  const d: MarketingStrategy = s.data!;
  const reload = () => { s.reload(); onChange(); };
  if (d.job_status === "failed") return <div className="mt-3 space-y-2"><ErrorBox message={d.error || "Generation failed"} /><Button size="sm" onClick={() => api.retryStrategy(id).then(reload, fail)}>Retry</Button></div>;
  if (d.job_status !== "completed") return <p className="mt-3 text-sm text-navy-500">Generating… <button className="underline" onClick={reload}>Refresh</button></p>;
  return <div className="mt-4 space-y-4">
    {d.disclaimer && <Note tone="blue">{d.disclaimer}</Note>}
    <div className="grid gap-3 md:grid-cols-2">{Object.entries(d.sections).map(([k, sec]) => <div key={k} className="rounded-lg border border-line p-4 text-sm">
      <div className="mb-1 flex items-center justify-between"><span className="font-medium text-navy-900">{SECTION_LABEL(k)}</span><button className="text-xs text-brand-600" onClick={() => setEdit({ key: k, summary: sec.summary })}>Edit</button></div>
      <p className="text-navy-700">{sec.summary || "—"}</p>
      {sec.facts?.length > 0 && <div className="mt-2"><div className="text-xs font-medium uppercase text-emerald-700">Verified facts</div><ul className="list-disc pl-4 text-navy-700">{sec.facts.map((x, i) => <li key={i}>{x.text} <span className="text-xs text-navy-400">[{x.source_id}]</span></li>)}</ul></div>}
      {sec.assumptions?.length > 0 && <div className="mt-2"><div className="text-xs font-medium uppercase text-amber-700">Assumptions to confirm</div><ul className="list-disc pl-4 text-navy-700">{sec.assumptions.map((x, i) => <li key={i}>{x}</li>)}</ul></div>}
      {sec.recommendations?.length > 0 && <div className="mt-2"><div className="text-xs font-medium uppercase text-violet-700">AI recommendations</div><ul className="list-disc pl-4 text-navy-700">{sec.recommendations.map((x, i) => <li key={i}>{x}</li>)}</ul></div>}
    </div>)}</div>
    <ReviewBar entity="strategy" id={id} status={d.status} role={role} onDone={reload} />
    {edit && <Modal open title={`Edit: ${SECTION_LABEL(edit.key)}`} onClose={() => setEdit(null)}>
      <Textarea rows={6} value={edit.summary} onChange={(e) => setEdit({ ...edit, summary: e.target.value })} />
      <p className="mt-2 text-xs text-navy-500">Editing an approved strategy sends it back to internal review.</p>
      <div className="mt-3 flex justify-end"><Button onClick={() => api.editStrategy(id, { sections: { [edit.key]: { summary: edit.summary } }, note: `Edited ${SECTION_LABEL(edit.key)}` }).then(() => { setEdit(null); reload(); }, fail)}>Save</Button></div></Modal>}
  </div>;
}

// ------------------------------------------------------------------ budget
function Budgets({ clientId, role }: { clientId: string; role: Role }) {
  const list = useAsync(() => api.listBudgets(clientId), [clientId]);
  const [f, setF] = useState({ name: "", monthly_total: "", currency: "INR", categories: [...BUDGET_CATEGORIES], scenario: "base" as "base" | "conservative" | "growth" });
  const [busy, setBusy] = useState(false); const [open, setOpen] = useState<string | null>(null);
  const create = async () => { setBusy(true); try { const b = await api.createBudget(clientId, { name: f.name, monthly_total: num(f.monthly_total), currency: f.currency, categories: f.categories, scenario: f.scenario }); setOpen(b.id); list.reload(); } catch (e) { fail(e); } finally { setBusy(false); } };
  return <div className="space-y-6">
    <Card><CardHeader title="New budget" subtitle="Starts from a planning template you adjust line by line. The shares are a starting point, not a benchmark." />
      <div className="grid gap-4 p-5 md:grid-cols-4">
        <Field label="Name" required><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Q1 plan" /></Field>
        <Field label="Monthly total" hint="Empty = client's budget on record"><Input type="number" min={0} value={f.monthly_total} onChange={(e) => setF({ ...f, monthly_total: e.target.value })} /></Field>
        <Field label="Currency"><Input maxLength={3} value={f.currency} onChange={(e) => setF({ ...f, currency: e.target.value.toUpperCase() })} /></Field>
        <Field label="Scenario"><Select value={f.scenario} onChange={(e) => setF({ ...f, scenario: e.target.value as typeof f.scenario })}><option value="base">Base</option><option value="conservative">Conservative (×0.7)</option><option value="growth">Growth (×1.4)</option></Select></Field>
        <div className="md:col-span-4"><div className="mb-1 text-sm font-medium text-navy-900">Categories</div><div className="flex flex-wrap gap-1.5">{BUDGET_CATEGORIES.map((c) => <button key={c} onClick={() => setF({ ...f, categories: f.categories.includes(c) ? f.categories.filter((x) => x !== c) : [...f.categories, c] })}
          className={cx("rounded-full border px-2.5 py-0.5 text-xs", f.categories.includes(c) ? "border-brand-600 bg-brand-50 text-brand-700" : "border-line")}>{BUDGET_LABELS[c]}</button>)}</div></div>
      </div>
      <div className="flex justify-end border-t border-line px-5 py-3"><Button loading={busy} disabled={f.name.trim().length < 2 || !f.categories.length} onClick={create}><Plus className="h-4 w-4" />Create budget</Button></div></Card>
    {list.loading ? <Skeleton /> : list.error ? <ErrorBox message={list.error} /> : !list.data!.length ? <Card><Empty title="No budgets yet" /></Card> :
      list.data!.map((b) => <Card key={b.id}><button onClick={() => setOpen(open === b.id ? null : b.id)} className="flex w-full items-center justify-between px-5 py-4 text-left">
        <span><span className="font-medium text-navy-900">{b.name}</span> <span className="text-sm text-navy-500">· {fmtMoney(b.summary.monthly_total, b.currency)}/month · {fmtMoney(b.summary.quarterly_total, b.currency)}/quarter · {label(b.scenario)}</span></span><StatusBadge s={b.status} /></button>
        {open === b.id && <BudgetEditor b={b} role={role} onChange={list.reload} />}</Card>)}
  </div>;
}
function BudgetEditor({ b, role, onChange }: { b: MarketingBudget; role: Role; onChange: () => void }) {
  const [lines, setLines] = useState<BudgetLine[]>(b.lines); const [busy, setBusy] = useState(false);
  const dirty = JSON.stringify(lines) !== JSON.stringify(b.lines);
  const save = async () => { setBusy(true); try { await api.editBudget(b.id, { lines }); onChange(); } catch (e) { fail(e); } finally { setBusy(false); } };
  return <div className="border-t border-line">
    <Table head={["Category", "Cost type", "Monthly", "Quarterly", "Share"]}>
      {lines.map((l, i) => <tr key={i}><td className="px-5 py-2">{BUDGET_LABELS[l.category]}</td>
        <td className="px-5 py-2"><Select value={l.cost_kind} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, cost_kind: e.target.value as BudgetLine["cost_kind"] } : x)))}>{COST_KINDS.map((k) => <option key={k} value={k}>{COST_LABEL[k]}</option>)}</Select></td>
        <td className="px-5 py-2"><Input type="number" min={0} className="w-32" value={l.amount} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, amount: Number(e.target.value) } : x)))} /></td>
        <td className="px-5 py-2 text-navy-600">{fmtMoney(b.summary.quarterly_by_category[l.category] ?? l.amount * 3, b.currency)}</td>
        <td className="px-5 py-2 text-navy-500">{b.summary.share[l.category] ?? 0}%</td></tr>)}
    </Table>
    <div className="grid gap-3 p-5 sm:grid-cols-3">{COST_KINDS.map((k) => <div key={k} className="rounded-lg border border-line p-3 text-sm"><div className="text-xs uppercase text-navy-400">{COST_LABEL[k]}</div><div className="text-lg font-semibold">{fmtMoney(b.summary.by_cost_kind[k], b.currency)}</div></div>)}</div>
    <div className="flex flex-wrap items-center justify-between gap-2 px-5 pb-5">
      <div className="flex gap-2">{(["conservative", "base", "growth"] as const).map((s) => <Button key={s} size="sm" variant="secondary" onClick={() => api.budgetScenario(b.id, s).then(onChange, fail)}>Copy as {s}</Button>)}
        {dirty && <Button size="sm" loading={busy} onClick={save}>Save lines</Button>}
        {role !== "staff" && <Button size="sm" variant="danger" onClick={() => confirm("Delete this budget?") && api.deleteBudget(b.id).then(onChange, fail)}><Trash2 className="h-4 w-4" /></Button>}</div>
      <ReviewBar entity="budget" id={b.id} status={b.status} role={role} onDone={onChange} />
    </div>
  </div>;
}

// ------------------------------------------------------------------ content (social + SEO)
function ContentCard({ it, role, onChange }: { it: ContentItem; role: Role; onChange: () => void }) {
  const [mode, setMode] = useState<null | "edit" | "schedule" | "publish" | "manual">(null);
  const limit = LIMITS[it.platform || "website"];
  return <div className="rounded-lg border border-line p-4">
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div><div className="font-medium text-navy-900">{it.title}</div>
        <div className="text-xs text-navy-500">{PLATFORM_LABEL[it.platform || ""] || it.platform} · {KIND_LABEL(it.kind)} · v{it.version}{it.origin === "ai" && " · AI draft"}{it.scheduled_at && ` · ${fmtDateTime(it.scheduled_at)}`}</div></div>
      <StatusBadge s={it.status} /></div>
    {it.body && <p className="mt-2 line-clamp-6 whitespace-pre-line text-sm text-navy-700">{it.body}</p>}
    {it.body && limit && <div className={cx("mt-1 text-xs", it.body.length > limit ? "text-red-600" : "text-navy-400")}>{it.body.length.toLocaleString()} / {limit.toLocaleString()} characters</div>}
    {it.data.hashtags?.length ? <p className="mt-1 text-xs text-brand-700">{it.data.hashtags.join(" ")}</p> : null}
    {it.data.cta && <p className="mt-1 text-xs text-navy-600">CTA: {it.data.cta}</p>}
    {it.data.slides?.length ? <ol className="mt-2 list-decimal pl-5 text-xs text-navy-600">{it.data.slides.map((s, i) => <li key={i}>{s}</li>)}</ol> : null}
    {it.data.meta_title && <p className="mt-2 text-xs text-navy-600">Meta: {it.data.meta_title} — {it.data.meta_description}</p>}
    {it.data.creative_brief && <p className="mt-2 text-xs text-navy-600">Creative brief: {it.data.creative_brief}</p>}
    {it.data.external_url && <a href={it.data.external_url} target="_blank" rel="noopener noreferrer" className="mt-2 inline-flex items-center gap-1 text-xs text-brand-600">Live post <ExternalLink className="h-3 w-3" /></a>}
    {it.claims_to_check.length > 0 && <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800"><div className="font-medium">Check before approving ({it.claims_to_check.length})</div><ul className="list-disc pl-4">{it.claims_to_check.map((c, i) => <li key={i}>{c}</li>)}</ul></div>}
    <div className="mt-3 flex flex-wrap gap-2">
      {it.status !== "published" && <Button size="sm" variant="secondary" onClick={() => setMode("edit")}>Edit</Button>}
      {["approved", "scheduled"].includes(it.status) && <Button size="sm" variant="secondary" onClick={() => setMode("schedule")}><CalendarDays className="h-4 w-4" />Date</Button>}
      {role !== "staff" && ["approved", "scheduled"].includes(it.status) && it.platform !== "website" && <Button size="sm" onClick={() => setMode("publish")}><Send className="h-4 w-4" />Publish</Button>}
      {role !== "staff" && ["approved", "scheduled"].includes(it.status) && <Button size="sm" variant="secondary" onClick={() => setMode("manual")}><Link2 className="h-4 w-4" />Record as published</Button>}
      {role !== "staff" && <Button size="sm" variant="ghost" onClick={() => confirm("Delete this item?") && api.deleteContent(it.id).then(onChange, fail)}><Trash2 className="h-4 w-4" /></Button>}
    </div>
    <div className="mt-3"><ReviewBar entity="content" id={it.id} status={it.status} role={role} claims={it.claims_to_check} onDone={onChange} /></div>
    {mode === "edit" && <EditContent it={it} onClose={() => setMode(null)} onSaved={onChange} />}
    {mode === "schedule" && <ScheduleModal it={it} onClose={() => setMode(null)} onSaved={onChange} />}
    {mode === "publish" && <PublishModal it={it} onClose={() => setMode(null)} onSaved={onChange} />}
    {mode === "manual" && <ManualModal it={it} onClose={() => setMode(null)} onSaved={onChange} />}
  </div>;
}
function EditContent({ it, onClose, onSaved }: { it: ContentItem; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ title: it.title, body: it.body || "", hashtags: it.data.hashtags || [], cta: it.data.cta || "", image_url: it.data.image_url || "", note: "" });
  return <Modal open title="Edit content" onClose={onClose}><div className="space-y-3">
    {["approved", "scheduled", "client_review"].includes(it.status) && <Note>Saving changes sends this back to internal review and cancels any scheduled post.</Note>}
    <Field label="Title"><Input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
    <Field label="Body / caption"><Textarea rows={8} value={f.body} onChange={(e) => setF({ ...f, body: e.target.value })} /></Field>
    {it.studio === "social" && <><Field label="Hashtags"><TagInput value={f.hashtags} onChange={(v) => setF({ ...f, hashtags: v })} /></Field>
      <Field label="Call to action"><Input value={f.cta} onChange={(e) => setF({ ...f, cta: e.target.value })} /></Field>
      <Field label="Image URL" hint="Public https link; Instagram needs one to publish"><Input value={f.image_url} onChange={(e) => setF({ ...f, image_url: e.target.value })} /></Field></>}
    <Field label="Change note"><Input value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} /></Field>
    <div className="flex justify-end"><Button onClick={() => api.editContent(it.id, { title: f.title, body: f.body, note: f.note || null,
      data: { ...Object.fromEntries(Object.entries(it.data).filter(([k]) => !["external_url", "removed_promises"].includes(k))), hashtags: f.hashtags, cta: f.cta || null, image_url: f.image_url || null } })
      .then(() => { onClose(); onSaved(); }, fail)}>Save</Button></div></div></Modal>;
}
function ScheduleModal({ it, onClose, onSaved }: { it: ContentItem; onClose: () => void; onSaved: () => void }) {
  const [when, setWhen] = useState(it.scheduled_at ? it.scheduled_at.slice(0, 16) : "");
  return <Modal open title="Calendar date" onClose={onClose}><div className="space-y-3">
    <Field label="Date and time (your local time)"><Input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} /></Field>
    <p className="text-xs text-navy-500">Moving the date keeps the approval. A date alone doesn&apos;t publish anything; use Publish to queue it.</p>
    <div className="flex justify-between"><Button variant="ghost" onClick={() => api.editContent(it.id, { clear_schedule: true }).then(() => { onClose(); onSaved(); }, fail)}>Clear date</Button>
      <Button disabled={!when} onClick={() => api.editContent(it.id, { scheduled_at: new Date(when).toISOString() }).then(() => { onClose(); onSaved(); }, fail)}>Save</Button></div></div></Modal>;
}
function PublishModal({ it, onClose, onSaved }: { it: ContentItem; onClose: () => void; onSaved: () => void }) {
  const acc = useAsync(() => api.listSocialAccounts(it.client_id), [it.client_id]);
  const plat = it.platform === "youtube_shorts" ? "youtube" : it.platform;
  const options = (acc.data?.accounts || []).filter((a) => a.platform === plat && a.status === "connected");
  const [aid, setAid] = useState(""); const [when, setWhen] = useState("");
  return <Modal open title={`Publish to ${PLATFORM_LABEL[it.platform || ""]}`} onClose={onClose}><div className="space-y-3">
    {plat === "youtube" ? <Note>YouTube uploads aren&apos;t automated. Publish in YouTube Studio, then use &quot;Record as published&quot; with the video URL.</Note> :
      acc.loading ? <Skeleton rows={2} /> : !options.length ? <Note>No connected {PLATFORM_LABEL[plat || ""]} account for this client. Connect one under Social accounts.</Note> : <>
        <Field label="Account"><Select value={aid} onChange={(e) => setAid(e.target.value)}><option value="">Choose…</option>{options.map((a) => <option key={a.id} value={a.id} disabled={!a.permissions.can_publish}>{a.account_name}{a.permissions.can_publish ? "" : " (no publish permission)"}</option>)}</Select></Field>
        <Field label="When" hint="Empty = now"><Input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} /></Field>
        <p className="text-xs text-navy-500">Posts the approved version {it.version} through the official API. Editing it afterwards cancels a scheduled post.</p>
        <div className="flex justify-end"><Button disabled={!aid} onClick={() => api.publishContent(it.id, { account_id: aid, scheduled_at: when ? new Date(when).toISOString() : null }).then(() => { onClose(); onSaved(); }, fail)}><Send className="h-4 w-4" />{when ? "Schedule" : "Publish now"}</Button></div></>}
  </div></Modal>;
}
function ManualModal({ it, onClose, onSaved }: { it: ContentItem; onClose: () => void; onSaved: () => void }) {
  const [url, setUrl] = useState("");
  return <Modal open title="Record as published" onClose={onClose}><div className="space-y-3">
    <p className="text-sm text-navy-600">For posts your team published itself. Records the live URL; nothing is posted from here.</p>
    <Field label="Live URL" required><Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://youtu.be/…" /></Field>
    <div className="flex justify-end"><Button disabled={url.length < 8} onClick={() => api.markPublished(it.id, { url }).then(() => { onClose(); onSaved(); }, fail)}>Save</Button></div></div></Modal>;
}

function Studio({ clientId, role, studio, products }: { clientId: string; role: Role; studio: "social" | "seo"; products: Product[] }) {
  const kinds = studio === "social" ? SOCIAL_KINDS : SEO_KINDS;
  const list = useAsync(() => api.listContent(clientId, { studio }), [clientId, studio]);
  const [g, setG] = useState({ kind: kinds[0], platform: "instagram", product_id: "", topic: "", tone: "", count: 1 });
  const [m, setM] = useState({ kind: kinds[0], platform: "linkedin", title: "", body: "" });
  const [busy, setBusy] = useState<string | null>(null); const [filter, setFilter] = useState("");
  const generate = async () => { setBusy("gen"); try { await api.generateContent(clientId, { studio, kind: g.kind, platform: studio === "social" ? g.platform : null, product_id: g.product_id || null, topic: g.topic || null, tone: g.tone || null, count: g.count }); list.reload(); } catch (e) { fail(e); } finally { setBusy(null); } };
  const add = async () => { setBusy("add"); try { await api.addContent(clientId, { studio, kind: m.kind, platform: studio === "social" ? m.platform : null, title: m.title, body: m.body || null }); setM({ ...m, title: "", body: "" }); list.reload(); } catch (e) { fail(e); } finally { setBusy(null); } };
  const items = (list.data || []).filter((i) => !filter || i.status === filter);
  return <div className="space-y-6">
    <LocalNote what="AI drafting" />
    <div className="grid gap-6 lg:grid-cols-2">
      <Card><CardHeader title="AI draft" subtitle={studio === "social" ? "Grounded in the client's products, buyer profiles and approved brand assets" : "Grounded in the client's website and market intelligence; claims are flagged for fact-checking"} />
        <div className="grid gap-3 p-5 sm:grid-cols-2">
          <Field label="Type"><Select value={g.kind} onChange={(e) => setG({ ...g, kind: e.target.value })}>{kinds.map((k) => <option key={k} value={k}>{KIND_LABEL(k)}</option>)}</Select></Field>
          {studio === "social" && <Field label="Platform"><Select value={g.platform} onChange={(e) => setG({ ...g, platform: e.target.value })}>{SOCIAL_PLATFORMS.map((p) => <option key={p} value={p}>{PLATFORM_LABEL[p]}</option>)}</Select></Field>}
          <Field label="Product"><Select value={g.product_id} onChange={(e) => setG({ ...g, product_id: e.target.value })}><option value="">Any</option>{products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select></Field>
          <Field label="How many"><Select value={g.count} onChange={(e) => setG({ ...g, count: Number(e.target.value) })}>{[1, 2, 3, 4, 5].map((n) => <option key={n}>{n}</option>)}</Select></Field>
          <Field label="Topic or angle"><Input value={g.topic} onChange={(e) => setG({ ...g, topic: e.target.value })} placeholder={studio === "social" ? "Diwali greetings, water quality tips…" : "RO plants for dairies in Gujarat"} /></Field>
          <Field label="Tone"><Input value={g.tone} onChange={(e) => setG({ ...g, tone: e.target.value })} placeholder="Professional, plain English" /></Field>
        </div>
        <div className="flex justify-end border-t border-line px-5 py-3"><Button loading={busy === "gen"} onClick={generate}><Sparkles className="h-4 w-4" />Draft</Button></div></Card>
      <Card><CardHeader title="Write it yourself" />
        <div className="grid gap-3 p-5 sm:grid-cols-2">
          <Field label="Type"><Select value={m.kind} onChange={(e) => setM({ ...m, kind: e.target.value })}>{kinds.map((k) => <option key={k} value={k}>{KIND_LABEL(k)}</option>)}</Select></Field>
          {studio === "social" && <Field label="Platform"><Select value={m.platform} onChange={(e) => setM({ ...m, platform: e.target.value })}>{SOCIAL_PLATFORMS.map((p) => <option key={p} value={p}>{PLATFORM_LABEL[p]}</option>)}</Select></Field>}
          <div className="sm:col-span-2"><Field label="Title" required><Input value={m.title} onChange={(e) => setM({ ...m, title: e.target.value })} /></Field></div>
          <div className="sm:col-span-2"><Field label={studio === "social" ? "Caption / script" : "Content"} hint={studio === "social" ? `${m.body.length} / ${LIMITS[m.platform]} characters` : undefined}><Textarea rows={4} value={m.body} onChange={(e) => setM({ ...m, body: e.target.value })} /></Field></div>
        </div>
        <div className="flex justify-end border-t border-line px-5 py-3"><Button variant="secondary" loading={busy === "add"} disabled={m.title.trim().length < 2} onClick={add}><Plus className="h-4 w-4" />Save draft</Button></div></Card>
    </div>
    <Card><CardHeader title={studio === "social" ? "Social content" : "SEO content"} action={<Select value={filter} onChange={(e) => setFilter(e.target.value)} className="w-44"><option value="">All statuses</option>{Object.entries(STATUS_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select>} />
      {list.loading ? <Skeleton /> : list.error ? <ErrorBox message={list.error} /> : !items.length ? <Empty title="Nothing here yet" /> :
        <div className="grid gap-4 p-5 lg:grid-cols-2">{items.map((it) => <ContentCard key={it.id} it={it} role={role} onChange={list.reload} />)}</div>}</Card>
  </div>;
}

// ------------------------------------------------------------------ brand assets
function Assets({ clientId, role }: { clientId: string; role: Role }) {
  const list = useAsync(() => api.listAssets(clientId), [clientId]);
  const docs = useAsync(() => api.listDocuments({ client_id: clientId }), [clientId]);
  const [f, setF] = useState({ kind: "colour", name: "", value: "", document_id: "", notes: "" });
  const add = () => api.addAsset(clientId, { kind: f.kind, name: f.name, value: f.value || null, document_id: f.document_id || null, notes: f.notes || null }).then(() => { setF({ ...f, name: "", value: "", notes: "" }); list.reload(); }, fail);
  return <div className="space-y-6">
    <Card><CardHeader title="Add a brand asset" subtitle="Only approved assets can be attached to content or given to the AI. Never add certifications or awards the client can't prove." />
      <div className="grid gap-3 p-5 md:grid-cols-4">
        <Field label="Type"><Select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>{ASSET_KINDS.map((k) => <option key={k} value={k}>{label(k)}</option>)}</Select></Field>
        <Field label="Name" required><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label={f.kind === "colour" ? "Hex value" : f.kind === "font" ? "Font name" : "https link (or pick a file)"}><Input value={f.value} onChange={(e) => setF({ ...f, value: e.target.value })} placeholder={f.kind === "colour" ? "#0B2A4A" : ""} /></Field>
        {!["colour", "font"].includes(f.kind) && <Field label="Uploaded file"><Select value={f.document_id} onChange={(e) => setF({ ...f, document_id: e.target.value })}><option value="">None</option>{docs.data?.items.map((d) => <option key={d.id} value={d.id}>{d.original_name}</option>)}</Select></Field>}
        <div className="md:col-span-4"><Field label="Usage notes"><Input value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field></div>
      </div>
      <div className="flex justify-end border-t border-line px-5 py-3"><Button disabled={f.name.trim().length < 2} onClick={add}><Plus className="h-4 w-4" />Add</Button></div></Card>
    <Card><CardHeader title="Library" />
      {list.loading ? <Skeleton /> : !list.data?.length ? <Empty title="No assets yet" /> : <Table head={["Asset", "Type", "Value", "Status", ""]}>
        {list.data.map((a) => <tr key={a.id}><td className="px-5 py-2.5 font-medium">{a.name}{a.notes && <div className="text-xs font-normal text-navy-500">{a.notes}</div>}</td><td className="px-5 py-2.5">{label(a.kind)}</td>
          <td className="px-5 py-2.5">{a.kind === "colour" && a.value ? <span className="inline-flex items-center gap-2"><span className="h-4 w-4 rounded border border-line" style={{ background: a.value }} />{a.value}</span> : a.value?.startsWith("https://") ? <a className="text-brand-600" href={a.value} target="_blank" rel="noopener noreferrer">Open</a> : a.value || (a.document_id ? "Uploaded file" : "—")}</td>
          <td className="px-5 py-2.5"><Badge tone={a.approved ? "green" : "amber"}>{a.approved ? "Approved" : "Not approved"}</Badge></td>
          <td className="px-5 py-2.5 text-right">{role !== "staff" && <div className="flex justify-end gap-1"><Button size="sm" variant="secondary" onClick={() => api.approveAsset(a.id, !a.approved).then(list.reload, fail)}>{a.approved ? "Withdraw" : <><Check className="h-4 w-4" />Approve</>}</Button>
            <Button size="sm" variant="ghost" onClick={() => confirm("Delete this asset?") && api.deleteAsset(a.id).then(list.reload, fail)}><Trash2 className="h-4 w-4" /></Button></div>}</td></tr>)}</Table>}</Card>
  </div>;
}

// ------------------------------------------------------------------ ads
function Ads({ clientId, role, products }: { clientId: string; role: Role; products: Product[] }) {
  const list = useAsync(() => api.listAdPlans(clientId), [clientId]);
  const [f, setF] = useState({ platform: "google" as AdPlan["platform"], name: "", product_id: "", objective: "leads", geography: [] as string[], landing_page: "", daily_budget: "", total_budget: "", headlines: [] as string[], ad_copy: "" });
  const [busy, setBusy] = useState<string | null>(null);
  const base = () => ({ platform: f.platform, product_id: f.product_id || null, objective: f.objective || null, geography: f.geography, landing_page: f.landing_page || null, daily_budget: num(f.daily_budget), total_budget: num(f.total_budget) });
  const run = (k: string, p: Promise<unknown>) => { setBusy(k); p.then(() => list.reload(), fail).finally(() => setBusy(null)); };
  const lim = AD_LIMITS[f.platform];
  return <div className="space-y-6">
    <Note tone="blue">Plans only. GrowthCognix doesn&apos;t create ads, change bids or spend money: no ad account is connected, and approving spend only records the decision and cap.</Note>
    <LocalNote what="AI ad drafting" />
    <Card><CardHeader title="New ad plan" />
      <div className="grid gap-3 p-5 md:grid-cols-3">
        <Field label="Platform"><Select value={f.platform} onChange={(e) => setF({ ...f, platform: e.target.value as AdPlan["platform"] })}><option value="google">Google Ads</option><option value="meta">Meta (Facebook & Instagram)</option><option value="linkedin">LinkedIn</option></Select></Field>
        <Field label="Product"><Select value={f.product_id} onChange={(e) => setF({ ...f, product_id: e.target.value })}><option value="">Any</option>{products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select></Field>
        <Field label="Objective"><Select value={f.objective} onChange={(e) => setF({ ...f, objective: e.target.value })}>{["leads", "traffic", "awareness", "conversions", "video_views"].map((o) => <option key={o} value={o}>{label(o)}</option>)}</Select></Field>
        <Field label="Geography"><TagInput value={f.geography} onChange={(v) => setF({ ...f, geography: v })} placeholder="Gujarat, UAE…" /></Field>
        <Field label="Landing page"><Input value={f.landing_page} onChange={(e) => setF({ ...f, landing_page: e.target.value })} /></Field>
        <div className="grid grid-cols-2 gap-2"><Field label="Daily budget"><Input type="number" min={0} value={f.daily_budget} onChange={(e) => setF({ ...f, daily_budget: e.target.value })} /></Field><Field label="Total budget"><Input type="number" min={0} value={f.total_budget} onChange={(e) => setF({ ...f, total_budget: e.target.value })} /></Field></div>
        <Field label="Plan name (manual)"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label={`Headlines (max ${lim.headline} chars)`}><TagInput value={f.headlines} onChange={(v) => setF({ ...f, headlines: v })} /></Field>
        <Field label={`Ad copy (max ${lim.copy} chars)`}><Input value={f.ad_copy} onChange={(e) => setF({ ...f, ad_copy: e.target.value })} /></Field>
      </div>
      <div className="flex justify-end gap-2 border-t border-line px-5 py-3">
        <Button variant="secondary" loading={busy === "add"} disabled={f.name.trim().length < 2} onClick={() => run("add", api.addAdPlan(clientId, { ...base(), name: f.name, headlines: f.headlines, ad_copy: f.ad_copy ? [f.ad_copy] : [] }))}><Plus className="h-4 w-4" />Save manual plan</Button>
        <Button loading={busy === "gen"} onClick={() => run("gen", api.generateAdPlan(clientId, base()))}><Sparkles className="h-4 w-4" />AI draft</Button></div></Card>
    {list.loading ? <Skeleton /> : !list.data?.length ? <Card><Empty title="No ad plans yet" /></Card> : list.data.map((a) => <Card key={a.id}><div className="space-y-3 p-5 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2"><div><span className="font-medium text-navy-900">{a.name}</span> <span className="text-navy-500">· {PLATFORM_LABEL[a.platform]} · {label(a.objective || "—")}</span></div>
        <div className="flex gap-2"><StatusBadge s={a.status} />{a.spend_approved ? <Badge tone="green">Spend approved ≤ {fmtMoney(a.spend_cap, a.currency)}</Badge> : <Badge>Spend not approved</Badge>}</div></div>
      <div className="grid gap-3 md:grid-cols-3">
        <div><div className="text-xs uppercase text-navy-400">Headlines</div><ul className="list-disc pl-4">{a.headlines.map((h, i) => <li key={i}>{h} <span className="text-xs text-navy-400">({h.length})</span></li>)}{!a.headlines.length && <li className="list-none text-navy-400">—</li>}</ul></div>
        <div><div className="text-xs uppercase text-navy-400">Ad copy</div><ul className="list-disc pl-4">{a.ad_copy.map((h, i) => <li key={i}>{h}</li>)}{!a.ad_copy.length && <li className="list-none text-navy-400">—</li>}</ul></div>
        <div className="space-y-1"><div><span className="text-navy-400">Budget:</span> {a.daily_budget != null ? `${fmtMoney(a.daily_budget, a.currency)}/day` : "—"} · {a.total_budget != null ? `${fmtMoney(a.total_budget, a.currency)} total` : "—"}</div>
          <div><span className="text-navy-400">Landing page:</span> {a.landing_page || "—"}</div><div><span className="text-navy-400">Geography:</span> {a.geography.join(", ") || "—"}</div>
          {a.bidding && <div><span className="text-navy-400">Bidding:</span> {a.bidding}</div>}{a.conversion_tracking && <div><span className="text-navy-400">Tracking:</span> {a.conversion_tracking}</div>}</div>
      </div>
      {a.ab_tests.length > 0 && <div><span className="text-navy-400">A/B tests:</span> {a.ab_tests.join("; ")}</div>}
      {a.claims_to_check.length > 0 && <div className="rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800"><ul className="list-disc pl-4">{a.claims_to_check.map((c, i) => <li key={i}>{c}</li>)}</ul></div>}
      <div className="flex flex-wrap items-end justify-between gap-2"><ReviewBar entity="ad_plan" id={a.id} status={a.status} role={role} claims={a.claims_to_check} onDone={list.reload} />
        <div className="flex gap-2">{["admin", "owner"].includes(role) && a.status === "approved" && (a.spend_approved
          ? <Button size="sm" variant="secondary" onClick={() => api.spendApproval(a.id, { approved: false }).then(list.reload, fail)}>Withdraw spend approval</Button>
          : <Button size="sm" onClick={() => { const cap = prompt(`Spend cap (${a.currency})${a.total_budget ? `, up to ${a.total_budget}` : ""}`); if (cap) api.spendApproval(a.id, { approved: true, spend_cap: Number(cap) }).then(list.reload, fail); }}>Approve spend…</Button>)}
          {role !== "staff" && <Button size="sm" variant="ghost" onClick={() => confirm("Delete this plan?") && api.deleteAdPlan(a.id).then(list.reload, fail)}><Trash2 className="h-4 w-4" /></Button>}</div></div>
    </div></Card>)}
  </div>;
}

// ------------------------------------------------------------------ calendar
function CalendarView({ clientId, role }: { clientId: string; role: Role }) {
  const [month, setMonth] = useState(() => { const d = new Date(); return new Date(d.getFullYear(), d.getMonth(), 1); });
  const [view, setView] = useState<"month" | "week" | "quarter">("month");
  const range = useMemo(() => {
    if (view === "week") { const s = new Date(); s.setHours(0, 0, 0, 0); s.setDate(s.getDate() - ((s.getDay() + 6) % 7)); const e = new Date(s); e.setDate(e.getDate() + 7); return [s, e]; }
    const e = new Date(month.getFullYear(), month.getMonth() + (view === "quarter" ? 3 : 1), 1); return [month, e];
  }, [month, view]);
  const cal = useAsync(() => api.calendar(clientId, range[0].toISOString(), range[1].toISOString()), [clientId, range[0].getTime(), range[1].getTime()]);
  const [drag, setDrag] = useState<string | null>(null);
  const items = cal.data?.items || [];
  const days: Date[] = [];
  if (view === "month") { const first = new Date(month); first.setDate(1 - ((first.getDay() + 6) % 7)); for (let i = 0; i < 42; i++) { const d = new Date(first); d.setDate(first.getDate() + i); days.push(d); } }
  else if (view === "week") for (let i = 0; i < 7; i++) { const d = new Date(range[0]); d.setDate(d.getDate() + i); days.push(d); }
  const key = (d: Date) => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
  const byDay: Record<string, ContentItem[]> = {};
  items.forEach((i) => { const d = new Date(i.scheduled_at || i.published_at!); (byDay[key(d)] ||= []).push(i); });
  const drop = async (d: Date) => {
    const it = items.find((x) => x.id === drag); setDrag(null);
    if (!it || it.status === "published") return;
    const old = new Date(it.scheduled_at!); const n = new Date(d); n.setHours(old.getHours(), old.getMinutes());
    try { await api.editContent(it.id, { scheduled_at: n.toISOString() }); cal.reload(); } catch (e) { fail(e); }
  };
  return <div className="space-y-4">
    <Card><div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
      <div className="flex items-center gap-2">
        {view !== "week" && <><Button size="sm" variant="ghost" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - (view === "quarter" ? 3 : 1), 1))}><ChevronLeft className="h-4 w-4" /></Button>
          <span className="w-40 text-center font-medium">{month.toLocaleDateString(undefined, { month: "long", year: "numeric" })}{view === "quarter" && " +2"}</span>
          <Button size="sm" variant="ghost" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + (view === "quarter" ? 3 : 1), 1))}><ChevronRight className="h-4 w-4" /></Button></>}
        {view === "week" && <span className="font-medium">This week</span>}
      </div>
      <div className="flex gap-1">{(["week", "month", "quarter"] as const).map((v) => <button key={v} onClick={() => setView(v)} className={cx("rounded-md px-3 py-1 text-sm", view === v ? "bg-brand-600 text-white" : "text-navy-600 hover:bg-canvas")}>{label(v)}</button>)}</div>
    </div></Card>
    {cal.loading ? <Skeleton /> : cal.error ? <ErrorBox message={cal.error} /> : view === "quarter" ? <Card>{!items.length ? <Empty title="Nothing dated in these three months" /> :
      <Table head={["Date", "Platform", "Title", "Status"]}>{items.map((i) => <tr key={i.id}><td className="px-5 py-2">{fmtDateTime(i.scheduled_at || i.published_at)}</td><td className="px-5 py-2">{PLATFORM_LABEL[i.platform || ""]}</td><td className="px-5 py-2">{i.title}</td><td className="px-5 py-2"><StatusBadge s={i.status} /></td></tr>)}</Table>}</Card> :
      <Card><div className="grid grid-cols-7 border-b border-line text-center text-xs font-medium uppercase text-navy-400">{["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => <div key={d} className="py-2">{d}</div>)}</div>
        <div className="grid grid-cols-7">{days.map((d) => <div key={d.toISOString()} onDragOver={(e) => e.preventDefault()} onDrop={() => drop(d)}
          className={cx("min-h-[96px] border-b border-r border-line p-1.5 text-xs", view === "month" && d.getMonth() !== month.getMonth() && "bg-canvas/50 text-navy-300")}>
          <div className="mb-1 text-right text-navy-400">{d.getDate()}</div>
          {(byDay[key(d)] || []).map((i) => <div key={i.id} draggable={i.status !== "published"} onDragStart={() => setDrag(i.id)} title={`${i.title} · ${STATUS_LABEL[i.status]}`}
            className={cx("mb-1 cursor-grab truncate rounded px-1.5 py-0.5", i.status === "published" ? "bg-emerald-50 text-emerald-700" : i.status === "scheduled" ? "bg-brand-50 text-brand-700" : "bg-amber-50 text-amber-800")}>
            {new Date(i.scheduled_at || i.published_at!).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })} {PLATFORM_LABEL[i.platform || ""]?.split(" ")[0]} · {i.title}</div>)}
        </div>)}</div></Card>}
    <p className="text-xs text-navy-500">Drag an item to another day to move it (approval is kept). Give items a date from the studios. Times show in your browser&apos;s time zone.</p>
    {cal.data && <CalendarSettingsCard clientId={clientId} role={role} s={cal.data.settings} onSaved={cal.reload} />}
  </div>;
}
function CalendarSettingsCard({ clientId, role, s, onSaved }: { clientId: string; role: Role; s: { timezone: string; require_client_review: boolean; default_reviewer_id: string | null }; onSaved: () => void }) {
  const [f, setF] = useState(s);
  return <Card><CardHeader title="Calendar settings" /><div className="flex flex-wrap items-end gap-4 p-5">
    <Field label="Client time zone"><Input value={f.timezone} onChange={(e) => setF({ ...f, timezone: e.target.value })} /></Field>
    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.require_client_review} onChange={(e) => setF({ ...f, require_client_review: e.target.checked })} />Require client approval after internal approval</label>
    {role !== "staff" && <Button size="sm" onClick={() => api.saveCalendarSettings(clientId, f).then(onSaved, fail)}>Save</Button>}</div></Card>;
}

// ------------------------------------------------------------------ approvals
function Approvals({ clientId, role }: { clientId: string; role: Role }) {
  const [status, setStatus] = useState("pending");
  const list = useAsync(() => api.marketingApprovals(clientId, status || null), [clientId, status]);
  return <Card><CardHeader title="Approval centre" subtitle="Strategies, budgets, content and ad plans waiting on a person" action={<Select value={status} onChange={(e) => setStatus(e.target.value)} className="w-40"><option value="pending">Pending</option><option value="approved">Approved</option><option value="rejected">Rejected</option><option value="">All</option></Select>} />
    {list.loading ? <Skeleton /> : list.error ? <ErrorBox message={list.error} /> : !list.data!.length ? <Empty title="Nothing waiting" body="Items submitted for review appear here." /> :
      <ul className="divide-y divide-line">{list.data!.map((a: ApprovalRow) => <li key={a.id} className="space-y-2 px-5 py-4 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-2"><div><span className="font-medium text-navy-900">{a.title}</span> <span className="text-navy-500">· {label(a.entity_type)}{a.platform ? ` · ${PLATFORM_LABEL[a.platform] || a.platform}` : ""}{a.kind ? ` · ${KIND_LABEL(a.kind)}` : ""} · {label(a.stage)} · v{a.entity_version}</span></div>
          <span className="flex items-center gap-2">{a.entity_status && <StatusBadge s={a.entity_status} />}<span className="text-xs text-navy-400">{fmtDateTime(a.created_at)}</span></span></div>
        {a.note && <p className="text-navy-500">{a.note}</p>}
        {!!a.claims_to_check?.length && <div className="rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800"><ul className="list-disc pl-4">{a.claims_to_check.map((c, i) => <li key={i}>{c}</li>)}</ul></div>}
        {a.status === "pending" && a.entity_status && <ReviewBar entity={a.entity_type} id={a.entity_id} status={a.entity_status} role={role} claims={a.claims_to_check} onDone={list.reload} />}
      </li>)}</ul>}</Card>;
}

// ------------------------------------------------------------------ accounts
function Accounts({ clientId, role }: { clientId: string; role: Role }) {
  const acc = useAsync(() => api.listSocialAccounts(clientId), [clientId]);
  const connect = (p: "facebook" | "instagram" | "linkedin") => api.connectSocial(clientId, p).then((r) => { window.location.href = r.authorize_url; }, fail);
  return <div className="space-y-6">
    <Note tone="blue">Accounts connect through each platform&apos;s official OAuth sign-in. Tokens are stored encrypted on the server, and no browser automation is used. Meta needs App Review for publishing permissions; LinkedIn posting needs the Share on LinkedIn product.</Note>
    {acc.loading ? <Skeleton /> : acc.error ? <ErrorBox message={acc.error} /> : <>
      <Card><CardHeader title="Platforms" /><Table head={["Platform", "Server", "Limits & permissions", ""]}>
        {acc.data!.platforms.map((p) => <tr key={p.platform}><td className="px-5 py-2.5 font-medium">{PLATFORM_LABEL[p.platform]}</td>
          <td className="px-5 py-2.5"><Badge tone={p.configured ? "green" : p.automated ? "slate" : "amber"}>{p.configured ? "Configured" : p.automated ? `Needs ${p.missing.join(", ")}` : "Manual only"}</Badge></td>
          <td className="px-5 py-2.5 text-xs text-navy-500">{p.note}</td>
          <td className="px-5 py-2.5 text-right">{role !== "staff" && p.automated && p.platform !== "youtube" && <Button size="sm" disabled={!p.configured && !local()} onClick={() => connect(p.platform as "facebook")}><Link2 className="h-4 w-4" />Connect</Button>}</td></tr>)}</Table></Card>
      <Card><CardHeader title="Connected accounts" />{!acc.data!.accounts.length ? <Empty title="No accounts connected" body="Nothing is posted until an account is connected and content is approved." /> :
        <Table head={["Account", "Platform", "Status", "Can publish", "Token expires", ""]}>{acc.data!.accounts.map((a) => <tr key={a.id}>
          <td className="px-5 py-2.5 font-medium">{a.account_name}{a.last_error && <div className="text-xs font-normal text-red-600">{a.last_error}</div>}</td><td className="px-5 py-2.5">{PLATFORM_LABEL[a.platform]}</td>
          <td className="px-5 py-2.5"><Badge tone={a.status === "connected" ? "green" : "red"}>{label(a.status)}</Badge></td><td className="px-5 py-2.5">{a.permissions.can_publish ? "Yes" : "No"}</td>
          <td className="px-5 py-2.5 text-navy-500">{fmtDate(a.token_expires_at)}</td>
          <td className="px-5 py-2.5 text-right">{role !== "staff" && a.status === "connected" && <Button size="sm" variant="ghost" onClick={() => confirm("Disconnect and delete the stored token?") && api.disconnectSocial(a.id).then(acc.reload, fail)}><Unplug className="h-4 w-4" /></Button>}</td></tr>)}</Table>}</Card>
    </>}
  </div>;
}

// ------------------------------------------------------------------ publishing history
function Jobs({ clientId, role }: { clientId: string; role: Role }) {
  const [status, setStatus] = useState("");
  const jobs = useAsync(() => api.publishingJobs(clientId, status || undefined), [clientId, status]);
  return <Card><CardHeader title="Publishing history" action={<Select value={status} onChange={(e) => setStatus(e.target.value)} className="w-40"><option value="">All</option>{["queued", "publishing", "published", "failed", "cancelled"].map((s) => <option key={s} value={s}>{label(s)}</option>)}</Select>} />
    {jobs.loading ? <Skeleton /> : jobs.error ? <ErrorBox message={jobs.error} /> : !jobs.data!.length ? <Empty title="Nothing published yet" /> :
      <Table head={["Content", "Platform", "Status", "When", "Result", ""]}>{jobs.data!.map((j) => <tr key={j.id}>
        <td className="px-5 py-2.5 font-medium">{j.title || "—"} <span className="text-xs text-navy-400">v{j.content_version}</span></td><td className="px-5 py-2.5">{PLATFORM_LABEL[j.platform] || j.platform}</td>
        <td className="px-5 py-2.5"><Badge tone={j.status === "published" ? "green" : j.status === "failed" ? "red" : j.status === "cancelled" ? "slate" : "blue"}>{label(j.status)}</Badge></td>
        <td className="px-5 py-2.5 text-navy-500">{fmtDateTime(j.published_at || j.scheduled_at || j.created_at)}</td>
        <td className="px-5 py-2.5 text-xs">{j.external_url ? <a href={j.external_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-brand-600">View <ExternalLink className="h-3 w-3" /></a> : j.error ? <span className="text-red-600">{j.error}</span> : "—"}</td>
        <td className="px-5 py-2.5 text-right">{role !== "staff" && j.status === "queued" && <Button size="sm" variant="ghost" onClick={() => api.cancelPublishingJob(j.id).then(jobs.reload, fail)}>Cancel</Button>}
          {role !== "staff" && j.status === "failed" && <Button size="sm" variant="secondary" onClick={() => api.retryPublishingJob(j.id).then(jobs.reload, fail)}>Retry</Button>}</td></tr>)}</Table>}</Card>;
}

// ------------------------------------------------------------------ analytics
function Analytics({ clientId }: { clientId: string }) {
  const an = useAsync(() => api.marketingAnalytics(clientId), [clientId]);
  const [msg, setMsg] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const refresh = async () => { setBusy(true); try { const r = await api.refreshAnalytics(clientId); setMsg(`${r.posts_updated} post(s) updated.${r.errors.length ? " " + r.errors.join(" ") : ""}`); an.reload(); } catch (e) { fail(e); } finally { setBusy(false); } };
  return <div className="space-y-6">
    <div className="flex items-center justify-between"><p className="text-sm text-navy-500">Platform-reported numbers and GrowthCognix calculations are shown separately. Anything not connected stays empty.</p><Button loading={busy} onClick={refresh}><RefreshCw className="h-4 w-4" />Refresh from platforms</Button></div>
    {msg && <Note tone="blue">{msg}</Note>}
    {an.loading ? <Skeleton /> : an.error ? <ErrorBox message={an.error} /> : <>
      <Card><CardHeader title="Reported by the platform" />{!an.data!.platform.length ? <Empty title="—" body="No connected platform has reported metrics yet." /> :
        <Table head={["Post", "Platform", "Metric", "Value", "Retrieved"]}>{an.data!.platform.map((m, i) => <tr key={i}><td className="px-5 py-2">{m.title || m.external_id}</td><td className="px-5 py-2">{PLATFORM_LABEL[m.platform]}</td><td className="px-5 py-2">{label(m.metric)}</td><td className="px-5 py-2 font-medium">{m.value.toLocaleString()}</td><td className="px-5 py-2 text-navy-500">{fmtDateTime(m.retrieved_at)}</td></tr>)}</Table>}</Card>
      <Card><CardHeader title="Calculated by GrowthCognix" subtitle="Derived only from the reported values above" />{!an.data!.calculated.length ? <Empty title="—" /> :
        <Table head={["Post", "Metric", "Value", "Formula"]}>{an.data!.calculated.map((m, i) => <tr key={i}><td className="px-5 py-2">{m.title || m.external_id}</td><td className="px-5 py-2">{label(m.metric)}</td><td className="px-5 py-2 font-medium">{m.value.toLocaleString()}</td><td className="px-5 py-2 text-xs text-navy-500">{m.formula}</td></tr>)}</Table>}</Card>
      <Card><CardHeader title="Not available yet" /><ul className="divide-y divide-line text-sm">{Object.entries(an.data!.not_available).map(([k, v]) => <li key={k} className="flex gap-4 px-5 py-2.5"><span className="w-24 font-medium">{k === "ads" ? "Ads" : PLATFORM_LABEL[k] || label(k)}</span><span className="text-navy-500">{v}</span></li>)}</ul></Card>
    </>}
  </div>;
}

// ------------------------------------------------------------------ reports
function Reports({ clientId, clientName, role }: { clientId: string; clientName: string; role: Role }) {
  const list = useAsync(() => api.listMarketingReports(clientId), [clientId]);
  const today = new Date().toISOString().slice(0, 10); const monthAgo = new Date(Date.now() - 30 * 864e5).toISOString().slice(0, 10);
  const [f, setF] = useState({ start: monthAgo, end: today }); const [view, setView] = useState<{ title: string; md: string } | null>(null);
  const open = async (id: string, title: string) => { try { setView({ title, md: await api.marketingReportMarkdown(id) }); } catch (e) { fail(e); } };
  const download = (v: { title: string; md: string }) => { const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([v.md], { type: "text/markdown" })); a.download = `${clientName}-${v.title}.md`.replace(/[^\w.-]+/g, "_"); a.click(); };
  return <div className="space-y-6">
    <Card><CardHeader title="New client report" subtitle="Composed only from stored records and platform-reported numbers" />
      <div className="flex flex-wrap items-end gap-3 p-5"><Field label="From"><Input type="date" value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} /></Field><Field label="To"><Input type="date" value={f.end} onChange={(e) => setF({ ...f, end: e.target.value })} /></Field>
        <Button onClick={() => api.createMarketingReport(clientId, f).then((r) => { list.reload(); open(r.id, r.title); }, fail)}><Plus className="h-4 w-4" />Create report</Button></div></Card>
    <Card><CardHeader title="Reports" />{list.loading ? <Skeleton /> : !list.data?.length ? <Empty title="No reports yet" /> :
      <ul className="divide-y divide-line">{list.data.map((r) => <li key={r.id} className="flex items-center justify-between px-5 py-3 text-sm"><button className="text-left font-medium text-navy-900 hover:text-brand-700" onClick={() => open(r.id, r.title)}>{r.title}</button>
        <span className="flex items-center gap-2 text-xs text-navy-400">{fmtDate(r.created_at)}{role !== "staff" && <Button size="sm" variant="ghost" onClick={() => confirm("Delete this report?") && api.deleteMarketingReport(r.id).then(list.reload, fail)}><Trash2 className="h-4 w-4" /></Button>}</span></li>)}</ul>}</Card>
    {view && <Modal open title={view.title} onClose={() => setView(null)}><pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap rounded-lg bg-canvas p-4 text-xs text-navy-800">{view.md}</pre>
      <div className="mt-3 flex justify-end"><Button variant="secondary" onClick={() => download(view)}><Download className="h-4 w-4" />Download .md</Button></div></Modal>}
  </div>;
}

// ------------------------------------------------------------------ shell
export function MarketingStudio({ clientId, clientName, archived, products }: { clientId: string; clientName: string; archived: boolean; products: Product[] }) {
  const { session } = useAuth();
  const role = (session?.user.role || "staff") as Role;
  const [screen, setScreen] = useState<Screen>("Overview");
  return <div>
    {archived && <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">This client is archived. Restore it before planning new marketing.</div>}
    <div className="mb-6 flex flex-wrap gap-1.5">{SCREENS.map((s) => <button key={s} onClick={() => setScreen(s)} className={cx("rounded-full border px-3 py-1 text-xs transition",
      screen === s ? "border-brand-600 bg-brand-600 text-white" : "border-line bg-white text-navy-600 hover:border-brand-300")}>{s}</button>)}</div>
    {screen === "Overview" && <Overview clientId={clientId} go={setScreen} />}
    {screen === "AI strategy" && <Strategy clientId={clientId} role={role} products={products} />}
    {screen === "Budget planner" && <Budgets clientId={clientId} role={role} />}
    {screen === "Social studio" && <Studio clientId={clientId} role={role} studio="social" products={products} />}
    {screen === "SEO studio" && <Studio clientId={clientId} role={role} studio="seo" products={products} />}
    {screen === "Creative assets" && <Assets clientId={clientId} role={role} />}
    {screen === "Ad planner" && <Ads clientId={clientId} role={role} products={products} />}
    {screen === "Calendar" && <CalendarView clientId={clientId} role={role} />}
    {screen === "Approval centre" && <Approvals clientId={clientId} role={role} />}
    {screen === "Social accounts" && <Accounts clientId={clientId} role={role} />}
    {screen === "Publishing history" && <Jobs clientId={clientId} role={role} />}
    {screen === "Analytics" && <Analytics clientId={clientId} />}
    {screen === "Reports" && <Reports clientId={clientId} clientName={clientName} role={role} />}
  </div>;
}
