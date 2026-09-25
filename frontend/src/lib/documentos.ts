import { getDocumentos } from "./api";
import { loadResource, type ResourceState } from "./resource";
import type { Documento, PaginationMeta } from "./types";

export type DocumentosQuery = {
  ticker?: string;
  tipo_documento?: string;
  status?: string;
  page?: number;
  pageSize?: number;
};

export type DocumentosData = {
  documentos: ResourceState<Documento[]>;
  items: Documento[];
  meta: PaginationMeta;
};

const PAGE_SIZE = 20;

export function normalizeTickerQuery(raw: string): string | undefined {
  const ticker = raw.trim().toUpperCase();
  return ticker.length > 0 ? ticker : undefined;
}

export function normalizeTextoQuery(raw: string): string | undefined {
  const texto = raw.trim();
  return texto.length > 0 ? texto : undefined;
}

export function normalizeStatusQuery(raw: string): string | undefined {
  const status = raw.trim().toUpperCase();
  return status.length > 0 ? status : undefined;
}

export function urlPdfValida(valor: string | null | undefined): string | null {
  if (!valor) {
    return null;
  }
  const url = valor.trim();
  if (!url) {
    return null;
  }
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return null;
    }
    return url;
  } catch {
    return null;
  }
}

export async function loadDocumentos(query: DocumentosQuery = {}): Promise<DocumentosData> {
  const page = query.page ?? 1;
  const pageSize = query.pageSize ?? PAGE_SIZE;
  const documentos = await loadResource(() =>
    getDocumentos({
      ticker: query.ticker,
      tipo_documento: query.tipo_documento,
      status: query.status,
      page,
      page_size: pageSize,
    }),
  );

  if (documentos.kind === "ok") {
    return {
      documentos: { kind: "ok", data: documentos.data.items, meta: documentos.data.meta },
      items: documentos.data.items,
      meta: documentos.data.meta,
    };
  }

  return { documentos, items: [], meta: {} };
}
