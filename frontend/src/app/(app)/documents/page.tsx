"use client";
import { useMemo, useState } from "react";
import { DocumentTable, Uploader } from "@/components/Documents";
import { ButtonLink, Card, CardHeader, Empty, ErrorBox, PageHeader, Select, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/useAsync";

export default function DocumentsPage() {
  const [clientId, setClientId] = useState("");
  const clients = useAsync(() => api.listClients());
  const products = useAsync(() => (clientId ? api.listProducts({ client_id: clientId }) : Promise.resolve({ items: [], total: 0 })), [clientId]);
  const docs = useAsync(() => api.listDocuments({ client_id: clientId || undefined }), [clientId]);
  const allProducts = useAsync(() => api.listProducts());
  const names = useMemo(() => ({ ...Object.fromEntries((clients.data?.items || []).map((c) => [c.id, c.company_name])), ...Object.fromEntries((allProducts.data?.items || []).map((p) => [p.id, p.name])) }), [clients.data, allProducts.data]);

  return (
    <>
      <PageHeader title="Documents" subtitle="Securely stored files, linked to clients and products. AI extraction arrives in Phase 2." />
      {clients.data && !clients.data.items.length ? <Card><Empty title="Add a client first" body="Documents are always attached to a client." action={<ButtonLink href="/clients/new/">Add client</ButtonLink>} /></Card> : (
        <Card>
          <CardHeader title="Upload" action={<Select className="h-9 w-64" value={clientId} onChange={(e) => setClientId(e.target.value)}><option value="">All clients (choose one to upload)</option>{clients.data?.items.map((c) => <option key={c.id} value={c.id}>{c.company_name}</option>)}</Select>} />
          <Uploader clientId={clientId || null} products={products.data?.items} onUploaded={() => { docs.reload(); }} />
          <div className="border-t border-line" />
          {docs.loading ? <Skeleton /> : docs.error ? <ErrorBox message={docs.error} onRetry={docs.reload} /> : <DocumentTable items={docs.data!.items} names={names} onDeleted={docs.reload} />}
        </Card>
      )}
    </>
  );
}
