type Tone = "neutral" | "gold" | "olive" | "critical";

const tones: Record<Tone, string> = {
  neutral: "bg-sand text-ink border-olive/15",
  gold: "bg-gold/15 text-olive border-gold/40",
  olive: "bg-olive text-sand border-olive",
  critical: "bg-[#5c1f1f] text-sand border-[#5c1f1f]",
};

export function Badge({
  children,
  tone = "neutral",
}: {
  children: string;
  tone?: Tone;
}) {
  return (
    <span
      className={`inline-flex items-center border px-2 py-0.5 text-[11px] uppercase tracking-[0.16em] ${tones[tone]}`}
    >
      {children}
    </span>
  );
}
