import { getCarteira, getFreshness, getSnapshots } from "./api";
import { countFromList, uniqueTickers } from "./dashboard";
import { freshnessSummary } from "./ativos";
import { itemsOf, loadResource, type ResourceState } from "./resource";
import type { FreshnessEstado, PaginationMeta, PosicaoCarteira, SnapshotMercado } from "./types";

export type CarteiraPosicaoItem = {
  posicao: PosicaoCarteira;
  snapshot: SnapshotMercado | null;
  freshness: ResourceState<FreshnessEstado | null>;
};

export type CarteiraData = {
  carteira: ResourceState<PosicaoCarteira[]>;
  snapshots: ResourceState<SnapshotMercado[]>;
  items: CarteiraPosicaoItem[];
  meta: PaginationMeta;
};

const PAGE = 500;
const FRESHNESS_CAP = 12;

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

export function countPosicoes(state: ResourceState<PosicaoCarteira[]>): number | null {
  return countFromList(state, state.kind === "ok" ? state.meta : undefined);
}

export function countAtivosDistintos(posicoes: PosicaoCarteira[]): number {
  return uniqueTickers(posicoes).length;
}

export function latestTimestamp(values: Array<string | null | undefined>): string | null {
  let latest: string | null = null;
  let latestMs = Number.NEGATIVE_INFINITY;
  for (const value of values) {
    if (!value) {
      continue;
    }
    const ms = new Date(value).getTime();
    if (Number.isNaN(ms)) {
      if (!latest) {
        latest = value;
      }
      continue;
    }
    if (ms > latestMs) {
      latestMs = ms;
      latest = value;
    }
  }
  return latest;
}

export async function loadCarteira(): Promise<CarteiraData> {
  const carteiraList = await loadResource(() => getCarteira(PAGE));
  const carteira: ResourceState<PosicaoCarteira[]> =
    carteiraList.kind === "ok"
      ? { kind: "ok", data: carteiraList.data.items, meta: carteiraList.data.meta }
      : carteiraList;

  const posicoes = itemsOf(carteira);
  const tickers = uniqueTickers(posicoes);
  const precisaMercado = tickers.length > 0 && carteira.kind === "ok";

  const snapshotsList = precisaMercado
    ? await loadResource(() => getSnapshots(PAGE))
    : { kind: "absent" as const, message: "Sem posicoes para cruzar snapshots." };

  const snapshots: ResourceState<SnapshotMercado[]> =
    snapshotsList.kind === "ok"
      ? { kind: "ok", data: snapshotsList.data.items, meta: snapshotsList.data.meta }
      : snapshotsList;

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

  const snaps = snapshotByTicker(itemsOf(snapshots));
  const items: CarteiraPosicaoItem[] = posicoes.map((posicao) => {
    const ticker = posicao.ticker ? posicao.ticker.toUpperCase() : "";
    return {
      posicao,
      snapshot: ticker ? snaps.get(ticker) || null : null,
      freshness: ticker ? freshnessByTicker.get(ticker) || { kind: "absent" } : { kind: "absent" },
    };
  });

  return {
    carteira,
    snapshots,
    items,
    meta: carteira.kind === "ok" ? carteira.meta || {} : {},
  };
}

export { freshnessSummary };
