export function EmptyState({
  title,
  detail,
}: {
  title: string;
  detail?: string;
}) {
  return (
    <div className="border border-dashed border-olive/20 bg-sand px-4 py-8 text-center">
      <p className="font-display text-olive">{title}</p>
      {detail ? <p className="mt-2 text-sm text-olive/70">{detail}</p> : null}
    </div>
  );
}
