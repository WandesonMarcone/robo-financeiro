import { KpiCard } from "./KpiCard";
import { countAtivosDistintos, countPosicoes, latestTimestamp } from "@/lib/carteira";
import { displayCount, displayField, formatDate, sumPresent } from "@/lib/format";
import type { CarteiraData } from "@/lib/carteira";

export function CarteiraResumo({ data }: { data: CarteiraData }) {
  const posicoes = countPosicoes(data.carteira);
  const ativos =
    data.carteira.kind === "ok" ? countAtivosDistintos(data.carteira.data) : null;
  const investidos =
    data.carteira.kind === "ok"
      ? sumPresent(data.carteira.data.map((item) => item.valor_investido))
      : { total: null, used: 0, skipped: 0 };
  const atualizado =
    data.carteira.kind === "ok"
      ? latestTimestamp(data.carteira.data.map((item) => item.atualizado_em || item.criado_em))
      : null;
  const atualizadoLabel = formatDate(atualizado);

  return (
    <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <KpiCard
        eyebrow="Custo"
        label="Valor investido"
        value={displayField(investidos.total, null, true)}
        hint={
          data.carteira.kind === "ok"
            ? investidos.skipped
              ? `${investidos.used} posicoes somadas; ${investidos.skipped} AUSENTE`
              : "Soma de valor_investido da API (custo)"
            : data.carteira.kind === "forbidden"
              ? "403 carteira pessoal"
              : "Carteira indisponivel"
        }
      />
      <KpiCard
        eyebrow="Posicoes"
        label="Numero de posicoes"
        value={displayCount(posicoes)}
        hint={data.carteira.kind === "forbidden" ? "403 carteira pessoal" : "GET /carteira"}
      />
      <KpiCard
        eyebrow="Ativos"
        label="Quantidade de ativos"
        value={displayCount(ativos)}
        hint="Tickers distintos retornados pela API"
      />
      <KpiCard
        eyebrow="Atualizacao"
        label="Ultima atualizacao"
        value={
          atualizadoLabel
            ? { kind: "PRESENTE", text: atualizadoLabel, raw: atualizado }
            : { kind: "AUSENTE", text: "AUSENTE", raw: null }
        }
        hint="Maior atualizado_em das posicoes"
      />
    </section>
  );
}
