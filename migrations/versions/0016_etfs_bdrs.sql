-- ETFs e BDRs ficam em tabelas próprias: não são ações/FIIs brasileiros e
-- não devem herdar métricas ou regras documentais daqueles ativos.
CREATE TABLE IF NOT EXISTS instrumentos_internacionais (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(12) NOT NULL UNIQUE,
    tipo VARCHAR(8) NOT NULL CHECK (tipo IN ('ETF', 'BDR')),
    nome VARCHAR(240),
    simbolo_yahoo_br VARCHAR(32),
    simbolo_exterior VARCHAR(32),
    sec_cik VARCHAR(16),
    indice_referencia VARCHAR(240),
    gestora VARCHAR(160),
    moeda_origem VARCHAR(12),
    fonte_cadastro VARCHAR(100) NOT NULL DEFAULT 'MANUAL_ADMIN',
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em TIMESTAMP NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS observacoes_instrumentos_internacionais (
    id BIGSERIAL PRIMARY KEY,
    instrumento_id BIGINT NOT NULL REFERENCES instrumentos_internacionais(id) ON DELETE CASCADE,
    referencia_em TIMESTAMP NOT NULL,
    abertura NUMERIC(24,8), maxima NUMERIC(24,8), minima NUMERIC(24,8),
    fechamento NUMERIC(24,8), volume BIGINT,
    variacao_percentual NUMERIC(12,6),
    fonte VARCHAR(100) NOT NULL,
    qualidade_fonte VARCHAR(20) NOT NULL DEFAULT 'COMPLEMENTAR',
    coletado_em TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uix_obs_instrumento_ref UNIQUE (instrumento_id, referencia_em)
);
CREATE INDEX IF NOT EXISTS ix_obs_instrumento_data
    ON observacoes_instrumentos_internacionais (instrumento_id, referencia_em DESC);

CREATE TABLE IF NOT EXISTS metricas_instrumentos_internacionais (
    id BIGSERIAL PRIMARY KEY,
    instrumento_id BIGINT NOT NULL REFERENCES instrumentos_internacionais(id) ON DELETE CASCADE,
    chave VARCHAR(80) NOT NULL,
    valor_numerico NUMERIC(28,10),
    valor_texto TEXT,
    unidade VARCHAR(30),
    fonte VARCHAR(120) NOT NULL,
    qualidade_fonte VARCHAR(20) NOT NULL DEFAULT 'COMPLEMENTAR',
    referencia_em TIMESTAMP,
    bloqueado BOOLEAN NOT NULL DEFAULT FALSE,
    atualizado_em TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uix_metrica_instrumento UNIQUE (instrumento_id, chave)
);
