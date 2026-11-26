-- Evidência oficial para datas de pagamento. Uma linha é preservada mesmo
-- quando ainda não existe data-ex confirmada para associá-la ao Yahoo.
CREATE TABLE IF NOT EXISTS conciliacoes_proventos_oficiais (
    id BIGSERIAL PRIMARY KEY,
    chave VARCHAR(64) NOT NULL UNIQUE,
    ticker VARCHAR(20) NOT NULL,
    classe VARCHAR(20) NOT NULL,
    isin VARCHAR(20),
    data_com DATE,
    data_pagamento DATE NOT NULL,
    tipo_original VARCHAR(120),
    valor_unitario NUMERIC(20, 10) NOT NULL,
    fonte VARCHAR(80) NOT NULL,
    url_fonte TEXT,
    status VARCHAR(30) NOT NULL DEFAULT 'PENDENTE_DATA_EX',
    provento_id BIGINT REFERENCES proventos_ativos(id),
    detalhe TEXT,
    coletado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (classe IN ('ACAO', 'FII', 'ETF', 'BDR')),
    CHECK (status IN ('CONFIRMADO', 'PENDENTE_DATA_EX', 'CONFLITO'))
);

CREATE INDEX IF NOT EXISTS idx_conciliacoes_proventos_pendentes
    ON conciliacoes_proventos_oficiais (ticker, classe, status, data_com DESC);
