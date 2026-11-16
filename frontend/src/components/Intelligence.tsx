"use client";
import { Brain, Check, Download, FileText, Pencil, Play, Plus, RotateCcw, Square, Trash2, Undo2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDateTime, timeAgo } from "@/lib/format";
import { CATEGORY_LABEL, ENUMS, LABEL, SCOPE_LABEL, STATUS_LABEL, statusText } from "@/lib/intelligence";
import { ApiError, type Analysis, type Finding, type FindingType, type Product, type VerificationStatus } from "@/lib/types";
import { useAsync } from "@/lib/useAsync";
import { Badge, Button, Card, CardHeader, Empty, ErrorBox, Field, Input, Modal, Select, Skeleton, TagInput, Textarea, cx } from "./ui";

const SECTIONS = ["Overview", "Products & applications", "Buyer personas", "Target markets", "Opportunities", "Evidence", "History"] as const;
type Section = (typeof SECTIONS)[number];

const TONE: Record<VerificationStatus, "green" | "violet" | "amber" | "red"> = { verified: "green", ai_hypothesis: "violet", needs_review: "amber", rejected: "red" };
const RANK = { staff: 0, manager: 1, admin: 2, owner: 3 } as const;

// ------------------------------------------------------------------ form config per finding type
type FieldDef = { key: string; label: string; kind: "text" | "textarea" | "tags" | "select" | "product" | "facts"; options?: string[]; hint?: string };
const FORMS: Record<FindingType, FieldDef[]> = {
  profile: [
    { key: "summary", label: "Company overview", kind: "textarea" },
    { key: "value_proposition", label: "Value proposition", kind: "textarea" },
    { key: "facts", label: "Facts", kind: "facts", hint: "One per line as  key: value  (e.g. founded: 1998). Only facts a source states." },
  ],
  application: [
    { key: "product_id", label: "Product", kind: "product" },
    { key: "application", label: "Application", kind: "text" },
    { key: "application_type", label: "Type", kind: "select", options: ENUMS.application_type },
    { key: "industry", label: "Industry", kind: "text" },
    { key: "description", label: "Description", kind: "textarea" },
    { key: "businesses_needing", label: "Businesses that need it", kind: "tags" },
    { key: "buyer_categories", label: "Buyer categories", kind: "tags" },
    { key: "pain_points", label: "Pain points solved", kind: "tags" },
    { key: "purchase_reasons", label: "Purchase reasons", kind: "tags" },
    { key: "substitutes", label: "Substitutes / alternatives", kind: "tags" },
  ],
  persona: [
    { key: "name", label: "Persona name", kind: "text" },
    { key: "product_id", label: "Product (optional)", kind: "product" },
    { key: "buyer_category", label: "Buyer category", kind: "text" },
    { key: "industry", label: "Industry", kind: "text" },
    { key: "company_size", label: "Company size", kind: "text" },
    { key: "job_titles", label: "Job titles", kind: "tags" },
    { key: "departments", label: "Departments", kind: "tags" },
    { key: "pain_points", label: "Pain points", kind: "tags" },
    { key: "purchase_reasons", label: "Purchase reasons", kind: "tags" },
    { key: "description", label: "Description", kind: "textarea" },
  ],
  market: [
    { key: "scope", label: "Scope", kind: "select", options: ENUMS.scope },
    { key: "name", label: "Market name", kind: "text", hint: "e.g. Karnataka, Pune, Germany" },
    { key: "parent", label: "Parent region", kind: "text" },
    { key: "product_id", label: "Product (optional)", kind: "product" },
    { key: "priority", label: "Priority", kind: "select", options: ENUMS.priority },
    { key: "rationale", label: "Rationale", kind: "textarea" },
  ],
  insight: [
    { key: "category", label: "Category", kind: "select", options: ENUMS.category },
    { key: "title", label: "Title", kind: "text" },
    { key: "product_id", label: "Product (optional)", kind: "product" },
    { key: "field", label: "Field (for product facts)", kind: "text", hint: "e.g. material, certification, capacity" },
    { key: "detail", label: "Detail", kind: "textarea" },
  ],
};
const TYPE_NAME: Record<FindingType, string> = { profile: "company profile", application: "application", persona: "buyer persona", market: "target market", insight: "insight" };
const optLabel = (k: string, o: string) => (k === "scope" ? SCOPE_LABEL[o] : k === "category" ? CATEGORY_LABEL[o] : LABEL(o));

function FindingModal({ type, clientId, products, initial, defaults, onClose, onSaved }: {
  type: FindingType; clientId: string; products: Product[]; initial?: Finding | null; defaults?: Record<string, unknown>;
  onClose: () => void; onSaved: () => void;
}) {
  const fields = FORMS[type];
  const start = () => {
    const d: Record<string, unknown> = { ...(defaults || {}), ...(initial?.data || {}) };
    if (type === "profile") d.facts = Object.entries((d.facts as Record<string, string>) || {}).map(([k, v]) => `${k}: ${v}`).join("\n");
    return d;
  };
  const [v, setV] = useState<Record<string, unknown>>(start);
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const set = (k: string, val: unknown) => setV({ ...v, [k]: val });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setErr(null); setBusy(true);
    const data: Record<string, unknown> = {};
    for (const f of fields) {
      let val = v[f.key];
      if (f.kind === "facts") val = Object.fromEntries(String(val || "").split("\n").map((l) => l.split(/:(.*)/s)).filter((p) => p[0]?.trim() && p[1]?.trim()).map(([a, b]) => [a.trim().toLowerCase().replace(/\s+/g, "_"), b.trim()]));
      if (f.kind === "tags") val = (val as string[] | undefined) || [];
      if (initial || (val !== undefined && val !== "")) data[f.key] = val ?? null;
    }
    try {
      if (initial) await api.editFinding(type, initial.id, data);
      else await api.createFinding(clientId, type, { data, note: note || null });
      onSaved(); onClose();
    } catch (e) { setErr(e instanceof ApiError ? e.message : "Could not save"); } finally { setBusy(false); }
  };

  return (
    <Modal open onClose={onClose} title={initial ? `Edit ${TYPE_NAME[type]}` : `Add ${TYPE_NAME[type]}`}>
      <form onSubmit={submit} noValidate className="space-y-4">
        {err && <div className="-m-5 mb-0"><ErrorBox message={err} /></div>}
        <div className="grid gap-4 md:grid-cols-2">
          {fields.map((f) => {
            const wide = ["textarea", "tags", "facts"].includes(f.kind);
            const val = v[f.key];
            return (
              <div key={f.key} className={wide ? "md:col-span-2" : ""}>
                <Field label={f.label} hint={f.hint}>
                  {f.kind === "text" && <Input value={(val as string) || ""} onChange={(e) => set(f.key, e.target.value)} />}
                  {f.kind === "textarea" && <Textarea value={(val as string) || ""} onChange={(e) => set(f.key, e.target.value)} />}
                  {f.kind === "facts" && <Textarea value={(val as string) || ""} onChange={(e) => set(f.key, e.target.value)} placeholder={"founded: 1998\nheadquarters: Pune"} />}
                  {f.kind === "tags" && <TagInput value={(val as string[]) || []} onChange={(t) => set(f.key, t)} />}
                  {f.kind === "select" && <Select value={(val as string) || ""} onChange={(e) => set(f.key, e.target.value)}>
                    <option value="">Select…</option>{f.options!.map((o) => <option key={o} value={o}>{optLabel(f.key, o)}</option>)}</Select>}
                  {f.kind === "product" && <Select value={(val as string) || ""} onChange={(e) => set(f.key, e.target.value)}>
                    <option value="">{type === "application" ? "Select a product…" : "Any / all products"}</option>{products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select>}
                </Field>
              </div>
            );
          })}
          {!initial && <div className="md:col-span-2"><Field label="Source or note" hint="Where this comes from: a document, a call with the client, a web page."><Input value={note} onChange={(e) => setNote(e.target.value)} /></Field></div>}
        </div>
        <p className="text-xs text-navy-500">{initial ? "Saving an edit clears any earlier approval: the finding goes back for review." : "New findings start as Needs review. Personas, markets, indirect uses and opportunities stay AI hypotheses even after approval."}</p>
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" loading={busy}>{initial ? "Save" : "Add"}</Button></div>
      </form>
    </Modal>
  );
}

// ------------------------------------------------------------------ a finding card with review controls
function StatusBadge({ f }: { f: Finding }) {
  return <Badge tone={TONE[f.verification_status]}>{statusText(f)}</Badge>;
}

function FindingCard({ f, products, onEdit, onChanged, children }: {
  f: Finding; products: Product[]; onEdit: (f: Finding) => void; onChanged: () => void; children: React.ReactNode;
}) {
  const { session } = useAuth(); const role = session?.user.role || "staff";
  const [busy, setBusy] = useState(false); const [showEv, setShowEv] = useState(false);
  const product = products.find((p) => p.id === f.data.product_id);
  const run = async (fn: () => Promise<unknown>) => { setBusy(true); try { await fn(); onChanged(); } catch (e) { alert(e instanceof Error ? e.message : "Failed"); } finally { setBusy(false); } };
  const review = (action: "approve" | "reject" | "needs_review") => {
    const note = action === "reject" ? prompt("Reason for rejecting (optional)") : null;
    if (action === "reject" && note === null) return;
    run(() => api.reviewFinding(f.type, f.id, action, note));
  };
  return (
    <div className={cx("rounded-xl border p-4", f.verification_status === "rejected" ? "border-red-100 bg-red-50/30" : "border-line")}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <StatusBadge f={f} />
          {f.is_inferred && f.verification_status !== "ai_hypothesis" && <Badge tone="violet">Inferred</Badge>}
          {product && <Badge tone="blue">{product.name}</Badge>}
          <Badge>{f.origin === "ai" ? "AI" : "Team"}</Badge>
          {f.edited && <Badge>Edited</Badge>}
          {f.confidence != null && <span className="text-xs text-navy-500">Confidence {Math.round(f.confidence * 100)}%</span>}
        </div>
        <div className="flex gap-1">
          <button onClick={() => onEdit(f)} className="rounded p-1.5 text-navy-500 hover:bg-canvas" aria-label="Edit"><Pencil className="h-4 w-4" /></button>
          {RANK[role] >= RANK.admin && <button disabled={busy} onClick={() => confirm("Delete this finding permanently? Rejecting keeps an audit trail instead.") && run(() => api.deleteFinding(f.type, f.id))} className="rounded p-1.5 text-navy-500 hover:bg-red-50 hover:text-red-600" aria-label="Delete"><Trash2 className="h-4 w-4" /></button>}
        </div>
      </div>
      <div className="mt-3 text-sm text-navy-800">{children}</div>
      {f.review_note && <p className="mt-2 text-xs text-navy-500">Review note: {f.review_note}</p>}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3">
        <button onClick={() => setShowEv(!showEv)} className="text-xs font-medium text-brand-600 hover:underline">{f.evidence.length} evidence item{f.evidence.length === 1 ? "" : "s"}</button>
        {RANK[role] >= RANK.manager && <div className="flex gap-1.5">
          {!(f.approved && f.verification_status !== "rejected") && <Button size="sm" variant="secondary" loading={busy} onClick={() => review("approve")}><Check className="h-3.5 w-3.5" />Approve</Button>}
          {f.verification_status !== "rejected" && <Button size="sm" variant="danger" disabled={busy} onClick={() => review("reject")}><X className="h-3.5 w-3.5" />Reject</Button>}
          {(f.approved || f.verification_status === "rejected") && <Button size="sm" variant="ghost" disabled={busy} onClick={() => review("needs_review")}><Undo2 className="h-3.5 w-3.5" />Send back</Button>}
        </div>}
      </div>
      {showEv && <EvidenceList items={f.evidence} />}
    </div>
  );
}

function EvidenceList({ items }: { items: Finding["evidence"] }) {
  if (!items.length) return <p className="mt-2 text-xs text-navy-500">No evidence recorded. Treat this as unverified.</p>;
  return (
    <ul className="mt-2 space-y-2">
      {items.map((e) => (
        <li key={e.id} className="rounded-lg bg-canvas p-2.5 text-xs text-navy-700">
          <div className="mb-1 flex flex-wrap gap-1.5"><Badge>{LABEL(e.source_type)}</Badge>
            {e.quote_matched === true && <Badge tone="green">Quote found in source</Badge>}
            {e.quote_matched === false && <Badge tone="amber">Quote not found in source</Badge>}
            {e.source_url && <a href={e.source_url} target="_blank" rel="noopener noreferrer" className="text-brand-600 hover:underline">{e.source_url.replace(/^https?:\/\//, "").slice(0, 60)}</a>}</div>
          {e.excerpt ? <q className="italic">{e.excerpt}</q> : "—"}
        </li>))}
    </ul>
  );
}

const List = ({ label, items }: { label: string; items?: unknown }) => {
  const arr = (items as string[]) || [];
  return arr.length ? <div className="mt-2"><span className="text-xs font-medium uppercase tracking-wide text-navy-400">{label}</span><div className="mt-1 flex flex-wrap gap-1">{arr.map((x) => <Badge key={x}>{x}</Badge>)}</div></div> : null;
};
const s = (f: Finding, k: string) => (f.data[k] as string | null) || "";

// ------------------------------------------------------------------ analysis runner
function AnalysisPanel({ clientId, archived, onDone }: { clientId: string; archived: boolean; onDone: () => void }) {
  const runs = useAsync(() => api.listAnalyses(clientId), [clientId]);
  const prov = useAsync(() => api.intelligenceProviders());
  const [busy, setBusy] = useState(false); const [err, setErr] = useState<string | null>(null);
  const latest = runs.data?.[0];
  const active = latest && ["queued", "running"].includes(latest.status);
  const local = api.mode === "local";
  const configured = prov.data?.providers.some((p) => p.configured);

  useEffect(() => {
    if (!active) return;
    const t = setInterval(async () => {
      const j = await api.listAnalyses(clientId).catch(() => null);
      if (j) { runs.setData(j); if (!["queued", "running"].includes(j[0]?.status)) onDone(); }
    }, 3000);
    return () => clearInterval(t);
  }, [active, clientId]); // eslint-disable-line react-hooks/exhaustive-deps

  const go = async (fn: () => Promise<Analysis>) => { setBusy(true); setErr(null); try { await fn(); await runs.reload(); } catch (e) { setErr(e instanceof Error ? e.message : "Failed"); } finally { setBusy(false); } };

  return (
    <Card>
      <CardHeader title="AI analysis" subtitle="Reads this client's documents, website and catalogue, then builds findings with evidence."
        action={!archived && <div className="flex gap-2">
          {active ? <Button variant="secondary" loading={busy} onClick={() => go(() => api.cancelAnalysis(latest!.id))}><Square className="h-4 w-4" />Cancel</Button>
            : latest && ["failed", "cancelled"].includes(latest.status) && !local
              ? <Button variant="secondary" loading={busy} onClick={() => go(() => api.retryAnalysis(latest.id))}><RotateCcw className="h-4 w-4" />Retry failed stages</Button> : null}
          {!active && <Button loading={busy} disabled={local} onClick={() => go(() => api.startAnalysis(clientId))}><Play className="h-4 w-4" />Run analysis</Button>}
        </div>} />
      <div className="space-y-3 p-5 text-sm">
        {local && <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-amber-800">This browser preview has no server, so AI analysis can&apos;t run here. API keys are kept only on the backend. You can still add, edit and review findings by hand. Run the backend with a Gemini or Groq key to enable analysis.</div>}
        {!local && prov.data && !configured && <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-amber-800">No AI provider is configured. Set GEMINI_API_KEY and/or GROQ_API_KEY on the backend. Document text extraction still runs without them.</div>}
        {!local && prov.data && <div className="flex flex-wrap gap-2 text-xs">{prov.data.providers.map((p) => <Badge key={p.name} tone={p.configured ? "green" : "slate"}>{p.name} · {p.model} · {p.configured ? `ready (${p.used_for})` : "no key"}</Badge>)}</div>}
        {err && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-red-700">{err}</div>}
        {latest ? (
          <div>
            <div className="mb-2 flex flex-wrap items-center gap-2 text-navy-700">
              <Badge tone={latest.status === "completed" ? "green" : latest.status === "failed" ? "red" : latest.status === "cancelled" ? "slate" : "blue"}>{LABEL(latest.status)}</Badge>
              <span>{latest.progress}%</span><span className="text-xs text-navy-500">started {timeAgo(latest.created_at)} · attempt {latest.attempts}{latest.model ? ` · ${latest.model}` : ""}</span>
            </div>
            <div className="mb-3 h-1.5 overflow-hidden rounded-full bg-canvas"><div className="h-full bg-brand-600 transition-all" style={{ width: `${latest.progress}%` }} /></div>
            <ol className="grid gap-1.5 md:grid-cols-3">
              {latest.stages.map((st) => (
                <li key={st.key} className="flex items-center gap-2 text-xs">
                  <span className={cx("h-2 w-2 shrink-0 rounded-full", { completed: "bg-emerald-500", running: "bg-brand-500 animate-pulse", failed: "bg-red-500", skipped: "bg-slate-200", pending: "bg-slate-300" }[st.status] || "bg-slate-300")} />
                  <span className={st.status === "skipped" ? "text-navy-400" : "text-navy-800"}>{st.label}</span>
                  {st.error && <span className="truncate text-red-600" title={st.error}>· {st.error}</span>}
                </li>))}
            </ol>
            {latest.error && <p className="mt-2 text-xs text-red-600">{latest.error}</p>}
          </div>
        ) : !local && <p className="text-navy-500">No analysis has run for this client yet.</p>}
      </div>
    </Card>
  );
}

// ------------------------------------------------------------------ main section
export function ClientIntelligence({ clientId, clientName, archived, products }: { clientId: string; clientName: string; archived: boolean; products: Product[] }) {
  const [section, setSection] = useState<Section>("Overview");
  const [showRejected, setShowRejected] = useState(false);
  const [modal, setModal] = useState<{ type: FindingType; initial?: Finding | null; defaults?: Record<string, unknown> } | null>(null);
  const load = useAsync(async () => {
    const types: FindingType[] = ["profile", "application", "persona", "market", "insight"];
    const res = await Promise.all(types.map((t) => api.listFindings(clientId, t, { include_rejected: showRejected })));
    const summary = await api.intelligenceSummary(clientId);
    return { by: Object.fromEntries(types.map((t, i) => [t, res[i].items])) as Record<FindingType, Finding[]>, summary };
  }, [clientId, showRejected]);
  const history = useAsync(() => api.listAnalyses(clientId), [clientId, section]);

  const by = load.data?.by;
  const all = useMemo(() => (by ? Object.values(by).flat() : []), [by]);
  const edit = (f: Finding) => setModal({ type: f.type, initial: f });
  const add = (type: FindingType, defaults?: Record<string, unknown>) => !archived && setModal({ type, defaults });
  const card = (f: Finding, body: React.ReactNode) => <FindingCard key={f.id} f={f} products={products} onEdit={edit} onChanged={load.reload}>{body}</FindingCard>;
  const addBtn = (type: FindingType, label: string, defaults?: Record<string, unknown>) => !archived &&
    <Button size="sm" variant="secondary" onClick={() => add(type, defaults)}><Plus className="h-3.5 w-3.5" />{label}</Button>;

  const download = async () => {
    try {
      const md = await api.reportMarkdown(clientId);
      const url = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
      const a = document.createElement("a"); a.href = url; a.download = `${clientName.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}-intelligence-report.md`; a.click(); URL.revokeObjectURL(url);
    } catch (e) { alert(e instanceof Error ? e.message : "Download failed"); }
  };

  const counts = load.data?.summary.status_counts;
  return (
    <div className="space-y-6">
      <AnalysisPanel clientId={clientId} archived={archived} onDone={() => { load.reload(); history.reload(); }} />

      <Card>
        <CardHeader title="Client intelligence" subtitle="Every finding shows its source and status. AI hypotheses are kept apart from verified facts."
          action={<div className="flex items-center gap-3">
            <label className="flex items-center gap-1.5 text-xs text-navy-600"><input type="checkbox" checked={showRejected} onChange={(e) => setShowRejected(e.target.checked)} />Show rejected</label>
            <Button size="sm" variant="secondary" onClick={download}><Download className="h-3.5 w-3.5" />Report</Button></div>} />
        <div className="flex gap-1 overflow-x-auto border-b border-line px-3">
          {SECTIONS.map((t) => <button key={t} onClick={() => setSection(t)} className={cx("-mb-px whitespace-nowrap border-b-2 px-3 py-2.5 text-sm transition", section === t ? "border-brand-600 font-medium text-brand-700" : "border-transparent text-navy-500 hover:text-navy-900")}>{t}</button>)}
        </div>

        {load.loading && !load.data ? <Skeleton /> : load.error ? <ErrorBox message={load.error} onRetry={load.reload} /> : by && (
          <div className="p-5">
            {section === "Overview" && (
              <div className="space-y-5">
                <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                  {(["verified", "needs_review", "ai_hypothesis", "rejected"] as VerificationStatus[]).map((k) => (
                    <div key={k} className="rounded-lg border border-line p-3"><div className="text-xs text-navy-500">{STATUS_LABEL[k]}</div>
                      <div className="mt-1 text-2xl font-semibold text-navy-950">{k === "rejected" ? (showRejected ? all.filter((f) => f.verification_status === "rejected").length : "—") : counts?.[k] ?? "—"}</div></div>))}
                </div>
                <p className="text-xs text-navy-500">Sources: {load.data!.summary.sources.documents} document(s), {load.data!.summary.sources.documents_extracted} with extracted text, {load.data!.summary.sources.evidence_items} evidence item(s).</p>
                <div className="flex items-center justify-between"><h4 className="font-medium text-navy-950">Company profile</h4>{!by.profile.length && addBtn("profile", "Add profile")}</div>
                {by.profile.length ? by.profile.slice(-1).map((f) => card(f, <>
                  <p className="whitespace-pre-line">{s(f, "summary") || "—"}</p>
                  {s(f, "value_proposition") && <p className="mt-2"><span className="font-medium">Value proposition:</span> {s(f, "value_proposition")}</p>}
                  {Object.keys((f.data.facts as object) || {}).length > 0 && <dl className="mt-3 grid gap-x-6 gap-y-1 md:grid-cols-2">
                    {Object.entries(f.data.facts as Record<string, string>).map(([k, v]) => <div key={k} className="flex gap-2"><dt className="text-navy-500">{LABEL(k)}:</dt><dd className="font-medium">{v}</dd></div>)}</dl>}
                </>)) : <Empty title="No company profile yet" body="Run an analysis or add the profile by hand. Facts appear only when a source states them." icon={<Brain className="h-5 w-5" />} />}
              </div>)}

            {section === "Products & applications" && (
              products.length ? <div className="space-y-6">{products.map((p) => {
                const facts = by.insight.filter((i) => i.data.product_id === p.id && ["product_fact", "advantage", "differentiation", "industry_usage"].includes(String(i.data.category)));
                const apps = by.application.filter((a) => a.data.product_id === p.id);
                return (
                  <div key={p.id}>
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2"><h4 className="font-medium text-navy-950">{p.name}</h4>
                      <div className="flex gap-2">{addBtn("insight", "Product fact", { product_id: p.id, category: "product_fact" })}{addBtn("application", "Application", { product_id: p.id, application_type: "direct" })}</div></div>
                    <div className="grid gap-3 md:grid-cols-2">
                      {facts.map((f) => card(f, <><div className="text-xs text-navy-500">{CATEGORY_LABEL[s(f, "category")]}{s(f, "field") && ` · ${s(f, "field")}`}</div><p className="font-medium">{s(f, "title")}</p>{s(f, "detail") && <p className="mt-1">{s(f, "detail")}</p>}</>))}
                      {apps.map((f) => card(f, <>
                        <div className="text-xs text-navy-500">Application · {s(f, "application_type") ? LABEL(s(f, "application_type")) : "—"}{s(f, "industry") && ` · ${s(f, "industry")}`}</div>
                        <p className="font-medium">{s(f, "application")}</p>{s(f, "description") && <p className="mt-1">{s(f, "description")}</p>}
                        <List label="Businesses that need it" items={f.data.businesses_needing} /><List label="Buyer categories" items={f.data.buyer_categories} />
                        <List label="Pain points" items={f.data.pain_points} /><List label="Purchase reasons" items={f.data.purchase_reasons} /><List label="Substitutes" items={f.data.substitutes} />
                      </>))}
                      {!facts.length && !apps.length && <p className="text-sm text-navy-500">— No facts or applications yet.</p>}
                    </div>
                  </div>);
              })}</div> : <Empty title="No products yet" body="Add products under Products & services first. Applications are linked to a product." />)}

            {section === "Buyer personas" && (<>
              <div className="mb-3 flex justify-end">{addBtn("persona", "Add persona")}</div>
              {by.persona.length ? <div className="grid gap-3 md:grid-cols-2">{by.persona.map((f) => card(f, <>
                <p className="font-medium">{s(f, "name")}</p>
                <div className="text-xs text-navy-500">{[s(f, "buyer_category"), s(f, "industry"), s(f, "company_size")].filter(Boolean).join(" · ") || "—"}</div>
                {s(f, "description") && <p className="mt-1">{s(f, "description")}</p>}
                <List label="Job titles" items={f.data.job_titles} /><List label="Departments" items={f.data.departments} /><List label="Pain points" items={f.data.pain_points} /><List label="Purchase reasons" items={f.data.purchase_reasons} />
              </>))}</div> : <Empty title="No buyer personas yet" body="Personas are always AI hypotheses or team judgements, never verified facts." />}
            </>)}

            {section === "Target markets" && (<>
              <div className="mb-3 flex justify-end">{addBtn("market", "Add market", { scope: "country" })}</div>
              {by.market.length ? <div className="space-y-5">{ENUMS.scope.map((sc) => {
                const rows = by.market.filter((m) => m.data.scope === sc); if (!rows.length) return null;
                return <div key={sc}><h4 className="mb-2 text-xs font-medium uppercase tracking-wide text-navy-400">{SCOPE_LABEL[sc]}</h4>
                  <div className="grid gap-3 md:grid-cols-2">{rows.map((f) => card(f, <>
                    <div className="flex items-center gap-2"><p className="font-medium">{s(f, "name")}</p>{s(f, "parent") && <span className="text-xs text-navy-500">{s(f, "parent")}</span>}{s(f, "priority") && <Badge tone={s(f, "priority") === "high" ? "blue" : "slate"}>{LABEL(s(f, "priority"))} priority</Badge>}</div>
                    {s(f, "rationale") && <p className="mt-1">{s(f, "rationale")}</p>}</>))}</div></div>;
              })}</div> : <Empty title="No target markets yet" body="India, states, cities, countries and export markets appear here as hypotheses." />}
            </>)}

            {section === "Opportunities" && (<>
              <div className="mb-3 flex justify-end">{addBtn("insight", "Add opportunity", { category: "opportunity" })}</div>
              {(() => {
                const rows = by.insight.filter((i) => ["opportunity", "risk", "gap"].includes(String(i.data.category)));
                return rows.length ? <div className="grid gap-3 md:grid-cols-2">{rows.map((f) => card(f, <><div className="text-xs text-navy-500">{CATEGORY_LABEL[s(f, "category")]}</div><p className="font-medium">{s(f, "title")}</p>{s(f, "detail") && <p className="mt-1">{s(f, "detail")}</p>}</>))}</div>
                  : <Empty title="No opportunities yet" body="Opportunities, risks and information gaps appear here." />;
              })()}
            </>)}

            {section === "Evidence" && (
              all.some((f) => f.evidence.length) ? <ul className="divide-y divide-line">{all.filter((f) => f.evidence.length).map((f) => (
                <li key={f.id} className="py-3">
                  <div className="flex flex-wrap items-center gap-2 text-sm"><StatusBadge f={f} /><span className="font-medium text-navy-900">{s(f, "title") || s(f, "name") || s(f, "application") || (f.type === "profile" ? "Company profile" : "—")}</span><span className="text-xs text-navy-500">{LABEL(f.type)}</span></div>
                  <EvidenceList items={f.evidence} />
                </li>))}</ul> : <Empty title="No evidence yet" body="Each finding's sources (document excerpts, web pages, team notes) are listed here." icon={<FileText className="h-5 w-5" />} />)}

            {section === "History" && (
              history.loading ? <Skeleton /> : history.data?.length ? (
                <ul className="divide-y divide-line">{history.data.map((j) => (
                  <li key={j.id} className="flex flex-wrap items-center justify-between gap-2 py-3 text-sm">
                    <div className="flex items-center gap-2"><Badge tone={j.status === "completed" ? "green" : j.status === "failed" ? "red" : "slate"}>{LABEL(j.status)}</Badge>
                      <span>{j.stages.filter((x) => x.status === "completed").length}/{j.stages.filter((x) => x.status !== "skipped").length} stages</span>
                      {j.model && <span className="text-xs text-navy-500">{j.provider} · {j.model}</span>}</div>
                    <span className="text-xs text-navy-500">{fmtDateTime(j.created_at)} · attempt {j.attempts}</span>
                  </li>))}</ul>
              ) : <Empty title="No analysis history" body={api.mode === "local" ? "Analyses run on the backend only. Manual edits are recorded in the Activity tab." : "Runs of the AI analysis are listed here."} />)}
          </div>)}
      </Card>

      {modal && <FindingModal type={modal.type} clientId={clientId} products={products} initial={modal.initial} defaults={modal.defaults} onClose={() => setModal(null)} onSaved={load.reload} />}
    </div>
  );
}
