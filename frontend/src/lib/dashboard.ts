import {
  getAlertas,
  getAcompanhados,
  getCarteira,
  getFreshness,
  getIndicadores,
  getMePlano,
  getNotificacoes,
  getPreferencias,
  getSnapshots,
} from "./api";
import { itemsOf, loadResource, type ResourceState } from "./resource";
import type {
  Acompanhamento,
  AlertaEvento,
  FreshnessEstado,
  Indicador,
  Notificacao,
  PaginationMeta,
  PlanoResumo,
  PosicaoCarteira,
  Preferencias,
  SnapshotMercado,
} from "./types";

export type { ResourceOk, ResourceState } from "./resource";

export type AssetCardModel = {
  key: string;
  ativoId: number | null;
  ticker: string | null;
  tipo: string | null;
  origem: "carteira" | "acompanhado" | "ambos";
  posicao: PosicaoCarteira | null;
  acompanhamento: Acompanhamento | null;
  snapshot: SnapshotMercado | null;
  indicadores: Indicador[];
  freshness: FreshnessEstado | null;
  freshnessState: ResourceState<FreshnessEstado | null>;
};

export type DashboardData = {
  plano: ResourceState<PlanoResumo>;
  carteira: ResourceState<PosicaoCarteira[]>;
  acompanhados: ResourceState<Acompanhamento[]>;
  notificacoes: ResourceState<Notificacao[]>;
  notificacoesNaoLidas: ResourceState<number>;
  alertas: ResourceState<AlertaEvento[]>;
  preferencias: ResourceState<Preferencias>;
  snapshots: ResourceState<SnapshotMercado[]>;
  indicadores: ResourceState<Indicador[]>;
  assets: AssetCardModel[];
};

const PAGE = 500;
const ALERT_PAGE = 20;
const FRESHNESS_CAP = 12;
const INDICADORES_POR_CARD = 4;

function snapshotByTicker(snapshots: SnapshotMercado[]): Map<string, SnapshotMercado> {
  const map = new Map<string, SnapshotMercado>();
  for (const snap of snapshots) {
    const ticker = snap.ticker ? String(snap.ticker).toUpperCase() : "";
    if (!ticker || map.has(ticker)) {
      continue;
    }
    map.set(ticker, snap);
  }
  return map;
}

function indicadoresByAtivo(indicadores: Indicador[]): Map<string, Indicador[]> {
  const map = new Map<string, Indicador[]>();
  for (const item of indicadores) {
    const key = item.ativo_id ? `id:${item.ativo_id}` : item.ticker ? `t:${item.ticker.toUpperCase()}` : "";
    if (!key) {
      continue;
    }
    const list = map.get(key) || [];
    list.push(item);
    map.set(key, list);
  }
  return map;
}

function mergeAssets(
  carteira: PosicaoCarteira[],
  acompanhados: Acompanhamento[],
  snapshots: SnapshotMercado[],
  indicadores: Indicador[],
  freshnessByTicker: Map<string, ResourceState<FreshnessEstado | null>>,
): AssetCardModel[] {
  const byKey = new Map<string, AssetCardModel>();
  const snaps = snapshotByTicker(snapshots);
  const inds = indicadoresByAtivo(indicadores);

  const put = (ativoId: number | null, ticker: string | null, tipo: string | null) => {
    const key = ativoId ? `id:${ativoId}` : ticker ? `t:${ticker.toUpperCase()}` : `x:${byKey.size}`;
    const existing = byKey.get(key);
    if (existing) {
      return existing;
    }
    const tickerKey = ticker ? ticker.toUpperCase() : "";
    const indKey = ativoId ? `id:${ativoId}` : tickerKey ? `t:${tickerKey}` : "";
    const freshness = tickerKey ? freshnessByTicker.get(tickerKey) : undefined;
    const model: AssetCardModel = {
      key,
      ativoId,
      ticker,
      tipo,
      origem: "acompanhado",
      posicao: null,
      acompanhamento: null,
      snapshot: tickerKey ? snaps.get(tickerKey) || null : null,
      indicadores: (indKey ? inds.get(indKey) || [] : []).slice(0, INDICADORES_POR_CARD),
      freshness: freshness?.kind === "ok" ? freshness.data : null,
      freshnessState: freshness || { kind: "absent" },
    };
    byKey.set(key, model);
    return model;
  };

  for (const posicao of carteira) {
    const model = put(posicao.ativo_id, posicao.ticker, posicao.tipo);
    model.posicao = posicao;
    model.origem = "carteira";
    if (!model.tipo) {
      model.tipo = posicao.tipo;
    }
    if (!model.ticker) {
      model.ticker = posicao.ticker;
    }
  }
  for (const item of acompanhados) {
    const model = put(item.ativo_id, item.ticker, item.tipo);
    model.acompanhamento = item;
    if (model.posicao) {
      model.origem = "ambos";
    } else {
      model.origem = "acompanhado";
    }
    if (!model.tipo) {
      model.tipo = item.tipo;
    }
    if (!model.ticker) {
      model.ticker = item.ticker;
    }
  }
  return Array.from(byKey.values());
}

export function countFromList<T>(state: ResourceState<T[]>, meta?: PaginationMeta): number | null {
  if (state.kind !== "ok") {
    return null;
  }
  if (typeof state.meta?.total === "number") {
    return state.meta.total;
  }
  if (typeof meta?.total === "number") {
    return meta.total;
  }
  return state.data.length;
}

export function uniqueTickers(assets: Array<{ ticker: string | null }>): string[] {
  const seen = new Set<string>();
  const list: string[] = [];
  for (const asset of assets) {
    const ticker = asset.ticker ? asset.ticker.toUpperCase() : "";
    if (!ticker || seen.has(ticker)) {
      continue;
    }
    seen.add(ticker);
    list.push(ticker);
  }
  return list;
}

export async function loadDashboard(): Promise<DashboardData> {
  const [
    plano,
    carteiraList,
    acompanhadosList,
    notificacoesList,
    naoLidasList,
    alertasList,
    preferencias,
  ] = await Promise.all([
    loadResource(() => getMePlano()),
    loadResource(() => getCarteira(PAGE)),
    loadResource(() => getAcompanhados(PAGE)),
    loadResource(() => getNotificacoes({ page_size: ALERT_PAGE })),
    loadResource(() => getNotificacoes({ nao_lidas: true, page_size: 1 })),
    loadResource(() => getAlertas(ALERT_PAGE)),
    loadResource(() => getPreferencias()),
  ]);

  const carteira: ResourceState<PosicaoCarteira[]> =
    carteiraList.kind === "ok"
      ? { kind: "ok", data: carteiraList.data.items, meta: carteiraList.data.meta }
      : carteiraList;
  const acompanhados: ResourceState<Acompanhamento[]> =
    acompanhadosList.kind === "ok"
      ? { kind: "ok", data: acompanhadosList.data.items, meta: acompanhadosList.data.meta }
      : acompanhadosList;
  const notificacoes: ResourceState<Notificacao[]> =
    notificacoesList.kind === "ok"
      ? { kind: "ok", data: notificacoesList.data.items, meta: notificacoesList.data.meta }
      : notificacoesList;
  const notificacoesNaoLidas: ResourceState<number> =
    naoLidasList.kind === "ok"
      ? {
          kind: "ok",
          data:
            typeof naoLidasList.data.meta.total === "number"
              ? naoLidasList.data.meta.total
              : naoLidasList.data.items.length,
          meta: naoLidasList.data.meta,
        }
      : naoLidasList;
  const alertas: ResourceState<AlertaEvento[]> =
    alertasList.kind === "ok"
      ? { kind: "ok", data: alertasList.data.items, meta: alertasList.data.meta }
      : alertasList;

  const draftAssets = mergeAssets(itemsOf(carteira), itemsOf(acompanhados), [], [], new Map());
  const tickers = uniqueTickers(draftAssets);
  const precisaMercado = tickers.length > 0;

  const [snapshotsList, indicadoresList] = precisaMercado
    ? await Promise.all([
        loadResource(() => getSnapshots(PAGE)),
        loadResource(() => getIndicadores(PAGE)),
      ])
    : [
        { kind: "absent" as const, message: "Sem ativos do usuario para cruzar snapshots." },
        { kind: "absent" as const, message: "Sem ativos do usuario para cruzar indicadores." },
      ];

  const snapshots: ResourceState<SnapshotMercado[]> =
    snapshotsList.kind === "ok"
      ? { kind: "ok", data: snapshotsList.data.items, meta: snapshotsList.data.meta }
      : snapshotsList;
  const indicadores: ResourceState<Indicador[]> =
    indicadoresList.kind === "ok"
      ? { kind: "ok", data: indicadoresList.data.items, meta: indicadoresList.data.meta }
      : indicadoresList;

  const freshnessByTicker = new Map<string, ResourceState<FreshnessEstado | null>>();
  if (precisaMercado) {
    const capped = tickers.slice(0, FRESHNESS_CAP);
    const results = await Promise.all(
      capped.map(async (ticker) => {
        const state = await loadResource(() => getFreshness(ticker));
        return [ticker, state] as const;
      }),
    );
    for (const [ticker, state] of results) {
      freshnessByTicker.set(ticker, state);
    }
  }

  const assets = mergeAssets(
    itemsOf(carteira),
    itemsOf(acompanhados),
    itemsOf(snapshots),
    itemsOf(indicadores),
    freshnessByTicker,
  );

  return {
    plano,
    carteira,
    acompanhados,
    notificacoes,
    notificacoesNaoLidas,
    alertas,
    preferencias,
    snapshots,
    indicadores,
    assets,
  };
}

export function filterAlertasDoUsuario(
  alertas: AlertaEvento[],
  tickers: string[],
): AlertaEvento[] {
  if (tickers.length === 0) {
    return [];
  }
  const set = new Set(tickers);
  return alertas.filter((alerta) => alerta.ticker && set.has(alerta.ticker.toUpperCase()));
}

export function notificacaoPrioridade(item: Notificacao): string | null {
  const dados = item.dados;
  if (!dados || typeof dados !== "object") {
    return null;
  }
  const valor = dados.prioridade;
  if (valor === null || valor === undefined || valor === "") {
    return null;
  }
  return String(valor);
}
