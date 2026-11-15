"use client";
import { useMemo, useState } from "react";
import { AddProductButton, ProductCards, ProductModal } from "@/components/Products";
import { ButtonLink, Card, CardHeader, Empty, ErrorBox, Input, PageHeader, Select, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { Product } from "@/lib/types";
import { useAsync } from "@/lib/useAsync";

export default function ProductsPage() {
  const [clientId, setClientId] = useState(""); const [q, setQ] = useState("");
  const [modal, setModal] = useState<{ open: boolean; product: Product | null }>({ open: false, product: null });
  const clients = useAsync(() => api.listClients());
  const products = useAsync(() => api.listProducts({ client_id: clientId || undefined, q: q || undefined }), [clientId, q]);
  const byId = useMemo(() => Object.fromEntries((clients.data?.items || []).map((c) => [c.id, c.company_name])), [clients.data]);

  return (
    <>
      <PageHeader title="Products & services" subtitle="Every client's catalogue in one place." />
      {clients.data && !clients.data.items.length ? <Card><Empty title="Add a client first" body="Products and services always belong to a client." action={<ButtonLink href="/clients/new/">Add client</ButtonLink>} /></Card> : (
        <Card>
          <CardHeader title="Catalogue" action={<AddProductButton onClick={() => setModal({ open: true, product: null })} />} />
          <div className="flex flex-wrap gap-3 border-b border-line p-4">
            <Select className="max-w-xs" value={clientId} onChange={(e) => setClientId(e.target.value)}><option value="">All clients</option>{clients.data?.items.map((c) => <option key={c.id} value={c.id}>{c.company_name}</option>)}</Select>
            <Input className="max-w-xs" placeholder="Search name or category" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          {products.loading ? <Skeleton /> : products.error ? <ErrorBox message={products.error} onRetry={products.reload} /> :
            <ProductCards items={products.data!.items} clientsById={byId} onEdit={(p) => setModal({ open: true, product: p })} onDeleted={products.reload} />}
        </Card>
      )}
      {modal.open && <ProductModal open clients={clients.data?.items} clientId={clientId} initial={modal.product} onClose={() => setModal({ open: false, product: null })} onSaved={products.reload} />}
    </>
  );
}
