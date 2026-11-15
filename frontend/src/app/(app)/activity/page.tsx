"use client";
import { useState } from "react";
import { Badge, Card, Empty, ErrorBox, PageHeader, Select, Skeleton, Table } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";

export default function ActivityPage() {
  const [type, setType] = useState("");
  const { data, error, loading, reload } = useAsync(() => api.listActivity({ limit: 200, entity_type: type || undefined }), [type]);
  const users = useAsync(() => api.listUsers());
  const who = (id: string | null) => users.data?.find((u) => u.id === id)?.full_name || "System";
  return (
    <>
      <PageHeader title="Activity history" subtitle="An audit trail of important actions in your agency." />
      <Card>
        <div className="flex border-b border-line p-4"><Select className="max-w-[220px]" value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">All activity</option>{["client", "product", "document", "user", "tenant", "job"].map((t) => <option key={t} value={t} className="capitalize">{t}</option>)}</Select></div>
        {loading ? <Skeleton /> : error ? <ErrorBox message={error} onRetry={reload} /> : !data?.items.length ? <Empty title="No activity recorded" /> : (
          <Table head={["When", "Who", "Action", "Details"]}>
            {data.items.map((a) => (
              <tr key={a.id}><td className="whitespace-nowrap px-5 py-3 text-navy-500">{fmtDateTime(a.created_at)}</td><td className="px-5 py-3 text-navy-800">{who(a.user_id)}</td>
                <td className="px-5 py-3"><Badge tone={a.action.includes("deleted") ? "red" : a.action.includes("created") || a.action.includes("uploaded") ? "green" : "slate"}>{a.action}</Badge></td>
                <td className="px-5 py-3 text-navy-900">{a.summary}</td></tr>))}
          </Table>
        )}
      </Card>
    </>
  );
}
