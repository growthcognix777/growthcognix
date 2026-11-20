"use client";
import { Archive, ArrowLeft, ExternalLink, Pencil, RotateCcw, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { DocumentTable, Uploader } from "@/components/Documents";
import { ClientIntelligence } from "@/components/Intelligence";
import { WebIntel } from "@/components/WebIntel";
import { BuyerDiscovery } from "@/components/Leads";
import { MarketingStudio } from "@/components/Marketing";
import { AddProductButton, ProductCards, ProductModal } from "@/components/Products";
import { Badge, Button, ButtonLink, Card, CardHeader, ErrorBox, Skeleton, Spinner, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, fmtMoney, timeAgo } from "@/lib/format";
import type { Product } from "@/lib/types";
import { useAsync } from "@/lib/useAsync";

const TABS = ["Overview", "Products & services", "Documents", "Intelligence", "Website & competitors", "Buyer discovery", "Marketing", "Activity"] as const;

function Detail() {
  const params = useSearchParams(); const id = params.get("id") || ""; const router = useRouter(); const { session } = useAuth();
  const [tab, setTab] = useState<(typeof TABS)[number]>(params.get("tab") === "buyers" ? "Buyer discovery" : params.get("tab") === "marketing" ? "Marketing" : "Overview");
  const [modal, setModal] = useState<{ open: boolean; product: Product | null }>({ open: false, product: null });
  const client = useAsync(() => api.getClient(id), [id]);
  const products = useAsync(() => api.listProducts({ client_id: id }), [id]);
  const docs = useAsync(() => api.listDocuments({ client_id: id }), [id]);
  const users = useAsync(() => api.listUsers());
  const act = useAsync(async () => (await api.listActivity({ limit: 200 })).items.filter((a) => a.entity_id === id || a.meta?.client_id === id), [id, tab]);
  const role = session?.user.role || "staff";
  const [busy, setBusy] = useState(false);

  if (client.loading) return <Spinner />;
  if (client.error || !client.data) return <Card><ErrorBox message={client.error || "Client not found"} /></Card>;
  const c = client.data;
  const assignee = users.data?.find((u) => u.id === c.assigned_user_id);
  const names: Record<string, string> = { [c.id]: "Client" }; products.data?.items.forEach((p) => (names[p.id] = p.name));

  const act_ = async (fn: () => Promise<unknown>, after?: () => void) => { setBusy(true); try { await fn(); after ? after() : client.reload(); } catch (e) { alert(e instanceof Error ? e.message : "Failed"); } finally { setBusy(false); } };

  return (
    <>
      <Link href="/clients/" className="mb-4 inline-flex items-center gap-1 text-sm text-navy-500 hover:text-navy-900"><ArrowLeft className="h-4 w-4" />Clients</Link>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2"><h1 className="text-2xl font-semibold tracking-tight text-navy-950">{c.company_name}</h1>{c.archived_at && <Badge tone="amber">Archived</Badge>}</div>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-navy-500">
            {c.industry && <span>{c.industry}</span>}{c.business_type && <span>· {c.business_type}</span>}
            {c.website && <a href={c.website} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-brand-600 hover:underline">{c.website.replace(/^https?:\/\//, "")}<ExternalLink className="h-3 w-3" /></a>}
          </div>
        </div>
        <div className="flex gap-2">
          {!c.archived_at && <ButtonLink variant="secondary" href={`/clients/edit/?id=${c.id}`}><Pencil className="h-4 w-4" />Edit</ButtonLink>}
          {["owner", "admin", "manager"].includes(role) && (c.archived_at
            ? <Button variant="secondary" loading={busy} onClick={() => act_(() => api.restoreClient(c.id))}><RotateCcw className="h-4 w-4" />Restore</Button>
            : <Button variant="secondary" loading={busy} onClick={() => confirm("Archive this client? You can restore it later.") && act_(() => api.archiveClient(c.id))}><Archive className="h-4 w-4" />Archive</Button>)}
          {c.archived_at && ["owner", "admin"].includes(role) && <Button variant="danger" loading={busy} onClick={() => confirm("Permanently delete this client, its products and documents?") && act_(() => api.deleteClient(c.id), () => router.push("/clients/"))}><Trash2 className="h-4 w-4" />Delete</Button>}
        </div>
      </div>

      <div className="mb-6 flex gap-1 overflow-x-auto border-b border-line">
        {TABS.map((t) => <button key={t} onClick={() => setTab(t)} className={cx("-mb-px whitespace-nowrap border-b-2 px-3 py-2.5 text-sm transition", tab === t ? "border-brand-600 font-medium text-brand-700" : "border-transparent text-navy-500 hover:text-navy-900")}>
          {t}{t === "Products & services" && ` (${c.product_count})`}{t === "Documents" && ` (${c.document_count})`}</button>)}
      </div>

      {tab === "Overview" && (
        <div className="grid gap-6 lg:grid-cols-3">
          <Card className="lg:col-span-2"><CardHeader title="Business profile" />
            <div className="space-y-5 p-5 text-sm">
              <div><div className="text-xs font-medium uppercase tracking-wide text-navy-400">Description</div><p className="mt-1 whitespace-pre-line text-navy-800">{c.description || "Not provided yet."}</p></div>
              <div><div className="text-xs font-medium uppercase tracking-wide text-navy-400">Business objectives</div><p className="mt-1 whitespace-pre-line text-navy-800">{c.business_objectives || "Not provided yet."}</p></div>
              <div><div className="text-xs font-medium uppercase tracking-wide text-navy-400">Target markets</div>
                <div className="mt-2 flex flex-wrap gap-1.5">{c.target_markets.length ? c.target_markets.map((m) => <Badge key={m} tone="blue">{m}</Badge>) : <span className="text-navy-500">None set.</span>}</div></div>
            </div></Card>
          <Card><CardHeader title="Details" />
            <dl className="divide-y divide-line text-sm">
              {[["Contact", c.contact_name], ["Email", c.contact_email], ["Phone", c.contact_phone], ["Address", c.address],
                ["Marketing budget", c.marketing_budget != null ? `${fmtMoney(c.marketing_budget, c.budget_currency)} / month` : null],
                ["Assigned to", assignee?.full_name], ["Created", fmtDate(c.created_at)], ["Last updated", fmtDate(c.updated_at)]].map(([k, v]) => (
                <div key={k} className="flex justify-between gap-4 px-5 py-2.5"><dt className="text-navy-500">{k}</dt><dd className="text-right font-medium text-navy-900">{v || "—"}</dd></div>))}
            </dl></Card>
        </div>
      )}

      {tab === "Products & services" && (
        <Card><CardHeader title="Catalogue" subtitle="Products and services this client sells." action={!c.archived_at && <AddProductButton onClick={() => setModal({ open: true, product: null })} />} />
          {products.loading ? <Skeleton /> : products.error ? <ErrorBox message={products.error} onRetry={products.reload} /> :
            <ProductCards items={products.data!.items} onEdit={(p) => setModal({ open: true, product: p })} onDeleted={() => { products.reload(); client.reload(); }} />}
          {modal.open && <ProductModal open clientId={c.id} initial={modal.product} onClose={() => setModal({ open: false, product: null })} onSaved={() => { products.reload(); client.reload(); }} />}
        </Card>
      )}

      {tab === "Documents" && (
        <Card><CardHeader title="Documents" subtitle="Catalogues, specification sheets, certificates and images." />
          {!c.archived_at && <Uploader clientId={c.id} products={products.data?.items} onUploaded={() => { docs.reload(); client.reload(); }} />}
          {docs.loading ? <Skeleton /> : docs.error ? <ErrorBox message={docs.error} onRetry={docs.reload} /> : <DocumentTable items={docs.data!.items} names={names} onDeleted={() => { docs.reload(); client.reload(); }} />}
        </Card>
      )}

      {tab === "Intelligence" && (products.loading ? <Skeleton /> :
        <ClientIntelligence clientId={c.id} clientName={c.company_name} archived={!!c.archived_at} products={products.data?.items || []} />
      )}

      {tab === "Website & competitors" && <WebIntel clientId={c.id} clientName={c.company_name} clientWebsite={c.website || null} archived={!!c.archived_at} />}
      {tab === "Buyer discovery" && <BuyerDiscovery clientId={c.id} clientName={c.company_name} archived={!!c.archived_at} />}

      {tab === "Marketing" && (products.loading ? <Skeleton /> : <MarketingStudio clientId={c.id} clientName={c.company_name} archived={!!c.archived_at} products={products.data?.items || []} />)}

      {tab === "Activity" && (
        <Card><CardHeader title="Client activity" />
          {act.loading ? <Skeleton /> : <ul className="divide-y divide-line">{act.data?.map((a) => <li key={a.id} className="flex justify-between px-5 py-3 text-sm"><span className="text-navy-900">{a.summary}</span><span className="text-xs text-navy-400">{timeAgo(a.created_at)}</span></li>)}</ul>}
        </Card>
      )}
    </>
  );
}
export default function Page() { return <Suspense><Detail /></Suspense>; }
