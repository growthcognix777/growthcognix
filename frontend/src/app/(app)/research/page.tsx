"use client";
import { BarChart3, Globe2, MapPin, Target, UserCheck } from "lucide-react";
import { Badge, Button, Card, Field, PageHeader, PlannedBanner, Select, TagInput } from "@/components/ui";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/useAsync";
import { useState } from "react";

const TYPES = [
  { key: "market", title: "Market research", body: "Industry size signals, demand drivers and trends — with sources.", icon: Globe2, phase: 4 },
  { key: "competitor", title: "Competitor research", body: "10–30 relevant competitors, positioning, public pricing and change tracking.", icon: BarChart3, phase: 3 },
  { key: "geo", title: "Geographic opportunity", body: "India states, districts and industrial clusters; export markets and HS codes.", icon: MapPin, phase: 4 },
  { key: "buyer", title: "Buyer discovery", body: "End users, distributors, importers, OEMs, institutional and project buyers.", icon: Target, phase: 4 },
  { key: "qualify", title: "Lead qualification", body: "100-point lead score with a separate evidence-confidence score.", icon: UserCheck, phase: 4 },
];

export default function ResearchPage() {
  const clients = useAsync(() => api.listClients());
  const [kind, setKind] = useState("market"); const [geo, setGeo] = useState<string[]>([]);
  return (
    <>
      <PageHeader title="Market research workspace" subtitle="Plan structured research for a client." badge={<Badge tone="blue">Planned</Badge>} />
      <PlannedBanner phase={3}>Research execution is disabled until the job APIs and workers ship (Phases 3–4). You can explore the workspace; nothing will run and no results are invented.</PlannedBanner>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        {TYPES.map((t) => (
          <button key={t.key} onClick={() => setKind(t.key)} className={`rounded-xl border bg-white p-4 text-left shadow-card transition ${kind === t.key ? "border-brand-500 ring-2 ring-brand-500/15" : "border-line hover:border-brand-200"}`}>
            <t.icon className="h-5 w-5 text-brand-600" /><div className="mt-3 text-sm font-semibold text-navy-950">{t.title}</div><div className="mt-1 text-xs text-navy-500">{t.body}</div>
            <div className="mt-3"><Badge>Phase {t.phase}</Badge></div>
          </button>))}
      </div>
      <Card className="mt-6 p-5">
        <div className="grid gap-4 md:grid-cols-3">
          <Field label="Client"><Select><option>Select a client…</option>{clients.data?.items.map((c) => <option key={c.id}>{c.company_name}</option>)}</Select></Field>
          <div className="md:col-span-2"><Field label="Target geographies" hint="Countries, states, districts or cities"><TagInput value={geo} onChange={setGeo} placeholder="e.g. Karnataka, Belagavi, UAE" /></Field></div>
        </div>
        <div className="mt-5 flex items-center justify-end gap-3"><span className="text-xs text-navy-500">Available once research workers are live.</span><Button disabled>Start research</Button></div>
      </Card>
    </>
  );
}
