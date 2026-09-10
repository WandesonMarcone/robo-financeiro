import {
  getAcompanhados,
  getAtivos,
  getCarteira,
  getFreshness,
  getIndicadores,
  getSnapshotMaisRecente,
  getSnapshots,
} from "./api";
import { formatDate } from "./format";
import { itemsOf, loadResource, type ResourceState } from "./resource";
import type {
  Acompanhamento,
  AtivoCatalogo,
  CampoSemantico,
  FreshnessEstado,
  Indicador,
  PaginationMeta,
  PosicaoCarteira,
  SnapshotMercado,
} from "./types";

export type AtivosQuery = {
  ticker?: string;
  tipo?: string;
  page?: number;
  pageSize?: number;
};

export type AtivoListItem = {
  ativo: AtivoCatalogo;
  snapshot: SnapshotMercado | null;
  indicadores: Indicador[];
  naCarteira: boolean;
  acompanhado: boolean;
};

export type AtivosListData = {
  ativos: ResourceState<AtivoCatalogo[]>;
  snapshots: ResourceState<SnapshotMercado[]>;
  indicadores: ResourceState<Indicador[]>;
  carteira: ResourceState<PosicaoCarteira[]>;
  acompanhados: ResourceState<Acompanhamento[]>;
  items: AtivoListItem[];
  meta: PaginationMeta;
};

export type AtivoDetailData = {
  ticker: string;
  ativo: ResourceState<AtivoCatalogo | null>;
  snapshot: ResourceState<SnapshotMercado | null>;
  indicadores: ResourceState<Indicador[]>;
  freshness: ResourceState<FreshnessEstado | null>;
  carteira: ResourceState<PosicaoCarteira[]>;
  acompanhados: ResourceState<Acompanhamento[]>;
  naCarteira: boolean;
  acompanhado: boolean;
  posicao: PosicaoCarteira | null;
};

const LIST_PAGE_SIZE = 20;
const SNAPSHOT_WINDOW = 500;
const OWNERSHIP_PAGE = 500;

const SNAPSHOT_META = new Set([
  "id",
  "ativo_id",
  "ticker",
  "tipo",
  "data_referencia",
  "data_coleta",
  "data_publicacao",
  "fonte",
  "fonte_primaria",
  "fonte_intermediaria",
  "url_origem",
  "campos",
  "proveniencia",
]);

const LIST_INDICATORS = ["preco", "dy", "pvp", "vpa"] as const;

export function normalizeTickerQuery(raw: string): string | undefined {
  const ticker = raw.trim().toUpperCase();
  return ticker.length > 0 ? ticker : undefined;
}

export function normalizeTipoQuery(raw: string): string | undefined {
  const tipo = raw.trim().toUpperCase();
  if (tipo === "ACAO" || tipo === "FII") {
    return tipo;
  }
  return undefined;
}

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

function indicadoresByTicker(indicadores: Indicador[]): Map<string, Indicador[]> {
  const map = new Map<string, Indicador[]>();
  for (const item of indicadores) {
    const ticker = item.ticker ? item.ticker.toUpperCase() : "";
    if (!ticker) {
      continue;
    }
    const list = map.get(ticker) || [];
    list.push(item);
    map.set(ticker, list);
  }
  return map;
}

function tickerSet(items: Array<{ ticker: string | null }>): Set<string> {
  const set = new Set<string>();
  for (const item of items) {
    if (item.ticker) {
      set.add(item.ticker.toUpperCase());
    }
  }
  return set;
}

export function snapshotFieldKeys(snapshot: SnapshotMercado | null): string[] {
  if (!snapshot) {
    return [];
  }
  const campos = snapshot.campos;
  const keys = campos ? Object.keys(campos) : [];
  const extra = Object.keys(snapshot).filter((key) => !SNAPSHOT_META.has(key) && !keys.includes(key));
  return [...keys, ...extra];
}

export function listIndicatorKeys(): readonly string[] {
  return LIST_INDICATORS;
}

export function campoDoSnapshot(snapshot: SnapshotMercado | null, key: string): CampoSemantico | null {
  if (!snapshot?.campos) {
    return null;
  }
  return snapshot.campos[key] || null;
}

export function isMoneySnapshotField(key: string, campo?: CampoSemantico | null): boolean {
  if (campo?.escala === "monetario" || campo?.unidade === "R$") {
    return true;
  }
  return key === "preco" || key === "vpa" || key === "liquidez" || key === "lucro_12m" || key === "dividendo_mensal" || key === "valor_mercado" || key === "lpa";
}

export function freshnessSummary(state: ResourceState<FreshnessEstado | null>): {
  state: string;
  date: string | null;
} {
  if (state.kind !== "ok" || !state.data) {
    return { state: "AUSENTE", date: null };
  }
  const categorias = state.data.categorias || {};
  const values = Object.values(categorias);
  const statuses = values.map((item) => item?.status).filter((item): item is string => Boolean(item));
  if (statuses.length === 0) {
    return { state: "AUSENTE", date: null };
  }
  const pick = (status: string) =>
    formatDate(values.find((item) => item?.status === status)?.data_referencia || values[0]?.data_referencia || null);
  if (statuses.includes("MISSING")) {
    return { state: "MISSING", date: pick("MISSING") };
  }
  if (statuses.includes("STALE")) {
    return { state: "STALE", date: pick("STALE") };
  }
  if (statuses.includes("FRESH")) {
    return { state: "FRESH", date: pick("FRESH") };
  }
  return { state: statuses[0], date: pick(statuses[0]) };
}

export async function loadAtivosList(query: AtivosQuery = {}): Promise<AtivosListData> {
  const ticker = query.ticker ? normalizeTickerQuery(query.ticker) : undefined;
  const tipo = query.tipo ? normalizeTipoQuery(query.tipo) : undefined;
  const page = query.page && query.page > 0 ? query.page : 1;
  const pageSize = query.pageSize && query.pageSize > 0 ? query.pageSize : LIST_PAGE_SIZE;

  const [ativosList, carteiraList, acompanhadosList] = await Promise.all([
    loadResource(() => getAtivos({ ticker, tipo, page, page_size: pageSize })),
    loadResource(() => getCarteira(OWNERSHIP_PAGE)),
    loadResource(() => getAcompanhados(OWNERSHIP_PAGE)),
  ]);

  const ativos: ResourceState<AtivoCatalogo[]> =
    ativosList.kind === "ok" ? { kind: "ok", data: ativosList.data.items, meta: ativosList.data.meta } : ativosList;
  const carteira: ResourceState<PosicaoCarteira[]> =
    carteiraList.kind === "ok"
      ? { kind: "ok", data: carteiraList.data.items, meta: carteiraList.data.meta }
      : carteiraList;
  const acompanhados: ResourceState<Acompanhamento[]> =
    acompanhadosList.kind === "ok"
      ? { kind: "ok", data: acompanhadosList.data.items, meta: acompanhadosList.data.meta }
      : acompanhadosList;

  const listed = itemsOf(ativos);
  const precisaMercado = listed.length > 0 && ativos.kind === "ok";

  const [snapshotsList, indicadoresList] = precisaMercado
    ? await Promise.all([
        loadResource(() => getSnapshots(SNAPSHOT_WINDOW, ticker ? { ticker } : undefined)),
        ticker
          ? loadResource(() => getIndicadores(SNAPSHOT_WINDOW, { ticker }))
          : Promise.resolve({ kind: "absent" as const, message: "Indicadores no detalhe do ativo." }),
      ])
    : [
        { kind: "absent" as const, message: "Sem ativos na pagina para cruzar snapshots." },
        { kind: "absent" as const, message: "Sem ativos na pagina para cruzar indicadores." },
      ];

  const snapshots: ResourceState<SnapshotMercado[]> =
    snapshotsList.kind === "ok"
      ? { kind: "ok", data: snapshotsList.data.items, meta: snapshotsList.data.meta }
      : snapshotsList;
  const indicadores: ResourceState<Indicador[]> =
    indicadoresList.kind === "ok"
      ? { kind: "ok", data: indicadoresList.data.items, meta: indicadoresList.data.meta }
      : indicadoresList;

  const snaps = snapshotByTicker(itemsOf(snapshots));
  const inds = indicadoresByTicker(itemsOf(indicadores));
  const owned = tickerSet(itemsOf(carteira));
  const watched = tickerSet(itemsOf(acompanhados));

  const items: AtivoListItem[] = listed.map((ativo) => {
    const key = ativo.ticker ? ativo.ticker.toUpperCase() : "";
    return {
      ativo,
      snapshot: key ? snaps.get(key) || null : null,
      indicadores: key ? inds.get(key) || [] : [],
      naCarteira: key ? owned.has(key) : false,
      acompanhado: key ? watched.has(key) : false,
    };
  });

  return {
    ativos,
    snapshots,
    indicadores,
    carteira,
    acompanhados,
    items,
    meta: ativos.kind === "ok" ? ativos.meta || {} : {},
  };
}

export async function loadAtivoDetalhe(tickerRaw: string): Promise<AtivoDetailData> {
  const ticker = normalizeTickerQuery(tickerRaw) || "";
  if (!ticker) {
    return {
      ticker,
      ativo: { kind: "absent", message: "Ticker ausente." },
      snapshot: { kind: "absent" },
      indicadores: { kind: "absent" },
      freshness: { kind: "absent" },
      carteira: { kind: "absent" },
      acompanhados: { kind: "absent" },
      naCarteira: false,
      acompanhado: false,
      posicao: null,
    };
  }

  const [ativosList, snapshotState, indicadoresList, freshness, carteiraList, acompanhadosList] = await Promise.all([
    loadResource(() => getAtivos({ ticker, page: 1, page_size: 1 })),
    loadResource(() => getSnapshotMaisRecente(ticker)),
    loadResource(() => getIndicadores(SNAPSHOT_WINDOW, { ticker })),
    loadResource(() => getFreshness(ticker)),
    loadResource(() => getCarteira(OWNERSHIP_PAGE)),
    loadResource(() => getAcompanhados(OWNERSHIP_PAGE)),
  ]);

  let ativo: ResourceState<AtivoCatalogo | null>;
  if (ativosList.kind === "ok") {
    const found = ativosList.data.items[0] || null;
    ativo = found
      ? { kind: "ok", data: found, meta: ativosList.data.meta }
      : { kind: "absent", message: "Ativo inexistente." };
  } else {
    ativo = ativosList;
  }

  const indicadores: ResourceState<Indicador[]> =
    indicadoresList.kind === "ok"
      ? { kind: "ok", data: indicadoresList.data.items, meta: indicadoresList.data.meta }
      : indicadoresList;
  const carteira: ResourceState<PosicaoCarteira[]> =
    carteiraList.kind === "ok"
      ? { kind: "ok", data: carteiraList.data.items, meta: carteiraList.data.meta }
      : carteiraList;
  const acompanhados: ResourceState<Acompanhamento[]> =
    acompanhadosList.kind === "ok"
      ? { kind: "ok", data: acompanhadosList.data.items, meta: acompanhadosList.data.meta }
      : acompanhadosList;

  const ownedItems = itemsOf(carteira);
  const watchedItems = itemsOf(acompanhados);
  const posicao = ownedItems.find((item) => item.ticker && item.ticker.toUpperCase() === ticker) || null;
  const naCarteira = Boolean(posicao);
  const acompanhado = watchedItems.some((item) => item.ticker && item.ticker.toUpperCase() === ticker);

  return {
    ticker,
    ativo,
    snapshot: snapshotState,
    indicadores,
    freshness,
    carteira,
    acompanhados,
    naCarteira,
    acompanhado,
    posicao,
  };
}
