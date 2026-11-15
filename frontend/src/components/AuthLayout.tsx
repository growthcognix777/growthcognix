import { DATA_MODE } from "@/lib/api";
import { Logo } from "./Logo";

export function AuthLayout({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="flex flex-col justify-center px-6 py-12 sm:px-12 lg:px-20">
        <div className="mx-auto w-full max-w-sm animate-fade">
          <Logo />
          <h1 className="mt-10 text-2xl font-semibold tracking-tight text-navy-950">{title}</h1>
          <p className="mt-1.5 text-sm text-navy-500">{subtitle}</p>
          <div className="mt-8">{children}</div>
          {DATA_MODE === "local" && (
            <p className="mt-8 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
              Browser sandbox: this preview has no server. Accounts and records you create are stored only in this browser. Don&apos;t enter confidential data.
            </p>
          )}
        </div>
      </div>
      <div className="relative hidden overflow-hidden bg-navy-950 lg:block">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_30%_20%,rgba(37,99,235,0.35),transparent_55%)]" />
        <div className="relative flex h-full flex-col justify-end p-16 text-white">
          <div className="max-w-md">
            <div className="text-xs font-semibold uppercase tracking-[0.2em] text-teal-500">Discover · Analyse · Market · Sell · Grow</div>
            <h2 className="mt-4 text-3xl font-semibold leading-tight">Growth intelligence for every client your agency serves.</h2>
            <p className="mt-4 text-sm leading-relaxed text-navy-400">Client profiles, product catalogues and documents in one secure, multi-tenant workspace — the foundation for verified AI research, buyer discovery and campaigns.</p>
          </div>
        </div>
      </div>
    </div>
  );
}
