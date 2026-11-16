"use client";
import {
  Activity, Bell, Bot, Building2, ChevronDown, FileText, FlaskConical, LayoutDashboard, ListChecks, LogOut, Menu,
  Package, Search, Settings, Target, X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, DATA_MODE } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { initials, timeAgo } from "@/lib/format";
import type { Activity as Act } from "@/lib/types";
import { Logo } from "./Logo";
import { Badge, cx } from "./ui";

const NAV = [
  { group: "Workspace", items: [
    { href: "/dashboard/", label: "Dashboard", icon: LayoutDashboard },
    { href: "/clients/", label: "Clients", icon: Building2 },
    { href: "/products/", label: "Products & services", icon: Package },
    { href: "/documents/", label: "Documents", icon: FileText },
  ] },
  { group: "Intelligence", items: [
    { href: "/agents/", label: "AI agent centre", icon: Bot },
    { href: "/research/", label: "Market research", icon: FlaskConical },
    { href: "/buyers/", label: "Buyer discovery", icon: Target },
    { href: "/jobs/", label: "Research jobs", icon: ListChecks },
  ] },
  { group: "Agency", items: [
    { href: "/activity/", label: "Activity history", icon: Activity },
    { href: "/settings/", label: "Settings", icon: Settings },
  ] },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const { session, logout } = useAuth();
  const path = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [menu, setMenu] = useState(false);
  const [bell, setBell] = useState(false);
  const [notes, setNotes] = useState<Act[] | null>(null);
  const [q, setQ] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => setOpen(false), [path]);
  useEffect(() => {
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) { setMenu(false); setBell(false); } };
    document.addEventListener("mousedown", h); return () => document.removeEventListener("mousedown", h);
  }, []);
  useEffect(() => { if (bell) api.listActivity({ limit: 8 }).then((r) => setNotes(r.items)).catch(() => setNotes([])); }, [bell]);

  const onSearch = (e: React.FormEvent) => { e.preventDefault(); if (q.trim()) router.push(`/clients/?q=${encodeURIComponent(q.trim())}`); };
  const doLogout = async () => { await logout(); router.replace("/login/"); };

  const sidebar = (
    <nav className="flex h-full flex-col">
      <div className="flex h-16 items-center px-5"><Link href="/dashboard/"><Logo /></Link></div>
      <div className="flex-1 space-y-6 overflow-y-auto px-3 py-4">
        {NAV.map((g) => (
          <div key={g.group}>
            <div className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-wider text-navy-400">{g.group}</div>
            {g.items.map(({ href, label, icon: Icon }) => {
              const active = path === href || (href !== "/dashboard/" && path.startsWith(href));
              return (
                <Link key={href} href={href} className={cx("mb-0.5 flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
                  active ? "bg-brand-50 font-medium text-brand-700" : "text-navy-700 hover:bg-canvas hover:text-navy-950")}>
                  <Icon className="h-4 w-4" />{label}
                </Link>
              );
            })}
          </div>
        ))}
      </div>
      <div className="border-t border-line p-4 text-xs text-navy-500">Phase 2 · Client Intelligence{DATA_MODE === "local" && <div className="mt-1"><Badge tone="amber">Browser sandbox</Badge></div>}</div>
    </nav>
  );

  return (
    <div className="min-h-screen bg-canvas">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 border-r border-line bg-white lg:block">{sidebar}</aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-navy-950/30" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 bg-white shadow-xl animate-fade">
            <button className="absolute right-3 top-4 rounded p-1 text-navy-500" onClick={() => setOpen(false)} aria-label="Close menu"><X className="h-5 w-5" /></button>{sidebar}
          </aside>
        </div>
      )}
      <div className="lg:pl-64">
        <header ref={ref} className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-line bg-white/90 px-4 backdrop-blur lg:px-8">
          <button className="rounded-lg p-2 text-navy-700 hover:bg-canvas lg:hidden" onClick={() => setOpen(true)} aria-label="Open menu"><Menu className="h-5 w-5" /></button>
          <form onSubmit={onSearch} className="relative max-w-md flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-navy-400" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search clients by name, industry or website"
              className="h-10 w-full rounded-lg border border-line bg-canvas pl-9 pr-3 text-sm outline-none focus:border-brand-500 focus:bg-white focus:ring-2 focus:ring-brand-500/20" />
          </form>
          <div className="ml-auto flex items-center gap-1">
            <div className="relative">
              <button onClick={() => { setBell(!bell); setMenu(false); }} className="rounded-lg p-2 text-navy-700 hover:bg-canvas" aria-label="Notifications"><Bell className="h-5 w-5" /></button>
              {bell && (
                <div className="absolute right-0 mt-2 w-80 rounded-xl border border-line bg-white shadow-lg animate-fade">
                  <div className="border-b border-line px-4 py-3 text-sm font-semibold text-navy-950">Recent activity</div>
                  <div className="max-h-80 overflow-y-auto">
                    {notes === null ? <div className="p-4 text-sm text-navy-500">Loading…</div> : notes.length === 0 ? <div className="p-4 text-sm text-navy-500">Nothing yet.</div> :
                      notes.map((n) => <div key={n.id} className="border-b border-line px-4 py-2.5 last:border-0"><div className="text-sm text-navy-900">{n.summary}</div><div className="text-xs text-navy-400">{timeAgo(n.created_at)}</div></div>)}
                  </div>
                  <Link href="/activity/" className="block border-t border-line px-4 py-2.5 text-center text-sm font-medium text-brand-600 hover:bg-canvas">View all activity</Link>
                </div>
              )}
            </div>
            <div className="relative">
              <button onClick={() => { setMenu(!menu); setBell(false); }} className="flex items-center gap-2 rounded-lg py-1.5 pl-1.5 pr-2 hover:bg-canvas">
                <span className="flex h-8 w-8 items-center justify-center rounded-full bg-navy-950 text-xs font-semibold text-white">{session ? initials(session.user.full_name) : ""}</span>
                <span className="hidden text-left sm:block"><span className="block text-sm font-medium leading-4 text-navy-950">{session?.user.full_name}</span><span className="block text-xs capitalize text-navy-500">{session?.user.role} · {session?.tenant.name}</span></span>
                <ChevronDown className="h-4 w-4 text-navy-400" />
              </button>
              {menu && (
                <div className="absolute right-0 mt-2 w-56 rounded-xl border border-line bg-white py-1 shadow-lg animate-fade">
                  <div className="px-4 py-2 text-xs text-navy-500">{session?.user.email}</div>
                  <Link href="/settings/" className="flex items-center gap-2 px-4 py-2 text-sm text-navy-800 hover:bg-canvas"><Settings className="h-4 w-4" />Settings</Link>
                  <button onClick={doLogout} className="flex w-full items-center gap-2 px-4 py-2 text-sm text-red-600 hover:bg-red-50"><LogOut className="h-4 w-4" />Sign out</button>
                </div>
              )}
            </div>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-4 py-8 lg:px-8 animate-fade">{children}</main>
      </div>
    </div>
  );
}
