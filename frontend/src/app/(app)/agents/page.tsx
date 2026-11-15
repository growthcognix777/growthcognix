"use client";
import { BarChart3, Bot, Globe, Lightbulb, MessageSquare, Search, Target, TrendingUp } from "lucide-react";
import { Badge, Card, ErrorBox, PageHeader, PlannedBanner, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";

const ICONS: Record<string, React.ElementType> = { business_analyst: Lightbulb, website_auditor: Globe, market_researcher: TrendingUp, competitor_analyst: BarChart3,
  buyer_finder: Target, lead_scorer: Search, marketing_strategist: Bot, sales_assistant: MessageSquare };

export default function AgentsPage() {
  const { data, error, loading, reload } = useAsync(() => api.listAgents());
  return (
    <>
      <PageHeader title="AI agent centre" subtitle="Specialist agents that will research, analyse and draft — always with evidence and human review." />
      <PlannedBanner phase={2}>Agents are shown as <strong>planned</strong> until their execution APIs exist. No agent has run, so there are no results, histories or outputs to show yet.</PlannedBanner>
      {loading ? <Card><Skeleton rows={4} /></Card> : error ? <Card><ErrorBox message={error} onRetry={reload} /></Card> : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {data!.map((a) => { const Icon = ICONS[a.key] || Bot; return (
            <Card key={a.key} className="flex flex-col p-5">
              <div className="flex items-start justify-between"><div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-50 text-brand-600"><Icon className="h-5 w-5" /></div><Badge>Planned · Phase {a.phase}</Badge></div>
              <h3 className="mt-4 font-semibold text-navy-950">{a.name}</h3>
              <p className="mt-1 flex-1 text-sm text-navy-500">{a.description}</p>
              <dl className="mt-4 grid grid-cols-2 gap-2 border-t border-line pt-3 text-xs">
                <div><dt className="text-navy-400">Jobs run</dt><dd className="font-medium text-navy-900">{a.total_jobs}</dd></div>
                <div><dt className="text-navy-400">Last run</dt><dd className="font-medium text-navy-900">{a.last_job_at ? fmtDate(a.last_job_at) : "Never"}</dd></div>
              </dl>
            </Card>); })}
        </div>
      )}
    </>
  );
}
