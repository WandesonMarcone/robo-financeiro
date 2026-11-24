-- Eventos necessários para calcular rentabilidade real na Carteira Consolidada.
-- A coleta começa na implantação e usa apenas uma janela curta e sobreposta;
-- não existe carga indiscriminada de anos anteriores.
CREATE TABLE IF NOT EXISTS proventos_ativos (
    id BIGSERIAL PRIMARY KEY,
    identificador VARCHAR(64) NOT NULL UNIQUE,
    ticker VARCHAR(20) NOT NULL,
    classe VARCHAR(20) NOT NULL,
    data_ex DATE NOT NULL,
    data_pagamento DATE,
    tipo VARCHAR(40) NOT NULL,
    valor_unitario NUMERIC(20, 8) NOT NULL,
    moeda VARCHAR(8) NOT NULL DEFAULT 'BRL',
    fonte VARCHAR(60) NOT NULL,
    qualidade_fonte VARCHAR(20) NOT NULL DEFAULT 'COMPLEMENTAR',
    coletado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (classe IN ('ACAO', 'FII', 'ETF', 'BDR')),
    CHECK (valor_unitario >= 0)
);

CREATE INDEX IF NOT EXISTS idx_proventos_ativos_ticker_data
    ON proventos_ativos (ticker, data_ex DESC);

CREATE TABLE IF NOT EXISTS eventos_corporativos_ativos (
    id BIGSERIAL PRIMARY KEY,
    identificador VARCHAR(64) NOT NULL UNIQUE,
    ticker VARCHAR(20) NOT NULL,
    classe VARCHAR(20) NOT NULL,
    data_referencia DATE NOT NULL,
    tipo VARCHAR(40) NOT NULL,
    fator NUMERIC(20, 8),
    descricao TEXT,
    fonte VARCHAR(60) NOT NULL,
    qualidade_fonte VARCHAR(20) NOT NULL DEFAULT 'COMPLEMENTAR',
    coletado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (classe IN ('ACAO', 'FII', 'ETF', 'BDR'))
);

CREATE INDEX IF NOT EXISTS idx_eventos_corporativos_ticker_data
    ON eventos_corporativos_ativos (ticker, data_referencia DESC);
