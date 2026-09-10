import Link from "next/link";
import { Badge } from "./Badge";
import { DataBadge } from "./DataBadge";
import { campoDoSnapshot, freshnessSummary } from "@/lib/ativos";
import { displayField } from "@/lib/format";
import type { CarteiraPosicaoItem } from "@/lib/carteira";

export function PosicaoCard({ item }: { item: CarteiraPosicaoItem }) {
  const ticker = item.posicao.ticker || "AUSENTE";
  const href = item.posicao.ticker ? `/ativos/${encodeURIComponent(item.posicao.ticker)}` : "/carteira";
  const quantidade = displayField(item.posicao.quantidade);
  const precoMedio = displayField(item.posicao.preco_medio, null, true);
  const investido = displayField(item.posicao.valor_investido, null, true);
  const mercado = displayField(item.snapshot?.preco ?? null, campoDoSnapshot(item.snapshot, "preco"), true);
  const freshness = freshnessSummary(item.freshness);

  return (
    <article className="flex flex-col border border-olive/10 bg-white shadow-card">
      <header className="flex items-start justify-between gap-3 border-b border-olive/10 px-5 py-4">
        <div>
          <p className="text-[11px] uppercase tracking-[0.22em] text-gold">Posicao</p>
          {item.posicao.ticker ? (
            <Link href={href} className="ticker mt-1 block text-2xl text-olive hover:text-gold">
              {ticker}
            </Link>
          ) : (
            <h3 className="ticker mt-1 text-2xl text-olive">{ticker}</h3>
          )}
          <p className="mt-1 text-sm text-olive/60">Nome AUSENTE</p>
        </div>
        <div className="flex flex-col items-end gap-2">
          {item.posicao.tipo ? <Badge tone="olive">{item.posicao.tipo}</Badge> : <DataBadge state="AUSENTE" />}
          <DataBadge state={freshness.state} />
        </div>
      </header>
      <div className="grid gap-4 px-5 py-4 sm:grid-cols-2">
        <div>
          <p className="text-[11px] uppercase tracking-[0.16em] text-olive/45">Quantidade</p>
          <p className="ticker mt-1 text-xl text-olive">{quantidade.text}</p>
          <DataBadge state={quantidade.kind} />
        </div>
        <div>
          <p className="text-[11px] uppercase tracking-[0.16em] text-olive/45">Preco medio</p>
          <p className="ticker mt-1 text-xl text-olive">{precoMedio.text}</p>
          <DataBadge state={precoMedio.kind} />
        </div>
        <div>
          <p className="text-[11px] uppercase tracking-[0.16em] text-olive/45">Valor investido</p>
          <p className="ticker mt-1 text-xl text-olive">{investido.text}</p>
          <DataBadge state={investido.kind} />
        </div>
        <div>
          <p className="text-[11px] uppercase tracking-[0.16em] text-olive/45">Mercado</p>
          <p className="ticker mt-1 text-xl text-olive">{mercado.text}</p>
          <DataBadge state={mercado.kind} />
        </div>
      </div>
    </article>
  );
}
