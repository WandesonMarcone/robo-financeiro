import { describe, expect, it } from "vitest";
import {
  freshnessSummary,
  isMoneySnapshotField,
  normalizeTickerQuery,
  normalizeTipoQuery,
  snapshotFieldKeys,
} from "./ativos";
import type { FreshnessEstado, SnapshotMercado } from "./types";

describe("contrato de pesquisa de ativos", () => {
  it("normaliza ticker para igualdade exata em maiusculas", () => {
    expect(normalizeTickerQuery(" petr4 ")).toBe("PETR4");
    expect(normalizeTickerQuery("HGLG11")).toBe("HGLG11");
    expect(normalizeTickerQuery("   ")).toBeUndefined();
  });

  it("nao aceita tipo fora do contrato ACAO/FII", () => {
    expect(normalizeTipoQuery("acao")).toBe("ACAO");
    expect(normalizeTipoQuery("FII")).toBe("FII");
    expect(normalizeTipoQuery("ETF")).toBeUndefined();
    expect(normalizeTipoQuery("")).toBeUndefined();
  });
});

describe("campos do snapshot", () => {
  it("lista apenas campos retornados, sem inventar indicadores", () => {
    const snapshot: SnapshotMercado = {
      id: 1,
      ativo_id: 1,
      ticker: "HGLG11",
      tipo: "FII",
      data_referencia: "2026-09-01",
      data_coleta: "2026-09-01T12:00:00",
      data_publicacao: null,
      fonte: "persistido",
      preco: 160,
      dy: 0.08,
      pvp: null,
      vpa: 0,
      campos: {
        preco: { semantica: "PRESENTE" },
        dy: { semantica: "PRESENTE" },
        pvp: { semantica: "AUSENTE" },
        vpa: { semantica: "ZERO" },
      },
    };
    expect(snapshotFieldKeys(snapshot)).toEqual(["preco", "dy", "pvp", "vpa"]);
    expect(isMoneySnapshotField("preco")).toBe(true);
    expect(isMoneySnapshotField("dy")).toBe(false);
  });
});

describe("freshness", () => {
  it("resume categorias da API sem mascarar MISSING", () => {
    const estado: FreshnessEstado = {
      ticker: "HGLG11",
      tipo: "FII",
      categorias: {
        mercado: {
          categoria: "mercado",
          status: "FRESH",
          valor: 1,
          data_referencia: "2026-09-01",
          data_coleta: "2026-09-01T12:00:00",
          data_publicacao: null,
          fonte: "persistido",
        },
        contabil: {
          categoria: "contabil",
          status: "MISSING",
          valor: null,
          data_referencia: null,
          data_coleta: null,
          data_publicacao: null,
          fonte: null,
        },
      },
    };
    expect(freshnessSummary({ kind: "ok", data: estado }).state).toBe("MISSING");
    expect(freshnessSummary({ kind: "absent" }).state).toBe("AUSENTE");
  });
});
