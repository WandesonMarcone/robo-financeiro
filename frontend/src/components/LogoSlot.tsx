export function LogoSlot({ compact = false }: { compact?: boolean }) {
  return (
    <div
      className={`flex items-center gap-3 ${compact ? "h-10" : "h-12"}`}
      aria-label="Estrategia Fardada"
    >
      <div
        className={`shrink-0 border border-gold/60 bg-olive ${compact ? "h-8 w-8" : "h-10 w-10"}`}
        aria-hidden="true"
      />
      <div className="min-w-0 leading-tight">
        <p className="font-display text-sm uppercase tracking-[0.18em] text-gold">
          Estrategia Fardada
        </p>
        {!compact ? (
          <p className="text-[11px] uppercase tracking-[0.22em] text-sand/70">
            Terminal institucional
          </p>
        ) : null}
      </div>
    </div>
  );
}
