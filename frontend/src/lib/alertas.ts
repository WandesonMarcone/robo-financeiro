import { getAlertas, getNotificacoes, getPreferencias } from "./api";
import { notificacaoPrioridade } from "./dashboard";
import { itemsOf, loadResource, type ResourceState } from "./resource";
import type { AlertaEvento, Notificacao, PaginationMeta, Preferencias } from "./types";

export type AlertasData = {
  notificacoes: ResourceState<Notificacao[]>;
  naoLidas: ResourceState<number>;
  alertas: ResourceState<AlertaEvento[]>;
  preferencias: ResourceState<Preferencias>;
};

const PAGE = 100;

export function notificacaoLida(item: Notificacao): boolean {
  return Boolean(item.lida_em);
}

export function textoOuNulo(valor: unknown): string | null {
  if (valor === null || valor === undefined || valor === "") {
    return null;
  }
  return String(valor);
}

function campoEmDados(item: Notificacao, chave: string): string | null {
  const dados = item.dados;
  if (!dados || typeof dados !== "object") {
    return null;
  }
  return textoOuNulo((dados as Record<string, unknown>)[chave]);
}

export function freshnessDaNotificacao(item: Notificacao): string | null {
  return campoEmDados(item, "freshness") || campoEmDados(item, "status_freshness");
}

export function indicadorDaNotificacao(item: Notificacao): string | null {
  return campoEmDados(item, "indicador") || campoEmDados(item, "evento") || item.tipo;
}

export function origemDaNotificacao(item: Notificacao): string | null {
  return item.canal || campoEmDados(item, "origem");
}

export function prioridadeExibida(item: Notificacao): string | null {
  return notificacaoPrioridade(item);
}

export function alertaCritico(alerta: AlertaEvento): boolean {
  const tipo = (alerta.tipo_alerta || "").toUpperCase();
  const severidade = (alerta.severidade || "").toUpperCase();
  return tipo === "CRITICO" || severidade === "CRITICO" || severidade === "ERRO";
}

export function notificacaoCritica(item: Notificacao): boolean {
  const prioridade = (prioridadeExibida(item) || "").toUpperCase();
  const tipo = (item.tipo || "").toUpperCase();
  return prioridade === "CRITICO" || prioridade === "ALTA" || prioridade === "ALTO" || tipo.includes("CRITICO");
}

export async function loadAlertas(): Promise<AlertasData> {
  const [notificacoesList, naoLidasList, alertasList, preferencias] = await Promise.all([
    loadResource(() => getNotificacoes({ page_size: PAGE })),
    loadResource(() => getNotificacoes({ nao_lidas: true, page_size: 1 })),
    loadResource(() => getAlertas(PAGE)),
    loadResource(() => getPreferencias()),
  ]);

  const notificacoes: ResourceState<Notificacao[]> =
    notificacoesList.kind === "ok"
      ? { kind: "ok", data: notificacoesList.data.items, meta: notificacoesList.data.meta }
      : notificacoesList;
  const naoLidas: ResourceState<number> =
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

  return { notificacoes, naoLidas, alertas, preferencias };
}

export function itensDe<T>(state: ResourceState<T[]>): T[] {
  return itemsOf(state);
}

export function metaDe(state: ResourceState<unknown>): PaginationMeta {
  return state.kind === "ok" ? state.meta || {} : {};
}
