import { Badge } from "./Badge";
import { DataBadge } from "./DataBadge";
import { displayField, formatDate } from "@/lib/format";
import type { AssetCardModel } from "@/lib/dashboard";
import type { CampoSemantico } from "@/lib/types";

const SNAPSHOT_INDICATORS: Array<{ key: string; label: string; money?: boolean }> = [
  { key: "preco", label: "Preco", money: true },
  { key: "dy", label: "DY" },
  { key: "pvp", label: "P/VP" },
  { key: "vpa", label: "VPA", money: true },
];

function origemLabel(origem: AssetCardModel["origem"]): string {
  if (origem === "ambos") {
    return "Carteira e acompanhamento";
  }
  if (origem === "carteira") {
    return "Carteira";
  }
  return "Acompanhado";
}

function freshnessSummary(asset: AssetCardModel): { state: string; date: string | null } {
  if (asset.freshnessState.kind === "forbidden") {
    return { state: "AUSENTE", date: null };
  }
  if (asset.freshnessState.kind === "error" || asset.freshnessState.kind === "absent") {
    return { state: "AUSENTE", date: null };
  }
  const categorias = asset.freshness?.categorias || {};
  const statuses = Object.values(categorias)
    .map((item) => item?.status)
    .filter((item): item is string => Boolean(item));
  if (statuses.length === 0) {
    return { state: "AUSENTE", date: null };
  }
  if (statuses.includes("MISSING")) {
    return { state: "MISSING", date: asset.freshness?.categorias ? formatDate(Object.values(categorias)[0]?.data_referencia || null) : null };
  }
  if (statuses.includes("STALE")) {
    return { state: "STALE", date: formatDate(Object.values(categorias).find((item) => item?.status === "STALE")?.data_referencia || null) };
  }
  if (statuses.includes("FRESH")) {
    return { state: "FRESH", date: formatDate(Object.values(categorias).find((item) => item?.status === "FRESH")?.data_referencia || null) };
  }
  return { state: statuses[0], date: null };
}

export function AssetCard({ asset }: { asset: AssetCardModel }) {
  const freshness = freshnessSummary(asset);
  const snapshotCampos = (asset.snapshot?.campos || {}) as Record<string, CampoSemantico>;
  const preco = displayField(asset.snapshot?.preco, snapshotCampos.preco, true);
  const quantidade = displayField(asset.posicao?.quantidade ?? null);
  const investido = displayField(asset.posicao?.valor_investido ?? null, null, true);

  return (
    <article className="flex flex-col border border-olive/10 bg-white shadow-card">
      <header className="flex items-start justify-between gap-3 border-b border-olive/10 px-5 py-4">
        <div>
          <p className="text-[11px] uppercase tracking-[0.22em] text-gold">{origemLabel(asset.origem)}</p>
          <h3 className="ticker mt-1 text-2xl text-olive">{asset.ticker || "AUSENTE"}</h3>
          <p className="mt-1 text-sm text-olive/60">{asset.tipo || "tipo AUSENTE"}</p>
        </div>
        <div className="flex flex-col items-end gap-2">
          {asset.tipo ? <Badge tone="olive">{asset.tipo}</Badge> : <DataBadge state="AUSENTE" />}
          <DataBadge state={freshness.state} />
        </div>
      </header>
      <div className="grid gap-4 px-5 py-4 sm:grid-cols-3">
        <div>
          <p className="text-[11px] uppercase tracking-[0.16em] text-olive/45">Preco</p>
          <p className="ticker mt-1 text-xl text-olive">{preco.text}</p>
          <DataBadge state={preco.kind} />
        </div>
        <div>
          <p className="text-[11px] uppercase tracking-[0.16em] text-olive/45">Quantidade</p>
          <p className="ticker mt-1 text-xl text-olive">{asset.posicao ? quantidade.text : "NAO_APLICAVEL"}</p>
          <DataBadge state={asset.posicao ? quantidade.kind : "NAO_APLICAVEL"} />
        </div>
        <div>
          <p className="text-[11px] uppercase tracking-[0.16em] text-olive/45">Investido</p>
          <p className="ticker mt-1 text-xl text-olive">{asset.posicao ? investido.text : "NAO_APLICAVEL"}</p>
          <DataBadge state={asset.posicao ? investido.kind : "NAO_APLICAVEL"} />
        </div>
      </div>
      <div className="border-t border-olive/10 px-5 py-4">
        <p className="text-[11px] uppercase tracking-[0.16em] text-olive/45">Indicadores disponiveis</p>
        <ul className="mt-3 grid gap-3 sm:grid-cols-2">
          {SNAPSHOT_INDICATORS.filter((item) => item.key !== "preco").map((item) => {
            const campo = snapshotCampos[item.key];
            const shown = displayField(asset.snapshot ? asset.snapshot[item.key] : null, campo, item.money);
            return (
              <li key={item.key} className="flex items-center justify-between gap-2">
                <span className="text-sm text-olive/70">{item.label}</span>
                <span className="flex items-center gap-2">
                  <span className="ticker text-sm text-olive">{shown.text}</span>
                  <DataBadge state={shown.kind} />
                </span>
              </li>
            );
          })}
          {asset.indicadores.map((indicador) => {
            const shown = displayField(indicador.valor_atual, {
              semantica: indicador.semantica,
              unidade: indicador.unidade,
              escala: indicador.escala,
              aplicavel: indicador.aplicavel,
            });
            return (
              <li key={`${indicador.id}-${indicador.indicador}`} className="flex items-center justify-between gap-2">
                <span className="text-sm text-olive/70">{indicador.indicador}</span>
                <span className="flex items-center gap-2">
                  <span className="ticker text-sm text-olive">{shown.text}</span>
                  <DataBadge state={shown.kind} />
                </span>
              </li>
            );
          })}
          {!asset.snapshot && asset.indicadores.length === 0 ? (
            <li className="text-sm text-olive/60">Nenhum indicador retornado pela API para este ativo.</li>
          ) : null}
        </ul>
      </div>
      <footer className="mt-auto border-t border-olive/10 px-5 py-3 text-[11px] uppercase tracking-[0.14em] text-olive/45">
        Referencia {formatDate(asset.snapshot?.data_referencia) || "AUSENTE"}
        {freshness.date ? ` · freshness ${freshness.date}` : ""}
      </footer>
    </article>
  );
}
