"use client";
import { ArrowRight, Target } from "lucide-react";
import Link from "next/link";
import { Badge, Card, CardHeader, Empty, ErrorBox, PageHeader, Skeleton, Table } from "@/components/ui";
import { api } from "@/lib/api";
import type { LeadSummary } from "@/lib/types";
import { useAsync } from "@/lib/useAsync";

/** Agency-wide view: every client's discovery numbers, read from real records only. Work happens on each client's Buyer discovery tab. */
export default function BuyersPage() {
  const rows = useAsync(async () => {
    const clients = (await api.listClients({})).items;
    const sums = await Promise.all(clients.map((c) => api.leadSummary(c.id).catch(() => null)));
    return clients.map((c, i) => ({ c, s: sums[i] as LeadSummary | null }));
  });
  const prov = useAsync(() => api.leadProviders());
  const configured = prov.data?.providers.filter((p) => p.configured && ["search", "directory"].includes(p.kind)).map((p) => p.label) || [];
  return (
    <>
      <PageHeader title="Buyer discovery" subtitle="Find and qualify buyers by application, need and geography. Every lead keeps its sources." badge={<Badge tone="green">Phase 4</Badge>} />
      {prov.data && <div className="mb-6 rounded-lg border border-line bg-white p-4 text-sm text-navy-600">
        {api.mode === "local" ? "Browser preview: searches, site checks and UN Comtrade run only on the backend. Profiles, research areas and prospects you add yourself work here."
          : configured.length ? `Search sources configured: ${configured.join(", ")}.` : "No search source is configured on the server yet (SearXNG, Google Programmable Search or Brave). Directory lists and manual prospects still work."}
      </div>}
      <Card><CardHeader title="Clients" subtitle="Open a client to build profiles, run campaigns and verify leads" />
        {rows.loading ? <Skeleton /> : rows.error ? <ErrorBox message={rows.error} /> : !rows.data!.length ? <Empty title="No clients yet" body="Add a client and its products first." icon={<Target className="h-5 w-5" />} /> : (
          <Table head={["Client", "Buyer profiles", "Research areas", "Prospects", "Approved", "Avg score", ""]}>
            {rows.data!.map(({ c, s }) => <tr key={c.id}>
              <td className="px-5 py-2.5 font-medium text-navy-900">{c.company_name}</td>
              <td className="px-5 py-2.5">{s ? s.profiles : "—"}</td><td className="px-5 py-2.5">{s ? s.areas : "—"}</td>
              <td className="px-5 py-2.5">{s?.prospects ? s.prospects : "—"}</td>
              <td className="px-5 py-2.5">{s?.prospects ? (s.by_crm.approved || 0) + (s.by_crm.handed_off || 0) : "—"}</td>
              <td className="px-5 py-2.5">{s?.avg_score != null ? Math.round(s.avg_score) : "—"}</td>
              <td className="px-5 py-2.5 text-right"><Link className="inline-flex items-center gap-1 text-brand-600 hover:underline" href={`/clients/view/?id=${c.id}&tab=buyers`}>Open<ArrowRight className="h-3.5 w-3.5" /></Link></td>
            </tr>)}
          </Table>)}
      </Card>
    </>
  );
}
