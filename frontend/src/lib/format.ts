import type { CampoSemantico } from "./types";

export type DisplayKind =
  | "PRESENTE"
  | "ZERO"
  | "AUSENTE"
  | "NAO_APLICAVEL"
  | "INVALIDO"
  | "FRESH"
  | "STALE"
  | "MISSING";

export type DisplayValue = {
  kind: DisplayKind | string;
  text: string;
  raw: unknown;
};

const KNOWN_STATES = new Set([
  "PRESENTE",
  "ZERO",
  "AUSENTE",
  "NAO_APLICAVEL",
  "INVALIDO",
  "FRESH",
  "STALE",
  "MISSING",
]);

function isNullish(value: unknown): boolean {
  return value === null || value === undefined || value === "";
}

export function classifyValue(value: unknown, campo?: CampoSemantico | null): string {
  const semantica = campo?.semantica ? String(campo.semantica).toUpperCase() : null;
  if (semantica && KNOWN_STATES.has(semantica)) {
    return semantica;
  }
  if (campo?.aplicavel === false) {
    return "NAO_APLICAVEL";
  }
  if (isNullish(value)) {
    return "AUSENTE";
  }
  if (typeof value === "number" && value === 0) {
    return "ZERO";
  }
  return "PRESENTE";
}

export function formatNumber(value: unknown): string | null {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return null;
  }
  return new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 4 }).format(value);
}

export function formatMoney(value: unknown): string | null {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return null;
  }
  return new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: "BRL",
  }).format(value);
}

export function displayField(
  value: unknown,
  campo?: CampoSemantico | null,
  asMoney = false,
): DisplayValue {
  const kind = classifyValue(value, campo);
  if (kind === "AUSENTE" || kind === "NAO_APLICAVEL" || kind === "INVALIDO") {
    return { kind, text: kind, raw: value };
  }
  const formatted = asMoney ? formatMoney(value) : formatNumber(value);
  if (formatted === null) {
    if (typeof value === "string" && value.trim()) {
      return { kind, text: value, raw: value };
    }
    return { kind: kind === "PRESENTE" ? "AUSENTE" : kind, text: kind === "PRESENTE" ? "AUSENTE" : kind, raw: value };
  }
  const unidade = campo?.unidade;
  const text = unidade && !asMoney ? `${formatted} ${unidade}` : formatted;
  return { kind, text, raw: value };
}

export function displayCount(value: number | null): DisplayValue {
  if (value === null) {
    return { kind: "AUSENTE", text: "AUSENTE", raw: null };
  }
  if (value === 0) {
    return { kind: "ZERO", text: "0", raw: 0 };
  }
  return { kind: "PRESENTE", text: String(value), raw: value };
}

export function sumPresent(values: Array<number | null | undefined>): {
  total: number | null;
  used: number;
  skipped: number;
} {
  let total = 0;
  let used = 0;
  let skipped = 0;
  for (const value of values) {
    if (typeof value === "number" && !Number.isNaN(value)) {
      total += value;
      used += 1;
    } else {
      skipped += 1;
    }
  }
  if (used === 0) {
    return { total: null, used, skipped };
  }
  return { total, used, skipped };
}

export function formatDate(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: value.includes("T") ? "short" : undefined,
  }).format(date);
}
