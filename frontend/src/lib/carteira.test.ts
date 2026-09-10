import { describe, expect, it } from "vitest";
import { countAtivosDistintos, countPosicoes, latestTimestamp } from "./carteira";
import type { PosicaoCarteira } from "./types";

const hglg: PosicaoCarteira = {
  id: 1,
  ativo_id: 101,
  ticker: "HGLG11",
  tipo: "FII",
  quantidade: 10,
  preco_medio: 150,
  valor_investido: 1500,
  criado_em: "2026-01-01T00:00:00",
  atualizado_em: "2026-01-02T00:00:00",
};

const petr: PosicaoCarteira = {
  id: 2,
  ativo_id: 202,
  ticker: "PETR4",
  tipo: "ACAO",
  quantidade: 5,
  preco_medio: 30,
  valor_investido: 150,
  criado_em: "2026-02-01T00:00:00",
  atualizado_em: "2026-03-01T00:00:00",
};

describe("composicao da carteira", () => {
  it("conta posicoes a partir de meta.total e nao inventa em 403", () => {
    expect(countPosicoes({ kind: "ok", data: [hglg], meta: { total: 9 } })).toBe(9);
    expect(countPosicoes({ kind: "forbidden", message: "Acesso negado." })).toBeNull();
    expect(countPosicoes({ kind: "error", message: "falha" })).toBeNull();
  });

  it("conta ativos distintos pelo ticker, ignorando nulos", () => {
    expect(countAtivosDistintos([hglg, petr, { ...hglg, id: 3 }])).toBe(2);
    expect(countAtivosDistintos([{ ...hglg, ticker: null }])).toBe(0);
  });

  it("escolhe a data mais recente sem inventar quando todas ausentes", () => {
    expect(latestTimestamp([null, undefined])).toBeNull();
    expect(latestTimestamp(["2026-01-01T00:00:00", "2026-03-01T00:00:00"])).toBe("2026-03-01T00:00:00");
  });
});
