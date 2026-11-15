"use client";
import { useState } from "react";
import { Badge, Button, Card, CardHeader, Empty, Field, PageHeader, PlannedBanner, Select, Stat } from "@/components/ui";

export default function BuyersPage() {
  const [geo, setGeo] = useState("India"); const [cat, setCat] = useState("Manufacturer");
  return (
    <>
      <PageHeader title="Buyer Intelligence" subtitle="Discover and qualify potential buyers by product application and geography." badge={<Badge tone="blue">Proposed UI</Badge>} />
      <PlannedBanner phase={4}>Metrics will populate only after real discovery campaigns have executed.</PlannedBanner>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Companies discovered" value={null} /><Stat label="Verified companies" value={null} /><Stat label="High-potential leads" value={null} /><Stat label="Markets researched" value={null} />
      </div>
      <Card className="mt-6">
        <CardHeader title="Research filters" />
        <div className="grid gap-4 p-5 md:grid-cols-3">
          <Field label="Geography"><Select value={geo} onChange={(e) => setGeo(e.target.value)}><option>India</option><option>Global</option></Select></Field>
          <Field label="Buyer category"><Select value={cat} onChange={(e) => setCat(e.target.value)}>{["Manufacturer", "Importer", "Distributor", "Dealer / reseller", "OEM buyer", "Institutional buyer", "Project buyer"].map((x) => <option key={x}>{x}</option>)}</Select></Field>
          <Field label="Verification"><Select disabled><option>Evidence required</option></Select></Field>
        </div>
        <div className="flex justify-end border-t border-line p-4"><Button disabled>Start discovery campaign</Button></div>
      </Card>
      <Card className="mt-6"><CardHeader title="Prospect database" /><Empty title="No prospects yet" body="Prospects appear here only after a discovery campaign has found and verified them, each with its source." /></Card>
    </>
  );
}
