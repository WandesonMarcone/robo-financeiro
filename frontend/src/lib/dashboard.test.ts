import { describe, expect, it } from "vitest";
import {
  countFromList,
  filterAlertasDoUsuario,
  notificacaoPrioridade,
  uniqueTickers,
  type ResourceState,
} from "./dashboard";
import type { AlertaEvento, Notificacao } from "./types";

describe("composicao do dashboard", () => {
  it("filtra alertas globais pelos tickers do usuario", () => {
    const alertas: AlertaEvento[] = [
      {
        id: 1,
        tipo_alerta: "MERCADO",
        tipo_ativo: "FII",
        ativo_id: 10,
        ticker: "HGLG11",
        indicador: "preco",
        valor_anterior: 1,
        valor_atual: 2,
        variacao_percentual: 100,
        regra: "x",
        motivo: "subiu",
        severidade: "WARNING",
        recomendacao: null,
        origem: "motor",
        data_referencia: null,
        data_evento: "2026-09-10",
        telegram_enviado: false,
      },
      {
        id: 2,
        tipo_alerta: "MERCADO",
        tipo_ativo: "ACAO",
        ativo_id: 11,
        ticker: "PETR4",
        indicador: "preco",
        valor_anterior: 1,
        valor_atual: 2,
        variacao_percentual: 100,
        regra: "x",
        motivo: "subiu",
        severidade: "WARNING",
        recomendacao: null,
        origem: "motor",
        data_referencia: null,
        data_evento: "2026-09-10",
        telegram_enviado: false,
      },
    ];
    expect(filterAlertasDoUsuario(alertas, ["HGLG11"]).map((item) => item.ticker)).toEqual(["HGLG11"]);
    expect(filterAlertasDoUsuario(alertas, [])).toEqual([]);
  });

  it("le prioridade real do payload da notificacao", () => {
    const item: Notificacao = {
      id: 1,
      tipo: "ALERTA",
      titulo: "x",
      mensagem: "y",
      ativo_id: 1,
      ticker: "HGLG11",
      canal: "web",
      status: "PENDENTE",
      dados: { prioridade: "CRITICO" },
      criado_em: null,
      lida_em: null,
      tentativas: 0,
      enviada_em: null,
    };
    expect(notificacaoPrioridade(item)).toBe("CRITICO");
    expect(notificacaoPrioridade({ ...item, dados: null })).toBeNull();
  });

  it("conta a partir de meta.total e nao inventa quando o recurso falha", () => {
    const ok: ResourceState<unknown[]> = { kind: "ok", data: [{}, {}], meta: { total: 9 } };
    const forbidden: ResourceState<unknown[]> = { kind: "forbidden", message: "Acesso negado." };
    expect(countFromList(ok)).toBe(9);
    expect(countFromList(forbidden)).toBeNull();
  });

  it("deduplica tickers do usuario", () => {
    expect(uniqueTickers([{ ticker: "hglg11" }, { ticker: "HGLG11" }, { ticker: null }])).toEqual(["HGLG11"]);
  });
});
