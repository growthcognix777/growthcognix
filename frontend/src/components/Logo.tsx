const base = process.env.NEXT_PUBLIC_BASE_PATH || "";
export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className="flex items-center gap-2.5">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={`${base}/icon.svg`} alt="" className="h-8 w-8 rounded-lg" />
      {!compact && <span className="text-[17px] font-bold tracking-tight text-navy-950">Growth<span className="font-semibold text-teal-500">Cognix</span></span>}
    </span>
  );
}
