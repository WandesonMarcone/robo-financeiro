import { describe, expect, it } from "vitest";
import {
  alertaCritico,
  freshnessDaNotificacao,
  indicadorDaNotificacao,
  notificacaoCritica,
  notificacaoLida,
  origemDaNotificacao,
  prioridadeExibida,
} from "./alertas";
import type { AlertaEvento, Notificacao } from "./types";

const baseNotificacao: Notificacao = {
  id: 1,
  tipo: "ALERTA_MERCADO",
  titulo: "Movimento",
  mensagem: "Variacao",
  ativo_id: 101,
  ticker: "HGLG11",
  canal: "WEB",
  status: "PENDENTE",
  dados: { prioridade: "CRITICO", indicador: "preco", freshness: "FRESH" },
  criado_em: "2026-09-10T10:00:00",
  lida_em: null,
  tentativas: 0,
  enviada_em: null,
};

const baseAlerta: AlertaEvento = {
  id: 61,
  tipo_alerta: "MERCADO",
  tipo_ativo: "FII",
  ativo_id: 101,
  ticker: "HGLG11",
  indicador: "preco",
  valor_anterior: 150,
  valor_atual: 160.5,
  variacao_percentual: 7,
  regra: "preco",
  motivo: "Variacao acima do limiar",
  severidade: "WARNING",
  recomendacao: null,
  origem: "motor",
  data_referencia: "2026-09-01",
  data_evento: "2026-09-10T10:00:00",
  telegram_enviado: false,
};

describe("alertas 11.8", () => {
  it("nao inventa prioridade, freshness ou indicador", () => {
    expect(prioridadeExibida(baseNotificacao)).toBe("CRITICO");
    expect(freshnessDaNotificacao(baseNotificacao)).toBe("FRESH");
    expect(indicadorDaNotificacao(baseNotificacao)).toBe("preco");
    expect(origemDaNotificacao(baseNotificacao)).toBe("WEB");
    expect(prioridadeExibida({ ...baseNotificacao, dados: null })).toBeNull();
    expect(freshnessDaNotificacao({ ...baseNotificacao, dados: null })).toBeNull();
    expect(indicadorDaNotificacao({ ...baseNotificacao, dados: null, tipo: null })).toBeNull();
  });

  it("distingue lida e nao lida sem persistir localmente", () => {
    expect(notificacaoLida(baseNotificacao)).toBe(false);
    expect(notificacaoLida({ ...baseNotificacao, lida_em: "2026-09-11T10:00:00" })).toBe(true);
  });

  it("marca critico somente com campos da API", () => {
    expect(notificacaoCritica(baseNotificacao)).toBe(true);
    expect(notificacaoCritica({ ...baseNotificacao, dados: { prioridade: "BAIXA" }, tipo: "DIVIDENDO" })).toBe(false);
    expect(alertaCritico(baseAlerta)).toBe(false);
    expect(alertaCritico({ ...baseAlerta, tipo_alerta: "CRITICO", severidade: "CRITICO" })).toBe(true);
  });
});
