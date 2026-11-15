"use client";
import { ListChecks } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Card, Empty, ErrorBox, PageHeader, Select, Skeleton, Table } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import type { JobStatus } from "@/lib/types";
import { useAsync } from "@/lib/useAsync";

const TONE: Record<JobStatus, "slate" | "blue" | "green" | "red" | "amber"> = { queued: "slate", running: "blue", completed: "green", failed: "red", cancelled: "amber" };

export default function JobsPage() {
  const [status, setStatus] = useState("");
  const { data, error, loading, reload } = useAsync(() => api.listJobs({ status: status || undefined }), [status]);
  const clients = useAsync(() => api.listClients());
  const name = (id: string | null) => clients.data?.items.find((c) => c.id === id)?.company_name || "—";
  return (
    <>
      <PageHeader title="Research jobs" subtitle="Status, progress, errors and results of background research." />
      <Card>
        <div className="flex border-b border-line p-4"><Select className="max-w-[200px]" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>{Object.keys(TONE).map((s) => <option key={s} value={s} className="capitalize">{s}</option>)}</Select></div>
        {loading ? <Skeleton /> : error ? <ErrorBox message={error} onRetry={reload} /> : !data?.items.length ? (
          <Empty icon={<ListChecks className="h-5 w-5" />} title="No research jobs yet" body="Jobs are created when agents run. Redis-backed workers are connected in Phase 2, so this list stays empty until then." />
        ) : (
          <Table head={["Job type", "Client", "Status", "Progress", "Started", "Completed", "Error", ""]}>
            {data.items.map((j) => (
              <tr key={j.id}><td className="px-5 py-3 font-medium text-navy-950">{j.job_type}</td><td className="px-5 py-3">{name(j.client_id)}</td>
                <td className="px-5 py-3"><Badge tone={TONE[j.status]}>{j.status}</Badge></td>
                <td className="px-5 py-3"><div className="h-1.5 w-24 rounded bg-canvas"><div className="h-full rounded bg-brand-500" style={{ width: `${j.progress}%` }} /></div></td>
                <td className="px-5 py-3 text-navy-500">{fmtDateTime(j.started_at)}</td><td className="px-5 py-3 text-navy-500">{fmtDateTime(j.completed_at)}</td>
                <td className="max-w-[200px] truncate px-5 py-3 text-red-600">{j.error || ""}</td>
                <td className="px-5 py-3">{["queued", "running"].includes(j.status) && <Button size="sm" variant="secondary" onClick={() => api.cancelJob(j.id).then(reload)}>Cancel</Button>}</td></tr>))}
          </Table>
        )}
      </Card>
    </>
  );
}
