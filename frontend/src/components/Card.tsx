import type { ReactNode } from "react";

export function Card({
  title,
  eyebrow,
  children,
  className = "",
}: {
  title?: string;
  eyebrow?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`bg-white shadow-card border border-olive/10 ${className}`}>
      {(eyebrow || title) && (
        <header className="border-b border-olive/10 px-5 py-4">
          {eyebrow ? (
            <p className="text-[11px] uppercase tracking-[0.22em] text-gold">{eyebrow}</p>
          ) : null}
          {title ? <h2 className="font-display text-lg text-olive">{title}</h2> : null}
        </header>
      )}
      <div className="px-5 py-4">{children}</div>
    </section>
  );
}
