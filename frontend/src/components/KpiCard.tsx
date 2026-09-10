import { DataBadge } from "./DataBadge";
import type { DisplayValue } from "@/lib/format";

export function KpiCard({
  eyebrow,
  label,
  value,
  hint,
}: {
  eyebrow: string;
  label: string;
  value: DisplayValue;
  hint?: string;
}) {
  const large = value.kind === "PRESENTE" || value.kind === "ZERO";
  return (
    <article className="border border-olive/10 bg-white px-5 py-4 shadow-card">
      <p className="text-[11px] uppercase tracking-[0.22em] text-gold">{eyebrow}</p>
      <p className="mt-1 text-sm text-olive/70">{label}</p>
      <p className={`mt-3 text-olive ${large ? "ticker text-3xl md:text-4xl" : "font-display text-xl"}`}>
        {value.text}
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <DataBadge state={value.kind} />
        {hint ? <p className="text-[11px] uppercase tracking-[0.14em] text-olive/45">{hint}</p> : null}
      </div>
    </article>
  );
}
