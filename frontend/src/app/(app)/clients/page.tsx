"use client";
import { Archive, Building2, Plus, Search } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Badge, ButtonLink, Card, Empty, ErrorBox, Input, PageHeader, Skeleton, Table, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate, fmtMoney } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";

function ClientList() {
  const params = useSearchParams(); const router = useRouter();
  const [q, setQ] = useState(params.get("q") || ""); const [archived, setArchived] = useState(false);
  const [debounced, setDebounced] = useState(q);
  useEffect(() => { setQ(params.get("q") || ""); }, [params]);
  useEffect(() => { const t = setTimeout(() => setDebounced(q), 250); return () => clearTimeout(t); }, [q]);
  const { data, error, loading, reload } = useAsync(() => api.listClients({ q: debounced, archived }), [debounced, archived]);

  return (
    <>
      <PageHeader title="Clients" subtitle="Every business your agency manages." action={<ButtonLink href="/clients/new/"><Plus className="h-4 w-4" />New client</ButtonLink>} />
      <Card>
        <div className="flex flex-wrap items-center gap-3 border-b border-line p-4">
          <div className="relative w-full max-w-sm"><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-navy-400" />
            <Input className="pl-9" placeholder="Search name, industry or website" value={q} onChange={(e) => setQ(e.target.value)} /></div>
          <div className="ml-auto flex rounded-lg border border-line p-0.5 text-sm">
            {[false, true].map((a) => <button key={String(a)} onClick={() => setArchived(a)} className={cx("rounded-md px-3 py-1.5", archived === a ? "bg-navy-950 text-white" : "text-navy-700")}>{a ? "Archived" : "Active"}</button>)}
          </div>
        </div>
        {loading ? <Skeleton /> : error ? <ErrorBox message={error} onRetry={reload} /> : !data?.items.length ? (
          debounced ? <Empty title="No matching clients" body={`Nothing matches “${debounced}”.`} icon={<Search className="h-5 w-5" />} /> :
            archived ? <Empty title="No archived clients" icon={<Archive className="h-5 w-5" />} /> :
              <Empty title="No clients yet" body="Create a client profile to capture their products, markets and goals." icon={<Building2 className="h-5 w-5" />} action={<ButtonLink href="/clients/new/">Add client</ButtonLink>} />
        ) : (
          <Table head={["Company", "Industry", "Target markets", "Budget", "Catalogue", "Added"]}>
            {data.items.map((c) => (
              <tr key={c.id} className="cursor-pointer hover:bg-canvas" onClick={() => router.push(`/clients/view/?id=${c.id}`)}>
                <td className="px-5 py-3"><Link href={`/clients/view/?id=${c.id}`} className="font-medium text-navy-950 hover:text-brand-600">{c.company_name}</Link>
                  <div className="text-xs text-navy-500">{c.website?.replace(/^https?:\/\//, "") || "No website"}</div></td>
                <td className="px-5 py-3 text-navy-700">{c.industry || "—"}</td>
                <td className="px-5 py-3"><div className="flex max-w-[220px] flex-wrap gap-1">{c.target_markets.slice(0, 3).map((m) => <Badge key={m}>{m}</Badge>)}{c.target_markets.length > 3 && <Badge>+{c.target_markets.length - 3}</Badge>}{!c.target_markets.length && "—"}</div></td>
                <td className="px-5 py-3 text-navy-700">{fmtMoney(c.marketing_budget, c.budget_currency)}</td>
                <td className="px-5 py-3 text-navy-700">{c.product_count} items · {c.document_count} docs</td>
                <td className="whitespace-nowrap px-5 py-3 text-navy-500">{fmtDate(c.created_at)}</td>
              </tr>))}
          </Table>
        )}
      </Card>
    </>
  );
}
export default function Page() { return <Suspense><ClientList /></Suspense>; }
