import {
  SESSION_HEADER,
  clearSessionToken,
  getSessionToken,
  markSessionExpired,
  tokenNeverInUrl,
} from "./session";
import type {
  Acompanhamento,
  AlertaEvento,
  AtivoCatalogo,
  FreshnessEstado,
  Indicador,
  LoginPayload,
  Notificacao,
  PaginationMeta,
  PlanoResumo,
  PosicaoCarteira,
  Preferencias,
  SnapshotMercado,
  Usuario,
} from "./types";

export type ApiEnvelope<T> = {
  status: "success" | "error";
  data: T | null;
  meta: Record<string, unknown> | null;
};

export class ApiError extends Error {
  statusCode: number;
  envelope: ApiEnvelope<null> | null;

  constructor(message: string, statusCode: number, envelope: ApiEnvelope<null> | null = null) {
    super(message);
    this.name = "ApiError";
    this.statusCode = statusCode;
    this.envelope = envelope;
  }
}

export type ApiFetchOptions = {
  skipAuth?: boolean;
  token?: string | null;
};

type AuthFailureHandler = (error: ApiError) => void;

let authFailureHandler: AuthFailureHandler | null = null;

export function setAuthFailureHandler(handler: AuthFailureHandler | null): void {
  authFailureHandler = handler;
}

export function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.statusCode === 401;
}

export function isForbidden(error: unknown): boolean {
  return error instanceof ApiError && error.statusCode === 403;
}

function apiBase(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL || "/api/v1";
}

export function buildApiUrl(path: string, query?: Record<string, string | number | boolean | undefined>): string {
  const base = apiBase().replace(/\/$/, "");
  const clean = path.startsWith("/") ? path : `/${path}`;
  const url = new URL(`${base}${clean}`, "http://local.invalid");
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null || value === "") {
        continue;
      }
      url.searchParams.set(key, String(value));
    }
  }
  const composed = `${url.pathname}${url.search}`;
  if (!tokenNeverInUrl(composed)) {
    throw new Error("Token nao pode ir na URL");
  }
  return composed;
}

function errorMessage(envelope: ApiEnvelope<unknown> | null, status: number): string {
  if (envelope?.meta && typeof envelope.meta.error === "string" && envelope.meta.error) {
    return envelope.meta.error;
  }
  return `HTTP ${status}`;
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
  query?: Record<string, string | number | boolean | undefined>,
  options: ApiFetchOptions = {},
): Promise<ApiEnvelope<T>> {
  const url = buildApiUrl(path, query);
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const token = options.skipAuth ? null : (options.token ?? getSessionToken());
  if (token) {
    headers.set(SESSION_HEADER, token);
  }

  const response = await fetch(url, { ...init, headers });
  let envelope: ApiEnvelope<T> | null = null;
  try {
    envelope = (await response.json()) as ApiEnvelope<T>;
  } catch {
    envelope = null;
  }

  if (!response.ok) {
    const error = new ApiError(
      errorMessage(envelope, response.status),
      response.status,
      envelope as ApiEnvelope<null> | null,
    );
    if (token && response.status === 401) {
      clearSessionToken();
      markSessionExpired();
    }
    if (token && (response.status === 401 || response.status === 403)) {
      authFailureHandler?.(error);
    }
    throw error;
  }
  if (!envelope) {
    throw new ApiError("Resposta invalida", response.status);
  }
  return envelope;
}

export async function loginRequest(email: string, senha: string): Promise<LoginPayload> {
  const envelope = await apiFetch<LoginPayload>(
    "/auth/login",
    { method: "POST", body: JSON.stringify({ email, senha }) },
    undefined,
    { skipAuth: true },
  );
  if (!envelope.data?.token || !envelope.data.usuario) {
    throw new ApiError("Resposta de login invalida", 500, null);
  }
  return envelope.data;
}

export async function logoutRequest(): Promise<void> {
  await apiFetch<{ logout: boolean }>("/auth/logout", { method: "POST" });
}

export async function meRequest(): Promise<Usuario> {
  const envelope = await apiFetch<Usuario>("/me");
  if (!envelope.data) {
    throw new ApiError("Resposta de sessao invalida", 500, null);
  }
  return envelope.data;
}

export type ListResult<T> = {
  items: T[];
  meta: PaginationMeta;
};

function asList<T>(data: T[] | null): T[] {
  return Array.isArray(data) ? data : [];
}

function asMeta(meta: Record<string, unknown> | null): PaginationMeta {
  if (!meta) {
    return {};
  }
  return meta as PaginationMeta;
}

export async function getMePlano(): Promise<PlanoResumo> {
  const envelope = await apiFetch<PlanoResumo>("/me/plano");
  if (!envelope.data) {
    throw new ApiError("Resposta de plano invalida", 500, null);
  }
  return envelope.data;
}

export async function getAtivos(query?: {
  ticker?: string;
  tipo?: string;
  page?: number;
  page_size?: number;
}): Promise<ListResult<AtivoCatalogo>> {
  const envelope = await apiFetch<AtivoCatalogo[]>(
    "/ativos",
    {},
    {
      ticker: query?.ticker,
      tipo: query?.tipo,
      page: query?.page ?? 1,
      page_size: query?.page_size ?? 100,
    },
  );
  return { items: asList(envelope.data), meta: asMeta(envelope.meta) };
}

export async function getCarteira(pageSize = 100): Promise<ListResult<PosicaoCarteira>> {
  const envelope = await apiFetch<PosicaoCarteira[]>("/carteira", {}, { page: 1, page_size: pageSize });
  return { items: asList(envelope.data), meta: asMeta(envelope.meta) };
}

export async function getAcompanhados(pageSize = 100): Promise<ListResult<Acompanhamento>> {
  const envelope = await apiFetch<Acompanhamento[]>(
    "/ativos-acompanhados",
    {},
    { page: 1, page_size: pageSize },
  );
  return { items: asList(envelope.data), meta: asMeta(envelope.meta) };
}

export async function getNotificacoes(query?: {
  nao_lidas?: boolean;
  page_size?: number;
}): Promise<ListResult<Notificacao>> {
  const envelope = await apiFetch<Notificacao[]>(
    "/notificacoes",
    {},
    {
      page: 1,
      page_size: query?.page_size ?? 20,
      nao_lidas: query?.nao_lidas ? "true" : undefined,
    },
  );
  return { items: asList(envelope.data), meta: asMeta(envelope.meta) };
}

export async function getAlertas(pageSize = 20): Promise<ListResult<AlertaEvento>> {
  const envelope = await apiFetch<AlertaEvento[]>("/alertas", {}, { page: 1, page_size: pageSize });
  return { items: asList(envelope.data), meta: asMeta(envelope.meta) };
}

export async function getPreferencias(): Promise<Preferencias> {
  const envelope = await apiFetch<Preferencias>("/preferencias");
  if (!envelope.data) {
    throw new ApiError("Resposta de preferencias invalida", 500, null);
  }
  return envelope.data;
}

export async function getSnapshots(
  pageSize = 100,
  query?: { ticker?: string; tipo_ativo?: string },
): Promise<ListResult<SnapshotMercado>> {
  const envelope = await apiFetch<SnapshotMercado[]>(
    "/mercado/snapshots",
    {},
    { page: 1, page_size: pageSize, ticker: query?.ticker, tipo_ativo: query?.tipo_ativo },
  );
  return { items: asList(envelope.data), meta: asMeta(envelope.meta) };
}

export async function getSnapshotMaisRecente(ticker: string): Promise<SnapshotMercado | null> {
  const envelope = await apiFetch<SnapshotMercado>("/mercado/snapshots/mais-recente", {}, { ticker });
  return envelope.data;
}

export async function getIndicadores(
  pageSize = 100,
  query?: { ticker?: string; ativo_id?: number; tipo_ativo?: string },
): Promise<ListResult<Indicador>> {
  const envelope = await apiFetch<Indicador[]>(
    "/indicadores",
    {},
    {
      page: 1,
      page_size: pageSize,
      ticker: query?.ticker,
      ativo_id: query?.ativo_id,
      tipo_ativo: query?.tipo_ativo,
    },
  );
  return { items: asList(envelope.data), meta: asMeta(envelope.meta) };
}

export async function getFreshness(ticker: string): Promise<FreshnessEstado | null> {
  const envelope = await apiFetch<FreshnessEstado>("/mercado/freshness", {}, { ticker });
  return envelope.data;
}
