import { Card } from "./Card";
import { EmptyState } from "./EmptyState";

export function PlaceholderPage({
  title,
  contract,
}: {
  title: string;
  contract: string;
}) {
  return (
    <div className="space-y-6">
      <header>
        <p className="text-[11px] uppercase tracking-[0.24em] text-gold">Area autenticada</p>
        <h1 className="font-display text-3xl text-olive md:text-4xl">{title}</h1>
      </header>
      <Card eyebrow="Contrato" title="Somente /api/v1">
        <p className="text-sm leading-6 text-olive/80">{contract}</p>
      </Card>
      <EmptyState
        title="Conteudo operacional nas etapas seguintes"
        detail="Area autenticada pronta. Sem graficos, carteira ou dados reais nesta etapa."
      />
    </div>
  );
}
