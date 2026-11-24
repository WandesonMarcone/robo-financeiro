-- Base normalizada de fatos e indicadores para valuation.
-- A planilha operacional continua sendo gravada antes destas tabelas.
CREATE TABLE IF NOT EXISTS fundamentos_ativos (
    id BIGSERIAL PRIMARY KEY,
    identificador VARCHAR(96) NOT NULL UNIQUE,
    ticker VARCHAR(20) NOT NULL,
    cnpj VARCHAR(14),
    classe VARCHAR(20) NOT NULL,
    periodo_inicio DATE,
    periodo_fim DATE NOT NULL,
    exercicio INTEGER NOT NULL,
    periodicidade VARCHAR(20) NOT NULL,
    documento VARCHAR(20) NOT NULL,
    escopo VARCHAR(20) NOT NULL DEFAULT 'CONSOLIDADO',
    demonstracao VARCHAR(30),
    conta_codigo VARCHAR(40),
    metrica VARCHAR(80) NOT NULL,
    valor NUMERIC(30, 8) NOT NULL,
    unidade VARCHAR(20) NOT NULL DEFAULT 'BRL',
    moeda VARCHAR(8) NOT NULL DEFAULT 'BRL',
    fonte VARCHAR(80) NOT NULL,
    qualidade_fonte VARCHAR(20) NOT NULL DEFAULT 'OFICIAL',
    url_origem TEXT,
    coletado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (classe IN ('ACAO', 'FII')),
    CHECK (periodicidade IN ('ANUAL', 'TRIMESTRAL', 'MENSAL', 'PONTUAL')),
    CHECK (qualidade_fonte IN ('OFICIAL', 'DERIVADO', 'COMPLEMENTAR', 'DOCUMENTAL'))
);

CREATE INDEX IF NOT EXISTS idx_fundamentos_ticker_periodo
    ON fundamentos_ativos (ticker, periodo_fim DESC, metrica);
CREATE INDEX IF NOT EXISTS idx_fundamentos_cnpj_periodo
    ON fundamentos_ativos (cnpj, periodo_fim DESC);

CREATE TABLE IF NOT EXISTS indicadores_valuation_ativos (
    id BIGSERIAL PRIMARY KEY,
    identificador VARCHAR(96) NOT NULL UNIQUE,
    ticker VARCHAR(20) NOT NULL,
    classe VARCHAR(20) NOT NULL,
    periodo_fim DATE NOT NULL,
    exercicio INTEGER NOT NULL,
    periodicidade VARCHAR(20) NOT NULL,
    indicador VARCHAR(80) NOT NULL,
    valor NUMERIC(30, 8) NOT NULL,
    unidade VARCHAR(20) NOT NULL,
    formula_versao VARCHAR(40) NOT NULL,
    entradas JSONB NOT NULL DEFAULT '{}'::jsonb,
    qualidade VARCHAR(20) NOT NULL DEFAULT 'DERIVADO',
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (classe IN ('ACAO', 'FII')),
    CHECK (periodicidade IN ('ANUAL', 'TRIMESTRAL', 'MENSAL', 'PONTUAL'))
);

CREATE INDEX IF NOT EXISTS idx_indicadores_valuation_ticker_periodo
    ON indicadores_valuation_ativos (ticker, periodo_fim DESC, indicador);

CREATE TABLE IF NOT EXISTS cobertura_valuation_ativos (
    ticker VARCHAR(20) NOT NULL,
    classe VARCHAR(20) NOT NULL,
    metodo VARCHAR(40) NOT NULL,
    status VARCHAR(30) NOT NULL,
    anos_disponiveis INTEGER NOT NULL DEFAULT 0,
    periodo_inicial DATE,
    periodo_final DATE,
    campos_presentes JSONB NOT NULL DEFAULT '[]'::jsonb,
    campos_ausentes JSONB NOT NULL DEFAULT '[]'::jsonb,
    observacao TEXT,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, classe, metodo),
    CHECK (classe IN ('ACAO', 'FII')),
    CHECK (status IN ('PRONTO', 'PARCIAL', 'INSUFICIENTE', 'NAO_APLICAVEL', 'PREMISSAS_NECESSARIAS'))
);

CREATE INDEX IF NOT EXISTS idx_cobertura_valuation_status
    ON cobertura_valuation_ativos (status, metodo, ticker);
