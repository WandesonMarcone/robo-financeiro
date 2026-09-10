import Link from "next/link";
import { DataBadge } from "./DataBadge";
import { campoDoSnapshot, freshnessSummary } from "@/lib/ativos";
import { displayField } from "@/lib/format";
import type { CarteiraPosicaoItem } from "@/lib/carteira";

export function PosicaoRow({ item }: { item: CarteiraPosicaoItem }) {
  const ticker = item.posicao.ticker || "AUSENTE";
  const href = item.posicao.ticker ? `/ativos/${encodeURIComponent(item.posicao.ticker)}` : "/carteira";
  const quantidade = displayField(item.posicao.quantidade);
  const precoMedio = displayField(item.posicao.preco_medio, null, true);
  const investido = displayField(item.posicao.valor_investido, null, true);
  const mercado = displayField(item.snapshot?.preco ?? null, campoDoSnapshot(item.snapshot, "preco"), true);
  const freshness = freshnessSummary(item.freshness);

  return (
    <tr className="border-b border-olive/10">
      <td className="px-3 py-3">
        {item.posicao.ticker ? (
          <Link href={href} className="ticker text-olive hover:text-gold">
            {ticker}
          </Link>
        ) : (
          <span className="ticker text-olive">{ticker}</span>
        )}
        <p className="mt-1 text-[11px] uppercase tracking-[0.14em] text-olive/45">
          {item.posicao.tipo || "tipo AUSENTE"}
        </p>
      </td>
      <td className="px-3 py-3">
        <p className="text-sm text-olive/70">AUSENTE</p>
        <DataBadge state="AUSENTE" />
      </td>
      <td className="px-3 py-3">
        <p className="ticker text-sm text-olive">{quantidade.text}</p>
        <DataBadge state={quantidade.kind} />
      </td>
      <td className="px-3 py-3">
        <p className="ticker text-sm text-olive">{precoMedio.text}</p>
        <DataBadge state={precoMedio.kind} />
      </td>
      <td className="px-3 py-3">
        <p className="ticker text-sm text-olive">{investido.text}</p>
        <DataBadge state={investido.kind} />
      </td>
      <td className="px-3 py-3">
        <p className="ticker text-sm text-olive">{mercado.text}</p>
        <div className="mt-1 flex flex-wrap items-center gap-1">
          <DataBadge state={mercado.kind} />
          <DataBadge state={freshness.state} />
        </div>
      </td>
    </tr>
  );
}
