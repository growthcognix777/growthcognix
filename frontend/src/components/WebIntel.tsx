"use client";
import { Check, Download, ExternalLink, Globe, Pencil, Play, Plus, RotateCcw, Sparkles, Square, Trash2, Undo2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDateTime, timeAgo } from "@/lib/format";
import { ApiError, type Competitor, type CompetitorCategory, type CompetitorInput, type CrawlConfig, type CrawlJob, type CrawledPage, type Opportunity } from "@/lib/types";
import { useAsync } from "@/lib/useAsync";
import { Badge, Button, Card, CardHeader, Empty, ErrorBox, Field, Input, Modal, Select, Skeleton, Table, TagInput, Textarea, cx } from "./ui";

const SCREENS = ["Overview", "Crawl settings", "Pages", "Technical audit", "Performance", "Keywords & content", "Competitors",
  "Competitor profile", "Comparison", "Change history", "Opportunities", "Report"] as const;
type Screen = (typeof SCREENS)[number];
const RANK = { staff: 0, manager: 1, admin: 2, owner: 3 } as const;
const SEV_TONE = { high: "red", medium: "amber", low: "blue", info: "slate" } as const;
const LABEL = (k: string) => k.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
const short = (u?: string | null) => (u ? u.replace(/^https?:\/\//, "").replace(/\/$/, "") : "—");
const local = () => api.mode === "local";

function download(name: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a"); a.href = url; a.download = name; a.click(); URL.revokeObjectURL(url);
}
const fail = (e: unknown) => alert(e instanceof Error ? e.message : "Failed");

function LocalNote() {
  if (!local()) return null;
  return <div className="m-5 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">This browser preview has no server, so websites can&apos;t be crawled here and no audit or competitor data is simulated. Run the GrowthCognix backend to crawl. You can still add and organise competitors.</div>;
}

function JobBadge({ j }: { j: CrawlJob }) {
  return <Badge tone={j.status === "completed" ? "green" : j.status === "failed" ? "red" : j.status === "cancelled" ? "slate" : "blue"}>{LABEL(j.status)}</Badge>;
}

// ------------------------------------------------------------------ crawl settings form
function ConfigForm({ clientId, initial, interval, defaults, onSaved }: { clientId: string; initial: Partial<CrawlConfig>; interval: number | null; defaults: CrawlConfig; onSaved: () => void }) {
  const [v, setV] = useState<CrawlConfig>({ ...defaults, ...initial });
  const [days, setDays] = useState<string>(interval ? String(interval) : "");
  const [busy, setBusy] = useState(false); const [err, setErr] = useState<string | null>(null); const [ok, setOk] = useState(false);
  const num = (k: keyof CrawlConfig) => (e: React.ChangeEvent<HTMLInputElement>) => setV({ ...v, [k]: Number(e.target.value) });
  const save = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setErr(null); setOk(false);
    try { await api.saveClientWebsite(clientId, { crawl_config: v, crawl_interval_days: days ? Number(days) : null }); setOk(true); onSaved(); }
    catch (e) { setErr(e instanceof ApiError ? e.message : "Could not save"); } finally { setBusy(false); }
  };
  return (
    <form onSubmit={save} className="space-y-4 p-5">
      {err && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{err}</div>}
      {ok && <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700">Saved. The next crawl uses these settings.</div>}
      <div className="grid gap-4 md:grid-cols-3">
        <Field label="Max pages" hint="Hard ceiling set on the server"><Input type="number" min={1} value={v.max_pages} onChange={num("max_pages")} /></Field>
        <Field label="Max depth" hint="Clicks from the home page"><Input type="number" min={0} max={10} value={v.max_depth} onChange={num("max_depth")} /></Field>
        <Field label="Delay between requests (s)" hint="robots.txt Crawl-delay can raise it"><Input type="number" min={0} max={60} step={0.5} value={v.delay_seconds} onChange={num("delay_seconds")} /></Field>
        <Field label="Concurrency" hint="Requests per delay window (1–4)"><Input type="number" min={1} max={4} value={v.concurrency} onChange={num("concurrency")} /></Field>
        <Field label="Retries for failed pages" hint="Timeouts and 5xx only"><Input type="number" min={0} max={3} value={v.retries} onChange={num("retries")} /></Field>
        <Field label="Re-crawl every (days)" hint="Empty = manual only"><Input type="number" min={1} max={365} value={days} onChange={(e) => setDays(e.target.value)} /></Field>
        <div className="md:col-span-3"><Field label="Only crawl paths matching" hint="Glob patterns, e.g. /products/*. Press Enter after each."><TagInput value={v.include} onChange={(t) => setV({ ...v, include: t })} /></Field></div>
        <div className="md:col-span-3"><Field label="Skip paths matching" hint="e.g. /blog/*, /cart*"><TagInput value={v.exclude} onChange={(t) => setV({ ...v, exclude: t })} /></Field></div>
        <label className="flex items-center gap-2 text-sm text-navy-700 md:col-span-3"><input type="checkbox" checked={v.use_sitemap} onChange={(e) => setV({ ...v, use_sitemap: e.target.checked })} />Seed the crawl from the XML sitemap</label>
      </div>
      <p className="text-xs text-navy-500">The crawler only visits the client&apos;s own domain, obeys robots.txt, never signs in or bypasses access controls, and blocks private network addresses.</p>
      <div className="flex justify-end"><Button type="submit" loading={busy} disabled={local()}>Save settings</Button></div>
    </form>
  );
}

// ------------------------------------------------------------------ competitor modal
function CompetitorModal({ clientId, initial, onClose, onSaved }: { clientId: string; initial?: Competitor | null; onClose: () => void; onSaved: () => void }) {
  const [v, setV] = useState<CompetitorInput>(initial ? { name: initial.name, website: initial.website, category: initial.category, relevance: { ...initial.relevance },
    geography: [...initial.geography], notes: initial.notes, monitor_interval_days: initial.monitor_interval_days } : { name: "", website: "", category: "direct", relevance: {}, geography: [], notes: "", monitor_interval_days: null });
  const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const rel = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) => setV({ ...v, relevance: { ...v.relevance, [k]: e.target.value } });
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setErr(null);
    if (!Object.values(v.relevance).some((x) => x && x.trim())) { setErr("Say why it competes: a shared product, application, customer type or geography."); return; }
    setBusy(true);
    try {
      const body = { ...v, website: v.website || null, notes: v.notes || null, monitor_interval_days: v.monitor_interval_days || null };
      if (initial) await api.editCompetitor(initial.id, body); else await api.addCompetitor(clientId, body);
      onSaved(); onClose();
    } catch (e) { setErr(e instanceof ApiError ? e.message : "Could not save"); } finally { setBusy(false); }
  };
  return (
    <Modal open onClose={onClose} title={initial ? `Edit ${initial.name}` : "Add competitor"}>
      <form onSubmit={submit} noValidate className="space-y-4">
        {err && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{err}</div>}
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Name" required><Input value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} /></Field>
          <Field label="Website" hint="Domain is checked before saving"><Input value={v.website || ""} onChange={(e) => setV({ ...v, website: e.target.value })} placeholder="competitor.com" /></Field>
          <Field label="Category"><Select value={v.category} onChange={(e) => setV({ ...v, category: e.target.value as CompetitorCategory })}>
            {["direct", "indirect", "substitute", "aspirational"].map((c) => <option key={c} value={c}>{LABEL(c)}</option>)}</Select></Field>
          <Field label="Monitor every (days)" hint="Empty = manual only"><Input type="number" min={1} max={365} value={v.monitor_interval_days ?? ""} onChange={(e) => setV({ ...v, monitor_interval_days: e.target.value ? Number(e.target.value) : null })} /></Field>
        </div>
        <div className="rounded-lg border border-line p-3">
          <div className="mb-2 text-xs font-medium uppercase tracking-wide text-navy-400">Why it competes (at least one)</div>
          <div className="grid gap-3 md:grid-cols-2">
            {[["product", "Overlapping product"], ["application", "Same application"], ["customer", "Same customer type"], ["geography", "Same geography"]].map(([k, l]) =>
              <Field key={k} label={l}><Input value={v.relevance[k] || ""} onChange={rel(k)} /></Field>)}
          </div>
        </div>
        <Field label="Markets they sell in"><TagInput value={v.geography} onChange={(t) => setV({ ...v, geography: t })} /></Field>
        <Field label="Notes"><Textarea className="min-h-[64px]" value={v.notes || ""} onChange={(e) => setV({ ...v, notes: e.target.value })} /></Field>
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" loading={busy}>{initial ? "Save" : "Add"}</Button></div>
      </form>
    </Modal>
  );
}

function PageModal({ id, onClose }: { id: string; onClose: () => void }) {
  const p = useAsync(() => api.getCrawledPage(id), [id]);
  return (
    <Modal open onClose={onClose} title="Crawled page">
      {p.loading ? <Skeleton /> : p.error ? <ErrorBox message={p.error} /> : p.data && <PageDetail p={p.data} />}
    </Modal>
  );
}
function PageDetail({ p }: { p: CrawledPage }) {
  const rows: [string, React.ReactNode][] = [["URL", <a key="u" href={p.url} target="_blank" rel="noopener noreferrer" className="break-all text-brand-600 hover:underline">{p.url}</a>],
    ["Final URL", p.final_url && p.final_url !== p.url ? <span className="break-all">{p.final_url}</span> : "—"], ["Status", p.status_code ?? "—"],
    ["Redirects", p.redirect_chain.length ? p.redirect_chain.map((h) => short(h.url)).join(" → ") : "—"], ["Response time (crawler)", p.response_ms != null ? `${p.response_ms} ms` : "—"],
    ["Title", p.title || "—"], ["Meta description", p.meta_description || "—"], ["H1", p.h1.join(" | ") || "—"], ["H2", p.h2.slice(0, 8).join(" | ") || "—"],
    ["Canonical", p.canonical || "—"], ["Robots meta", p.robots_meta || "—"], ["Lang", p.lang || "—"], ["Viewport", p.has_viewport == null ? "—" : p.has_viewport ? "yes" : "no"],
    ["Schema", p.structured_data.join(", ") || "—"], ["Words", p.word_count ?? "—"], ["Images missing alt", p.images_total ? `${p.images_missing_alt} of ${p.images_total}` : "—"],
    ["Internal links", p.internal_links_count], ["Fetched", fmtDateTime(p.fetched_at)], ["Error", p.error || "—"]];
  return (
    <div className="space-y-3 text-sm">
      <dl className="divide-y divide-line">{rows.map(([k, v]) => <div key={k} className="grid grid-cols-3 gap-3 py-1.5"><dt className="text-navy-500">{k}</dt><dd className="col-span-2 text-navy-900">{v}</dd></div>)}</dl>
      {p.text_preview && <div><div className="mb-1 text-xs font-medium uppercase tracking-wide text-navy-400">Text preview</div><p className="max-h-40 overflow-y-auto rounded-lg bg-canvas p-3 text-xs text-navy-700">{p.text_preview}</p></div>}
    </div>
  );
}

// ------------------------------------------------------------------ main
export function WebIntel({ clientId, clientName, clientWebsite, archived }: { clientId: string; clientName: string; clientWebsite: string | null; archived: boolean }) {
  const { session } = useAuth(); const role = session?.user.role || "staff";
  const [screen, setScreen] = useState<Screen>("Overview");
  const [busy, setBusy] = useState(false);
  const [pageFilter, setPageFilter] = useState(""); const [pageId, setPageId] = useState<string | null>(null);
  const [sev, setSev] = useState(""); const [cat, setCat] = useState("");
  const [compModal, setCompModal] = useState<{ open: boolean; c?: Competitor | null }>({ open: false });
  const [selComp, setSelComp] = useState<string>("");
  const [showRejected, setShowRejected] = useState(false);

  const status = useAsync(() => api.crawlerStatus());
  const site = useAsync(() => api.getClientWebsite(clientId), [clientId]);
  const crawls = useAsync(() => api.listCrawls(clientId), [clientId]);
  const comps = useAsync(() => api.listCompetitors(clientId), [clientId]);
  const audit = site.data?.latest_audit || null;
  const job = site.data?.latest_crawl || null;
  const running = (crawls.data?.items || []).some((j) => ["queued", "running"].includes(j.status));

  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => { crawls.reload(); site.reload(); comps.reload(); }, 3000);
    return () => clearInterval(t);
  }, [running]); // eslint-disable-line react-hooks/exhaustive-deps

  const auditJobId = audit?.crawl_job_id;
  const pages = useAsync(() => (auditJobId ? api.listCrawlPages(auditJobId, { status: pageFilter || undefined, limit: 500 }) : Promise.resolve({ items: [], total: 0 })), [auditJobId, pageFilter]);
  const findings = useAsync(() => (audit ? api.auditFindings(audit.id, { severity: sev || undefined, category: cat || undefined }) : Promise.resolve({ items: [], total: 0 })), [audit?.id, sev, cat]);
  const topics = useAsync(() => (audit ? api.auditTopics(audit.id) : Promise.resolve({ items: [], basis: "" })), [audit?.id]);
  const comparison = useAsync(() => api.comparison(clientId), [clientId, screen === "Comparison"]);
  const changes = useAsync(() => api.clientCompetitorChanges(clientId), [clientId, screen === "Change history"]);
  const opps = useAsync(() => api.listOpportunities(clientId, { include_rejected: showRejected }), [clientId, showRejected]);
  const profileId = selComp || comps.data?.items.find((c) => c.status === "active")?.id || "";
  const profile = useAsync(() => (profileId ? api.competitorProfile(profileId) : Promise.resolve(null)), [profileId, screen === "Competitor profile", running]);
  const profileChanges = useAsync(() => (profileId ? api.competitorChanges(profileId) : Promise.resolve({ items: [] })), [profileId, running]);

  const go = async (fn: () => Promise<unknown>, after?: () => void) => { setBusy(true); try { await fn(); after?.(); crawls.reload(); site.reload(); } catch (e) { fail(e); } finally { setBusy(false); } };
  const compBusy = (c: Competitor) => (crawls.data?.items || []).some((j) => j.competitor_id === c.id && ["queued", "running"].includes(j.status));
  const categories = useMemo(() => Object.keys(audit?.summary.by_category || {}), [audit]);

  const reviewOpp = async (o: Opportunity, action: "approve" | "reject" | "needs_review") => {
    const note = action === "reject" ? prompt("Reason (optional)") : null;
    if (action === "reject" && note === null) return;
    try { await api.reviewOpportunity(o.id, action, note); opps.reload(); } catch (e) { fail(e); }
  };

  return (
    <Card>
      <CardHeader title="Website & competitor intelligence" subtitle="Crawler observations and PageSpeed measurements, each with its source page. No ranking, traffic or revenue claims." />
      <div className="flex gap-1 overflow-x-auto border-b border-line px-3">
        {SCREENS.map((t) => <button key={t} onClick={() => setScreen(t)} className={cx("-mb-px whitespace-nowrap border-b-2 px-3 py-2.5 text-sm transition", screen === t ? "border-brand-600 font-medium text-brand-700" : "border-transparent text-navy-500 hover:text-navy-900")}>{t}</button>)}
      </div>
      <LocalNote />

      {screen === "Overview" && (
        <div className="space-y-5 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-sm"><Globe className="h-4 w-4 text-navy-400" />
              {clientWebsite ? <a href={clientWebsite} target="_blank" rel="noopener noreferrer" className="text-brand-600 hover:underline">{short(clientWebsite)}</a> : <span className="text-navy-500">No website on this client. Add one under Edit.</span>}
              {status.data && !local() && <Badge>{status.data.provider} crawler</Badge>}</div>
            {!archived && <div className="flex gap-2">
              {job && ["queued", "running"].includes(job.status) && <Button variant="secondary" loading={busy} onClick={() => go(() => api.cancelCrawl(job.id))}><Square className="h-4 w-4" />Cancel</Button>}
              {job && ["failed", "cancelled"].includes(job.status) && <Button variant="secondary" loading={busy} disabled={local()} onClick={() => go(() => api.retryCrawl(job.id))}><RotateCcw className="h-4 w-4" />Resume / retry</Button>}
              {!(job && ["queued", "running"].includes(job.status)) && <Button loading={busy} disabled={local() || !clientWebsite} onClick={() => go(() => api.startAudit(clientId))}><Play className="h-4 w-4" />Run website audit</Button>}
            </div>}
          </div>
          {job && (
            <div className="rounded-lg border border-line p-4 text-sm">
              <div className="mb-2 flex flex-wrap items-center gap-2"><JobBadge j={job} /><span>{job.progress}%</span>{job.stage && <span className="text-xs text-navy-500">stage: {job.stage}</span>}
                <span className="text-xs text-navy-500">started {timeAgo(job.created_at)} · attempt {job.attempts} · {job.provider}</span></div>
              <div className="mb-3 h-1.5 overflow-hidden rounded-full bg-canvas"><div className="h-full bg-brand-600 transition-all" style={{ width: `${job.progress}%` }} /></div>
              <div className="grid grid-cols-2 gap-2 text-xs md:grid-cols-4">
                {[["Discovered", job.pages_discovered], ["Crawled", job.pages_crawled], ["Failed", job.pages_failed], ["Blocked by robots.txt", job.pages_blocked]].map(([k, v]) =>
                  <div key={k as string}><div className="text-navy-400">{k}</div><div className="text-base font-semibold text-navy-950">{v}</div></div>)}
              </div>
              {job.error && <p className="mt-2 text-xs text-red-600">{job.error}</p>}
            </div>)}
          {audit ? (
            <div className="grid gap-3 md:grid-cols-4">
              <div className="rounded-lg border border-line p-4"><div className="text-xs text-navy-500">Technical health</div><div className="mt-1 text-3xl font-semibold text-navy-950">{audit.health_score ?? "—"}<span className="text-base text-navy-400">/100</span></div><div className="mt-1 text-[11px] text-navy-400">Crawler-observed, not a ranking</div></div>
              {(["high", "medium", "low"] as const).map((s) => <div key={s} className="rounded-lg border border-line p-4"><div className="text-xs text-navy-500">{LABEL(s)} issues</div><div className="mt-1 text-3xl font-semibold text-navy-950">{audit.summary.by_severity?.[s] ?? 0}</div></div>)}
              <div className="flex flex-wrap gap-2 md:col-span-4">
                {[["HTTPS", audit.summary.https], ["robots.txt", audit.summary.robots_found], ["Sitemap", audit.summary.sitemap_found]].map(([k, v]) => <Badge key={k as string} tone={v ? "green" : "amber"}>{k as string}: {v ? "yes" : "no"}</Badge>)}
                <Badge>{String(audit.summary.broken_links ?? 0)} broken links</Badge><Badge>{String(audit.summary.redirect_chains ?? 0)} redirect chains</Badge>
                <Badge>{String(audit.summary.duplicate_titles ?? 0)} duplicate titles</Badge><Badge>{String(audit.summary.missing_meta ?? 0)} missing meta descriptions</Badge>
              </div>
            </div>
          ) : !local() && <p className="text-sm text-navy-500">No audit yet. Run one to see the site&apos;s technical health.</p>}
          {!!crawls.data?.items.length && <div>
            <h4 className="mb-2 text-xs font-medium uppercase tracking-wide text-navy-400">Crawl history</h4>
            <Table head={["When", "Type", "Status", "Pages", "Trigger"]}>{crawls.data.items.map((j) => (
              <tr key={j.id}><td className="px-5 py-2.5 text-navy-700">{fmtDateTime(j.created_at)}</td><td className="px-5 py-2.5">{j.kind === "audit" ? "Client site" : comps.data?.items.find((c) => c.id === j.competitor_id)?.name || "Competitor"}</td>
                <td className="px-5 py-2.5"><JobBadge j={j} /></td><td className="px-5 py-2.5">{j.pages_crawled}</td><td className="px-5 py-2.5 text-navy-500">{j.trigger}</td></tr>))}</Table></div>}
        </div>)}

      {screen === "Crawl settings" && (status.data ? <ConfigForm key={site.data?.website?.id || "new"} clientId={clientId} defaults={status.data.defaults} initial={site.data?.website?.crawl_config || {}} interval={site.data?.website?.crawl_interval_days ?? null} onSaved={site.reload} /> : <Skeleton />)}

      {screen === "Pages" && (
        <div>
          <div className="flex gap-2 p-5 pb-0"><Select value={pageFilter} onChange={(e) => setPageFilter(e.target.value)} className="max-w-[200px]">
            <option value="">All pages</option><option value="ok">Loaded</option><option value="failed">Failed / 4xx / 5xx</option><option value="redirected">Redirected</option><option value="blocked">Blocked by robots.txt</option></Select></div>
          {pages.loading ? <Skeleton /> : !pages.data?.items.length ? <Empty title="No crawled pages" body="Run a website audit to crawl the client's site." /> : (
            <div className="mt-3"><Table head={["Page", "Status", "Type", "Title", "Words", "Depth"]}>{pages.data.items.map((p) => (
              <tr key={p.id} onClick={() => setPageId(p.id)} className="cursor-pointer hover:bg-canvas/60">
                <td className="max-w-[260px] truncate px-5 py-2.5 text-brand-700">{short(p.url)}</td>
                <td className="px-5 py-2.5">{p.blocked_by_robots ? <Badge>robots</Badge> : <Badge tone={!p.status_code || p.status_code >= 400 ? "red" : p.redirect_chain.length ? "amber" : "green"}>{p.status_code ?? "error"}</Badge>}</td>
                <td className="px-5 py-2.5 text-navy-600">{p.page_type || "—"}</td><td className="max-w-[260px] truncate px-5 py-2.5">{p.title || "—"}</td>
                <td className="px-5 py-2.5">{p.word_count ?? "—"}</td><td className="px-5 py-2.5">{p.depth}</td></tr>))}</Table>
              <p className="px-5 py-3 text-xs text-navy-500">{pages.data.total} page(s)</p></div>)}
          {pageId && <PageModal id={pageId} onClose={() => setPageId(null)} />}
        </div>)}

      {screen === "Technical audit" && (
        <div>
          <div className="flex flex-wrap items-center gap-2 p-5 pb-0">
            <Select value={sev} onChange={(e) => setSev(e.target.value)} className="max-w-[160px]"><option value="">All severities</option>{["high", "medium", "low", "info"].map((s) => <option key={s} value={s}>{LABEL(s)}</option>)}</Select>
            <Select value={cat} onChange={(e) => setCat(e.target.value)} className="max-w-[200px]"><option value="">All categories</option>{categories.map((c) => <option key={c} value={c}>{LABEL(c)}</option>)}</Select>
            {audit && <Button size="sm" variant="secondary" onClick={async () => { try { download("seo-findings.csv", await api.auditCsv(audit.id), "text/csv"); } catch (e) { fail(e); } }}><Download className="h-3.5 w-3.5" />CSV</Button>}
          </div>
          {findings.loading ? <Skeleton /> : !findings.data?.items.length ? <Empty title={audit ? "No findings match" : "No audit yet"} body="Findings are crawler observations with the page they were seen on." /> : (
            <div className="mt-3"><Table head={["Severity", "Category", "Issue", "Page", "Observed"]}>{findings.data.items.map((f) => (
              <tr key={f.id}><td className="px-5 py-2.5"><Badge tone={SEV_TONE[f.severity]}>{f.severity}</Badge></td><td className="px-5 py-2.5 text-navy-600">{LABEL(f.category)}</td>
                <td className="px-5 py-2.5">{f.message}{f.measured && <span className="ml-1"><Badge tone="violet">measured</Badge></span>}</td>
                <td className="max-w-[220px] truncate px-5 py-2.5">{f.page_url ? <a href={f.page_url} target="_blank" rel="noopener noreferrer" className="text-brand-600 hover:underline">{short(f.page_url)}</a> : "Site-wide"}</td>
                <td className="max-w-[200px] truncate px-5 py-2.5 text-xs text-navy-500" title={f.observed_value || ""}>{f.observed_value || "—"}</td></tr>))}</Table></div>)}
        </div>)}

      {screen === "Performance" && (
        <div className="space-y-4 p-5 text-sm">
          {!audit ? <Empty title="No audit yet" body="Performance is measured during a website audit." /> : audit.pagespeed?.results?.length ? (
            <div className="grid gap-4 md:grid-cols-2">{audit.pagespeed.results.map((r) => (
              <div key={r.strategy} className="rounded-lg border border-line p-4">
                <div className="mb-2 flex items-center justify-between"><h4 className="font-medium text-navy-950">{LABEL(r.strategy)}</h4><Badge tone="violet">Measured · PageSpeed Insights</Badge></div>
                {r.error ? <p className="text-red-600">{r.error}</p> : <>
                  <div className="grid grid-cols-4 gap-2">{["performance", "accessibility", "best-practices", "seo"].map((k) => <div key={k}><div className="text-xs text-navy-500">{LABEL(k)}</div><div className="text-xl font-semibold">{r.scores?.[k] ?? "—"}</div></div>)}</div>
                  <dl className="mt-3 grid grid-cols-3 gap-2 text-xs">{[["LCP", r.lab?.lcp_ms, "ms"], ["CLS", r.lab?.cls, ""], ["TBT", r.lab?.tbt_ms, "ms"], ["FCP", r.lab?.fcp_ms, "ms"], ["Speed index", r.lab?.speed_index_ms, "ms"], ["TTI", r.lab?.tti_ms, "ms"]].map(([k, v, u]) =>
                    <div key={k as string}><dt className="text-navy-400">{k as string} (lab)</dt><dd className="font-medium">{v != null ? `${v}${u ? " " + u : ""}` : "—"}</dd></div>)}</dl>
                  <p className="mt-2 text-xs text-navy-500">{r.field ? "Includes real-user (CrUX) field data." : "No real-user field data available from Google for this URL."} {fmtDateTime(r.fetched_at)}</p>
                </>}
              </div>))}</div>
          ) : <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-amber-800">— Not measured. {audit.pagespeed?.skipped || ""} Add a free PAGESPEED_API_KEY on the backend to measure Core Web Vitals.</div>}
          {audit && <p className="text-xs text-navy-500">Server response times seen by the crawler are listed under Technical audit as observations, not Core Web Vitals.</p>}
        </div>)}

      {screen === "Keywords & content" && (
        <div className="grid gap-6 p-5 lg:grid-cols-2">
          <div>
            <h4 className="mb-1 font-medium text-navy-950">Topics the site covers</h4>
            <p className="mb-3 text-xs text-navy-500">Counted from page titles and headings. Not search volume or rankings (connect Search Console in a later phase for that).</p>
            {topics.data?.items.length ? <Table head={["Topic", "Pages", "In titles"]}>{topics.data.items.slice(0, 30).map((t) => <tr key={t.topic}><td className="px-5 py-2">{t.topic}</td><td className="px-5 py-2">{t.pages}</td><td className="px-5 py-2">{t.in_titles}</td></tr>)}</Table> : <p className="text-sm text-navy-500">—</p>}
          </div>
          <div className="space-y-5">
            <div><h4 className="mb-2 font-medium text-navy-950">Recommendations</h4>
              {audit?.recommendations.length ? <ul className="space-y-2">{audit.recommendations.map((r, i) => <li key={i} className="rounded-lg border border-line p-3 text-sm"><div className="flex items-center gap-2"><Badge tone={r.priority === "high" ? "red" : r.priority === "medium" ? "amber" : "slate"}>{r.priority}</Badge><span className="font-medium">{r.title}</span></div><p className="mt-1 text-navy-700">{r.detail}</p>{!!r.urls.length && <p className="mt-1 truncate text-xs text-navy-500">{r.urls.slice(0, 3).map(short).join(", ")}</p>}</li>)}</ul> : <p className="text-sm text-navy-500">—</p>}</div>
            <div><h4 className="mb-2 font-medium text-navy-950">Content calendar (suggestions)</h4>
              {audit?.summary.content_calendar?.length ? <ol className="space-y-1 text-sm">{audit.summary.content_calendar.map((c) => <li key={c.week} className="flex gap-3"><span className="w-16 text-navy-400">Week {c.week}</span><span>{c.topic}</span></li>)}</ol> : <p className="text-sm text-navy-500">—</p>}</div>
          </div>
        </div>)}

      {screen === "Competitors" && (
        <div className="p-5">
          <div className="mb-3 flex flex-wrap justify-end gap-2">
            {!archived && <Button size="sm" variant="secondary" loading={busy} disabled={local()} onClick={() => go(async () => { const r = await api.suggestCompetitors(clientId); alert(`${r.created} suggestion(s) added for review.`); }, comps.reload)}><Sparkles className="h-3.5 w-3.5" />Suggest with AI</Button>}
            {!archived && <Button size="sm" onClick={() => setCompModal({ open: true })}><Plus className="h-3.5 w-3.5" />Add competitor</Button>}
          </div>
          {comps.loading ? <Skeleton /> : !comps.data?.items.length ? <Empty title="No competitors yet" body="Add 10–30 competitors relevant by product, application, customer or geography." /> : (
            <div className="grid gap-3 md:grid-cols-2">{comps.data.items.map((c) => (
              <div key={c.id} className={cx("rounded-xl border p-4", c.status === "suggested" ? "border-violet-200 bg-violet-50/30" : "border-line")}>
                <div className="flex items-start justify-between gap-2">
                  <div><div className="flex flex-wrap items-center gap-1.5"><h4 className="font-medium text-navy-950">{c.name}</h4><Badge tone="blue">{c.category}</Badge>
                    {c.status === "suggested" && <Badge tone="violet">AI suggestion</Badge>}{c.domain_valid === false && <Badge tone="red">domain invalid</Badge>}{c.domain_valid == null && c.website && <Badge>domain not checked</Badge>}</div>
                    {c.website && <a href={c.website} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-brand-600 hover:underline">{short(c.website)}<ExternalLink className="h-3 w-3" /></a>}</div>
                  <div className="flex gap-1">
                    <button onClick={() => setCompModal({ open: true, c })} className="rounded p-1.5 text-navy-500 hover:bg-canvas" aria-label="Edit"><Pencil className="h-4 w-4" /></button>
                    {RANK[role] >= RANK.manager && <button onClick={() => confirm(`Delete ${c.name} and its snapshots?`) && api.deleteCompetitor(c.id).then(comps.reload, fail)} className="rounded p-1.5 text-navy-500 hover:bg-red-50 hover:text-red-600" aria-label="Delete"><Trash2 className="h-4 w-4" /></button>}
                  </div>
                </div>
                <div className="mt-2 flex flex-wrap gap-1">{Object.entries(c.relevance).map(([k, v]) => <Badge key={k}>{LABEL(k)}: {v}</Badge>)}</div>
                {c.notes && <p className="mt-2 text-xs text-navy-600">{c.notes}</p>}
                <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3 text-xs text-navy-500">
                  <span>{c.last_analysed_at ? `Analysed ${timeAgo(c.last_analysed_at)}` : "Not analysed"}{c.monitor_interval_days ? ` · every ${c.monitor_interval_days}d` : ""}</span>
                  <div className="flex gap-1.5">
                    {c.status === "suggested" && RANK[role] >= RANK.manager && <>
                      <Button size="sm" variant="secondary" onClick={() => api.reviewCompetitor(c.id, "accept").then(comps.reload, fail)}><Check className="h-3.5 w-3.5" />Accept</Button>
                      <Button size="sm" variant="danger" onClick={() => api.reviewCompetitor(c.id, "reject").then(comps.reload, fail)}><X className="h-3.5 w-3.5" />Reject</Button></>}
                    {c.status === "active" && <Button size="sm" variant="secondary" loading={compBusy(c)} disabled={local() || !c.website || archived} onClick={() => go(() => api.analyseCompetitor(c.id), comps.reload)}><Play className="h-3.5 w-3.5" />Analyse</Button>}
                    {c.status === "active" && <Button size="sm" variant="ghost" onClick={() => { setSelComp(c.id); setScreen("Competitor profile"); }}>Profile</Button>}
                  </div>
                </div>
              </div>))}</div>)}
          {compModal.open && <CompetitorModal clientId={clientId} initial={compModal.c} onClose={() => setCompModal({ open: false })} onSaved={comps.reload} />}
        </div>)}

      {screen === "Competitor profile" && (
        <div className="space-y-4 p-5 text-sm">
          <Select value={profileId} onChange={(e) => setSelComp(e.target.value)} className="max-w-xs"><option value="">Select a competitor…</option>{comps.data?.items.filter((c) => c.status === "active").map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>
          {!profileId ? <Empty title="No competitor selected" /> : profile.loading && !profile.data ? <Skeleton /> : profile.data && (() => {
            const { competitor: c, latest_snapshot: s } = profile.data;
            return <div className="space-y-4">
              <div><h4 className="text-lg font-semibold text-navy-950">{c.name}</h4><p className="text-xs text-navy-500">{short(c.website)} · {profile.data.snapshots} snapshot(s){s ? ` · last captured ${fmtDateTime(s.captured_at)}` : ""}</p></div>
              {c.positioning && <div className="rounded-lg border border-violet-200 bg-violet-50/40 p-3"><Badge tone="violet">AI interpretation</Badge><p className="mt-1">{c.positioning}</p></div>}
              {!s ? <Empty title="Not analysed yet" body="Analyse the competitor to capture a snapshot of its public pages." /> : <div className="grid gap-4 md:grid-cols-2">
                <div className="rounded-lg border border-line p-3"><div className="mb-1 text-xs font-medium uppercase tracking-wide text-navy-400">Home page messaging</div><p className="font-medium">{s.homepage.h1 || "—"}</p><p className="text-xs text-navy-500">{s.homepage.title || "—"}</p><p className="mt-1 text-xs">{s.homepage.description || ""}</p></div>
                <div className="rounded-lg border border-line p-3"><div className="mb-1 text-xs font-medium uppercase tracking-wide text-navy-400">Site (crawler observation)</div><p>{String(s.seo.pages ?? "—")} pages · {String(s.seo.product_pages ?? 0)} product pages · avg {String(s.seo.avg_words ?? "—")} words</p><p className="text-xs text-navy-500">Schema: {(s.seo.schema_types as string[] | undefined)?.join(", ") || "—"}</p></div>
                {[["Products / product pages", s.products.map((p) => ({ t: p.name, u: p.url }))], ["Public prices (as published)", s.prices.map((p) => ({ t: p.text, u: p.url }))],
                  ["Certifications mentioned", s.certifications.map((p) => ({ t: p.name, u: p.url }))], ["Locations mentioned", s.locations.map((p) => ({ t: p.name, u: p.url }))],
                  ["Promotions", (s.seo.promotions || []).map((p) => ({ t: p.text, u: p.url }))]].map(([title, items]) => (
                  <div key={title as string} className="rounded-lg border border-line p-3"><div className="mb-1 text-xs font-medium uppercase tracking-wide text-navy-400">{title as string}</div>
                    {(items as { t: string; u: string }[]).length ? <ul className="space-y-1">{(items as { t: string; u: string }[]).slice(0, 12).map((x, i) => <li key={i} className="flex justify-between gap-2"><span className="truncate">{x.t}</span><a href={x.u} target="_blank" rel="noopener noreferrer" className="shrink-0 text-xs text-brand-600 hover:underline">source</a></li>)}</ul> : <p className="text-navy-500">—</p>}</div>))}
                <div className="rounded-lg border border-line p-3"><div className="mb-1 text-xs font-medium uppercase tracking-wide text-navy-400">Business contact</div><p>{[...(s.contact.emails || []), ...(s.contact.phones || [])].join(", ") || "—"}</p><p className="text-xs text-navy-500">Only role addresses at the company domain are kept.</p></div>
                <div className="rounded-lg border border-line p-3 md:col-span-2"><div className="mb-1 text-xs font-medium uppercase tracking-wide text-navy-400">Topics</div><div className="flex flex-wrap gap-1">{s.topics.length ? s.topics.map((t) => <Badge key={t}>{t}</Badge>) : "—"}</div></div>
              </div>}
              <div><h4 className="mb-2 font-medium text-navy-950">Recent changes</h4>
                {profileChanges.data?.items.length ? <ChangeTable items={profileChanges.data.items} /> : <p className="text-navy-500">— Changes appear after the second snapshot.</p>}</div>
            </div>;
          })()}
        </div>)}

      {screen === "Comparison" && (
        comparison.loading ? <Skeleton /> : !comparison.data?.items.length ? <Empty title="Nothing to compare yet" body="Run a website audit and analyse at least one competitor." /> : (
          <div><Table head={["Company", "Pages", "Product pages", "Prices shown", "Certifications", "Schema", "Avg words", "HTTPS", "Health", "Shared topics"]}>{comparison.data.items.map((r) => (
            <tr key={r.id || "client"} className={r.is_client ? "bg-brand-50/40" : ""}>
              <td className="px-5 py-2.5 font-medium">{r.name}{r.is_client && <span className="ml-1"><Badge tone="blue">client</Badge></span>}</td><td className="px-5 py-2.5">{r.pages ?? "—"}</td><td className="px-5 py-2.5">{r.product_pages ?? "—"}</td>
              <td className="px-5 py-2.5">{r.prices_published}</td><td className="max-w-[160px] truncate px-5 py-2.5">{r.certifications.join(", ") || "—"}</td><td className="max-w-[160px] truncate px-5 py-2.5">{r.schema_types.join(", ") || "—"}</td>
              <td className="px-5 py-2.5">{r.avg_words ?? "—"}</td><td className="px-5 py-2.5">{r.https == null ? "—" : r.https ? "yes" : "no"}</td><td className="px-5 py-2.5">{r.health_score ?? "—"}</td>
              <td className="max-w-[200px] truncate px-5 py-2.5">{r.is_client ? "—" : r.shared_topics.join(", ") || "none"}</td></tr>))}</Table>
            <p className="px-5 py-3 text-xs text-navy-500">{comparison.data.basis}</p></div>))}

      {screen === "Change history" && (
        changes.loading ? <Skeleton /> : !changes.data?.items.length ? <Empty title="No changes recorded" body="Changes are detected when a competitor is analysed again (manually or on its monitoring schedule)." /> : <ChangeTable items={changes.data.items} withName />)}

      {screen === "Opportunities" && (
        <div className="p-5">
          <div className="mb-3 flex flex-wrap items-center justify-end gap-3">
            <label className="flex items-center gap-1.5 text-xs text-navy-600"><input type="checkbox" checked={showRejected} onChange={(e) => setShowRejected(e.target.checked)} />Show rejected</label>
            {!archived && <Button size="sm" loading={busy} onClick={() => go(async () => { const r = await api.analyseOpportunities(clientId); if (r.note) alert(r.note); }, opps.reload)}><Sparkles className="h-3.5 w-3.5" />Find opportunities</Button>}
          </div>
          {opps.loading ? <Skeleton /> : !opps.data?.items.length ? <Empty title="No opportunities yet" body="Built by comparing the client's audited site with competitor snapshots and the client intelligence." /> : (
            <div className="grid gap-3 md:grid-cols-2">{opps.data.items.map((o) => (
              <div key={o.id} className={cx("rounded-xl border p-4 text-sm", o.verification_status === "rejected" ? "border-red-100 bg-red-50/30" : "border-line")}>
                <div className="flex flex-wrap items-center gap-1.5"><Badge tone={o.priority === "high" ? "red" : o.priority === "medium" ? "amber" : "slate"}>{o.priority}</Badge><Badge>{LABEL(o.kind)}</Badge>
                  <Badge tone={o.approved ? "green" : o.verification_status === "rejected" ? "red" : "amber"}>{o.approved ? "Approved to act on" : o.verification_status === "rejected" ? "Rejected" : "Needs review"}</Badge>
                  <Badge tone="violet">{o.origin === "ai" ? "AI" : "Rule-based"} recommendation</Badge>{o.confidence != null && <span className="text-xs text-navy-500">confidence {Math.round(o.confidence * 100)}%</span>}</div>
                <p className="mt-2 font-medium text-navy-950">{o.title}</p>
                {o.description && <p className="mt-1 text-navy-700">{o.description}</p>}
                {o.rationale && <p className="mt-1 text-xs text-navy-500">Why: {o.rationale}</p>}
                {o.next_action && <p className="mt-1 text-xs"><span className="font-medium">Next action:</span> {o.next_action}</p>}
                <details className="mt-2 text-xs"><summary className="cursor-pointer text-brand-600">{o.evidence.length} source(s)</summary>
                  <ul className="mt-1 space-y-1">{o.evidence.map((e) => <li key={e.id} className="rounded bg-canvas p-2">{e.excerpt || "—"} {e.source_url && <a href={e.source_url} target="_blank" rel="noopener noreferrer" className="text-brand-600 hover:underline">{short(e.source_url)}</a>}</li>)}</ul></details>
                {RANK[role] >= RANK.manager && <div className="mt-3 flex justify-end gap-1.5 border-t border-line pt-3">
                  {!o.approved && o.verification_status !== "rejected" && <Button size="sm" variant="secondary" onClick={() => reviewOpp(o, "approve")}><Check className="h-3.5 w-3.5" />Approve</Button>}
                  {o.verification_status !== "rejected" && <Button size="sm" variant="danger" onClick={() => reviewOpp(o, "reject")}><X className="h-3.5 w-3.5" />Reject</Button>}
                  {(o.approved || o.verification_status === "rejected") && <Button size="sm" variant="ghost" onClick={() => reviewOpp(o, "needs_review")}><Undo2 className="h-3.5 w-3.5" />Send back</Button>}
                </div>}
              </div>))}</div>)}
        </div>)}

      {screen === "Report" && (
        <div className="space-y-3 p-5 text-sm">
          {!audit ? <Empty title="No audit to export" body="Run a website audit first." /> : <>
            <p className="text-navy-700">Export the latest audit ({fmtDateTime(audit.created_at)}): summary, PageSpeed results when measured, every finding with its page, recommendations and the content calendar.</p>
            <div className="flex gap-2">
              <Button onClick={async () => { try { download(`${clientName.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}-website-audit.md`, await api.auditReport(audit.id), "text/markdown"); } catch (e) { fail(e); } }}><Download className="h-4 w-4" />Audit report (Markdown)</Button>
              <Button variant="secondary" onClick={async () => { try { download("seo-findings.csv", await api.auditCsv(audit.id), "text/csv"); } catch (e) { fail(e); } }}><Download className="h-4 w-4" />Findings (CSV)</Button>
            </div></>}
        </div>)}
    </Card>
  );
}

function ChangeTable({ items, withName }: { items: { id: string; change_type: string; url: string | null; old_value: string | null; new_value: string | null; observed_at: string; competitor_name?: string | null }[]; withName?: boolean }) {
  return (
    <Table head={[...(withName ? ["Competitor"] : []), "Change", "Old value", "New value", "Source", "Observed"]}>{items.map((c) => (
      <tr key={c.id}>{withName && <td className="px-5 py-2.5 font-medium">{c.competitor_name || "—"}</td>}
        <td className="px-5 py-2.5"><Badge tone={c.change_type.includes("price") || c.change_type.includes("promotion") ? "amber" : "blue"}>{LABEL(c.change_type)}</Badge></td>
        <td className="max-w-[200px] truncate px-5 py-2.5 text-navy-500" title={c.old_value || ""}>{c.old_value || "—"}</td>
        <td className="max-w-[200px] truncate px-5 py-2.5" title={c.new_value || ""}>{c.new_value || "—"}</td>
        <td className="max-w-[180px] truncate px-5 py-2.5">{c.url ? <a href={c.url} target="_blank" rel="noopener noreferrer" className="text-brand-600 hover:underline">{short(c.url)}</a> : "—"}</td>
        <td className="whitespace-nowrap px-5 py-2.5 text-xs text-navy-500">{fmtDateTime(c.observed_at)}</td></tr>))}</Table>
  );
}
