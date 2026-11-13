-- Prova usada por uma classificação automática. A coleta não sobrescreve uma
-- sobreposição humana bloqueada; esta tabela apenas permite explicar a decisão.
CREATE TABLE IF NOT EXISTS evidencias_taxonomia_ativos (
    id BIGSERIAL PRIMARY KEY,
    ativo_id INTEGER NOT NULL REFERENCES ativos(id) ON DELETE CASCADE,
    classe VARCHAR(120) NOT NULL,
    segmento VARCHAR(160) NOT NULL,
    fonte VARCHAR(100) NOT NULL,
    documento_id INTEGER REFERENCES documentos_qualitativos(id) ON DELETE SET NULL,
    trecho TEXT,
    confianca VARCHAR(20) NOT NULL,
    aplicado BOOLEAN NOT NULL DEFAULT FALSE,
    criado_em TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_evidencias_taxonomia_ativo_em
    ON evidencias_taxonomia_ativos (ativo_id, criado_em DESC);
