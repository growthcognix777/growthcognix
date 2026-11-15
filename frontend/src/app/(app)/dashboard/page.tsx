"use client";
import { Building2, FileText, ListChecks, Package, Plus, Users } from "lucide-react";
import Link from "next/link";
import { ButtonLink, Card, CardHeader, Empty, ErrorBox, PageHeader, Skeleton, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, timeAgo } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";

export default function Dashboard() {
  const { session } = useAuth();
  const sum = useAsync(() => api.dashboard());
  const recent = useAsync(() => api.listClients());
  const act = useAsync(() => api.listActivity({ limit: 6 }));
  const s = sum.data;

  return (
    <>
      <PageHeader title={`Good to see you, ${session?.user.full_name.split(" ")[0]}`} subtitle={`${session?.tenant.name} · agency overview`}
        action={<ButtonLink href="/clients/new/"><Plus className="h-4 w-4" />New client</ButtonLink>} />
      {sum.error && <Card className="mb-6"><ErrorBox message={sum.error} onRetry={sum.reload} /></Card>}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <Stat label="Active clients" value={s?.active_clients} icon={<Building2 className="h-4 w-4" />} hint={s ? `${s.archived_clients} archived` : undefined} />
        <Stat label="Products & services" value={s?.products} icon={<Package className="h-4 w-4" />} />
        <Stat label="Documents" value={s?.documents} icon={<FileText className="h-4 w-4" />} />
        <Stat label="Team members" value={s?.team_members} icon={<Users className="h-4 w-4" />} />
        <Stat label="Jobs in progress" value={s?.jobs_running} icon={<ListChecks className="h-4 w-4" />} hint="Workers arrive in Phase 2" />
      </div>
      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title="Recent clients" action={<Link href="/clients/" className="text-sm font-medium text-brand-600 hover:underline">View all</Link>} />
          {recent.loading ? <Skeleton rows={3} /> : recent.error ? <ErrorBox message={recent.error} onRetry={recent.reload} /> :
            !recent.data?.items.length ? <Empty title="No clients yet" body="Add your first client to start building their business profile." action={<ButtonLink href="/clients/new/">Add client</ButtonLink>} /> :
              <ul className="divide-y divide-line">{recent.data.items.slice(0, 5).map((c) => (
                <li key={c.id}><Link href={`/clients/view/?id=${c.id}`} className="flex items-center justify-between px-5 py-3 hover:bg-canvas">
                  <div><div className="text-sm font-medium text-navy-950">{c.company_name}</div><div className="text-xs text-navy-500">{c.industry || "Industry not set"}</div></div>
                  <div className="text-right text-xs text-navy-500"><div>{c.product_count} products · {c.document_count} docs</div><div>Added {fmtDate(c.created_at)}</div></div>
                </Link></li>))}</ul>}
        </Card>
        <Card>
          <CardHeader title="Latest activity" action={<Link href="/activity/" className="text-sm font-medium text-brand-600 hover:underline">All</Link>} />
          {act.loading ? <Skeleton rows={4} /> : act.error ? <ErrorBox message={act.error} /> :
            <ul className="divide-y divide-line">{act.data?.items.map((a) => (
              <li key={a.id} className="px-5 py-3"><div className="text-sm text-navy-900">{a.summary}</div><div className="text-xs text-navy-400">{timeAgo(a.created_at)}</div></li>))}</ul>}
        </Card>
      </div>
    </>
  );
}
