-- Histórico operacional da atualização cíclica, exibido na Central de Controles.
-- Definição; não executar automaticamente no boot.
CREATE TABLE IF NOT EXISTS execucoes_ciclicas (
    id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(80) NOT NULL UNIQUE,
    status VARCHAR(20) NOT NULL CHECK (status IN ('sucesso', 'falha', 'cancelado')),
    limite_total INTEGER NOT NULL CHECK (limite_total BETWEEN 1 AND 20),
    acoes_solicitadas INTEGER,
    fiis_solicitados INTEGER,
    acoes_gravadas BOOLEAN,
    fiis_gravados BOOLEAN,
    duracao_segundos NUMERIC(12, 3),
    url_execucao TEXT,
    resumo_erro VARCHAR(300),
    concluido_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_execucoes_ciclicas_concluido_em
    ON execucoes_ciclicas (concluido_em DESC);
