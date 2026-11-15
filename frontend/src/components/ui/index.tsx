"use client";
import { AlertCircle, Inbox, Loader2, X } from "lucide-react";
import Link from "next/link";
import { forwardRef, useState } from "react";

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

type BtnProps = React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger"; loading?: boolean; size?: "sm" | "md" };
export function Button({ variant = "primary", loading, size = "md", className, children, disabled, ...p }: BtnProps) {
  const v = {
    primary: "bg-brand-600 text-white hover:bg-brand-700 shadow-sm",
    secondary: "bg-white text-navy-900 border border-line hover:bg-canvas",
    ghost: "text-navy-700 hover:bg-canvas",
    danger: "bg-white text-red-600 border border-red-200 hover:bg-red-50",
  }[variant];
  return (
    <button className={cx("inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/40",
      size === "sm" ? "h-8 px-3 text-sm" : "h-10 px-4 text-sm", v, className)} disabled={disabled || loading} {...p}>
      {loading && <Loader2 className="h-4 w-4 animate-spin" />}{children}
    </button>
  );
}

export function ButtonLink({ href, children, variant = "primary", className }: { href: string; children: React.ReactNode; variant?: "primary" | "secondary"; className?: string }) {
  return <Link href={href} className={cx("inline-flex h-10 items-center gap-2 rounded-lg px-4 text-sm font-medium transition-colors",
    variant === "primary" ? "bg-brand-600 text-white hover:bg-brand-700 shadow-sm" : "border border-line bg-white text-navy-900 hover:bg-canvas", className)}>{children}</Link>;
}

export function Field({ label, error, hint, required, children }: { label: string; error?: string; hint?: string; required?: boolean; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-navy-900">{label}{required && <span className="text-red-500"> *</span>}</span>
      {children}
      {error ? <span className="mt-1 block text-xs text-red-600">{error}</span> : hint ? <span className="mt-1 block text-xs text-navy-500">{hint}</span> : null}
    </label>
  );
}

const inputCls = (err?: boolean) => cx("w-full rounded-lg border bg-white px-3 text-sm text-navy-950 placeholder:text-navy-400 transition focus:outline-none focus:ring-2",
  err ? "border-red-300 focus:ring-red-200" : "border-line focus:border-brand-500 focus:ring-brand-500/20");

export const Input = forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean }>(
  ({ invalid, className, ...p }, ref) => <input ref={ref} className={cx(inputCls(invalid), "h-10", className)} {...p} />);
Input.displayName = "Input";

export function Textarea({ invalid, className, ...p }: React.TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean }) {
  return <textarea className={cx(inputCls(invalid), "min-h-[96px] py-2", className)} {...p} />;
}

export function Select({ invalid, className, children, ...p }: React.SelectHTMLAttributes<HTMLSelectElement> & { invalid?: boolean }) {
  return <select className={cx(inputCls(invalid), "h-10 pr-8", className)} {...p}>{children}</select>;
}

export function TagInput({ value, onChange, placeholder }: { value: string[]; onChange: (v: string[]) => void; placeholder?: string }) {
  const [draft, setDraft] = useState("");
  const add = () => { const t = draft.trim(); if (t && !value.includes(t)) onChange([...value, t]); setDraft(""); };
  return (
    <div className={cx(inputCls(), "flex min-h-10 flex-wrap items-center gap-1.5 py-1.5")}>
      {value.map((t) => (
        <span key={t} className="inline-flex items-center gap-1 rounded-md bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-700">
          {t}<button type="button" aria-label={`Remove ${t}`} onClick={() => onChange(value.filter((x) => x !== t))}><X className="h-3 w-3" /></button>
        </span>
      ))}
      <input className="min-w-[120px] flex-1 bg-transparent text-sm outline-none" value={draft} placeholder={value.length ? "" : placeholder}
        onChange={(e) => setDraft(e.target.value)} onBlur={add}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); } if (e.key === "Backspace" && !draft && value.length) onChange(value.slice(0, -1)); }} />
    </div>
  );
}

export function Card({ className, children }: { className?: string; children: React.ReactNode }) {
  return <div className={cx("rounded-xl border border-line bg-white shadow-card", className)}>{children}</div>;
}

export function CardHeader({ title, subtitle, action }: { title: string; subtitle?: string; action?: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
      <div><h3 className="text-sm font-semibold text-navy-950">{title}</h3>{subtitle && <p className="mt-0.5 text-xs text-navy-500">{subtitle}</p>}</div>{action}
    </div>
  );
}

export function PageHeader({ title, subtitle, action, badge }: { title: string; subtitle?: string; action?: React.ReactNode; badge?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div><div className="flex items-center gap-2"><h1 className="text-2xl font-semibold tracking-tight text-navy-950">{title}</h1>{badge}</div>
        {subtitle && <p className="mt-1 text-sm text-navy-500">{subtitle}</p>}</div>
      {action && <div className="flex gap-2">{action}</div>}
    </div>
  );
}

export function Badge({ tone = "slate", children }: { tone?: "slate" | "blue" | "green" | "amber" | "red" | "violet"; children: React.ReactNode }) {
  const t = { slate: "bg-slate-100 text-slate-700", blue: "bg-brand-50 text-brand-700", green: "bg-emerald-50 text-emerald-700",
    amber: "bg-amber-50 text-amber-700", red: "bg-red-50 text-red-700", violet: "bg-violet-50 text-violet-700" }[tone];
  return <span className={cx("inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium", t)}>{children}</span>;
}

export function Stat({ label, value, hint, icon }: { label: string; value: number | string | null | undefined; hint?: string; icon?: React.ReactNode }) {
  return (
    <Card className="p-5">
      <div className="flex items-center justify-between text-navy-500"><span className="text-xs font-medium uppercase tracking-wide">{label}</span>{icon}</div>
      <div className="mt-3 text-3xl font-semibold tracking-tight text-navy-950">{value === null || value === undefined ? "—" : value}</div>
      {hint && <div className="mt-1 text-xs text-navy-500">{hint}</div>}
    </Card>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return <div className="flex items-center justify-center gap-2 py-16 text-sm text-navy-500"><Loader2 className="h-4 w-4 animate-spin" />{label}…</div>;
}

export function Skeleton({ rows = 4 }: { rows?: number }) {
  return <div className="space-y-3 p-5">{Array.from({ length: rows }).map((_, i) => <div key={i} className="h-10 animate-pulse rounded-lg bg-canvas" />)}</div>;
}

export function Empty({ title, body, action, icon }: { title: string; body?: string; action?: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-14 text-center animate-fade">
      <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-brand-50 text-brand-600">{icon ?? <Inbox className="h-5 w-5" />}</div>
      <h3 className="text-sm font-semibold text-navy-950">{title}</h3>
      {body && <p className="mt-1 max-w-sm text-sm text-navy-500">{body}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="m-5 flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" /><div className="flex-1">{message}</div>
      {onRetry && <button onClick={onRetry} className="font-medium underline">Retry</button>}
    </div>
  );
}

export function Table({ head, children }: { head: string[]; children: React.ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead><tr className="border-b border-line bg-canvas/60">{head.map((h) => <th key={h} className="whitespace-nowrap px-5 py-2.5 text-xs font-medium uppercase tracking-wide text-navy-500">{h}</th>)}</tr></thead>
        <tbody className="divide-y divide-line">{children}</tbody>
      </table>
    </div>
  );
}

export function Modal({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-navy-950/30 p-4 backdrop-blur-[2px]" onClick={onClose}>
      <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl bg-white shadow-xl animate-fade" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-line px-5 py-4"><h3 className="font-semibold text-navy-950">{title}</h3>
          <button onClick={onClose} aria-label="Close" className="rounded p-1 text-navy-500 hover:bg-canvas"><X className="h-4 w-4" /></button></div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

export function PlannedBanner({ phase, children }: { phase: number; children: React.ReactNode }) {
  return (
    <div className="mb-6 flex items-start gap-3 rounded-xl border border-brand-200 bg-brand-50 p-4 text-sm text-brand-700">
      <Badge tone="blue">Phase {phase}</Badge><div>{children}</div>
    </div>
  );
}
