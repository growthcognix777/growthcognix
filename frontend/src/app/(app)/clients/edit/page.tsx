"use client";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { ClientForm } from "@/components/ClientForm";
import { Card, ErrorBox, PageHeader, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/useAsync";

function Edit() {
  const id = useSearchParams().get("id") || "";
  const { data, error, loading } = useAsync(() => api.getClient(id), [id]);
  if (loading) return <Spinner />;
  if (error || !data) return <Card><ErrorBox message={error || "Client not found"} /></Card>;
  return <div className="mx-auto max-w-4xl"><PageHeader title={`Edit ${data.company_name}`} /><ClientForm initial={data} /></div>;
}
export default function Page() { return <Suspense><Edit /></Suspense>; }
