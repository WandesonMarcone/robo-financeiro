export function ErrorState({
  title = "Falha de comunicacao",
  detail,
}: {
  title?: string;
  detail?: string;
}) {
  return (
    <div className="border border-[#5c1f1f]/30 bg-white px-4 py-6">
      <p className="text-[11px] uppercase tracking-[0.18em] text-[#5c1f1f]">Erro</p>
      <p className="mt-1 font-display text-olive">{title}</p>
      {detail ? <p className="mt-2 text-sm text-olive/70">{detail}</p> : null}
    </div>
  );
}
