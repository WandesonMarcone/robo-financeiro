-- Fase 4: cada decisão de triagem fica auditável no Neon.
CREATE TABLE IF NOT EXISTS oportunidades_triagem (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL,
    classe VARCHAR(20) NOT NULL,
    referencia_em DATE NOT NULL,
    score NUMERIC(12,4),
    elegivel BOOLEAN NOT NULL,
    motivos JSONB NOT NULL DEFAULT '[]'::jsonb,
    criterios JSONB NOT NULL DEFAULT '{}'::jsonb,
    fonte VARCHAR(80) NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (ticker, classe, referencia_em, fonte)
);
CREATE INDEX IF NOT EXISTS idx_oportunidades_triagem_ativas
    ON oportunidades_triagem (classe, elegivel, referencia_em DESC);
