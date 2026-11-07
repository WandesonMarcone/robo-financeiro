-- Extensões aditivas da Central: não removem nem reescrevem dados existentes.
CREATE TABLE IF NOT EXISTS preferencias_alertas_usuarios (
    usuario_id INTEGER PRIMARY KEY REFERENCES usuarios(id) ON DELETE CASCADE,
    alertas_ativos BOOLEAN NOT NULL DEFAULT TRUE,
    variacao_minima_percentual NUMERIC(8,4),
    atualizado_em TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS indicadores_manuais_ativos (
    id BIGSERIAL PRIMARY KEY,
    ativo_id INTEGER NOT NULL REFERENCES ativos(id) ON DELETE CASCADE,
    chave VARCHAR(80) NOT NULL,
    valor_texto VARCHAR(255) NOT NULL,
    fonte TEXT NOT NULL,
    data_referencia DATE,
    bloqueado BOOLEAN NOT NULL DEFAULT TRUE,
    origem VARCHAR(40) NOT NULL DEFAULT 'PAINEL_ADMIN',
    criado_em TIMESTAMP NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uix_indicadores_manuais_ativo_chave UNIQUE (ativo_id, chave)
);
CREATE INDEX IF NOT EXISTS ix_indicadores_manuais_ativo ON indicadores_manuais_ativos (ativo_id);

ALTER TABLE historico_notificacoes
    ADD COLUMN IF NOT EXISTS audiencia VARCHAR(20) NOT NULL DEFAULT 'USUARIO',
    ADD COLUMN IF NOT EXISTS usuario_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS ix_historico_notificacoes_audiencia ON historico_notificacoes (audiencia, criado_em DESC);
CREATE INDEX IF NOT EXISTS ix_historico_notificacoes_usuario ON historico_notificacoes (usuario_id, criado_em DESC);
