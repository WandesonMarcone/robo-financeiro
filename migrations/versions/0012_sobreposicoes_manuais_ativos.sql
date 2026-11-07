-- Classificação editorial definida por administrador.
-- É deliberadamente separada dos coletores: uma coleta nunca pode sobrescrever
-- uma decisão humana bloqueada.
CREATE TABLE IF NOT EXISTS sobreposicoes_manuais_ativos (
    ativo_id INTEGER PRIMARY KEY REFERENCES ativos(id) ON DELETE CASCADE,
    classe VARCHAR(120),
    segmento VARCHAR(160),
    estrategia VARCHAR(160),
    bloqueado BOOLEAN NOT NULL DEFAULT TRUE,
    origem VARCHAR(40) NOT NULL DEFAULT 'PAINEL_ADMIN',
    criado_em TIMESTAMP NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMP NOT NULL DEFAULT NOW()
);
