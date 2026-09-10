export function Loading({ label = "Carregando" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 text-sm text-olive/70" role="status">
      <span className="h-2 w-2 animate-pulse bg-gold" />
      {label}
    </div>
  );
}
