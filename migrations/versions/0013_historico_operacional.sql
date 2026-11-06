-- Histórico administrativo persistente: operações, varreduras, erros e envios.
-- É aditivo e pode ser aplicado mais de uma vez com segurança.
CREATE TABLE IF NOT EXISTS eventos_operacionais (
    id SERIAL PRIMARY KEY,
    origem VARCHAR(30) NOT NULL DEFAULT 'SISTEMA',
    tipo VARCHAR(80) NOT NULL,
    ticker VARCHAR(10),
    status VARCHAR(30) NOT NULL DEFAULT 'EM_ANDAMENTO',
    mensagem TEXT,
    erro TEXT,
    detalhes TEXT,
    iniciado_em TIMESTAMP NOT NULL DEFAULT NOW(),
    concluido_em TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_eventos_operacionais_tipo ON eventos_operacionais (tipo);
CREATE INDEX IF NOT EXISTS ix_eventos_operacionais_ticker ON eventos_operacionais (ticker);
CREATE INDEX IF NOT EXISTS ix_eventos_operacionais_status ON eventos_operacionais (status);
CREATE INDEX IF NOT EXISTS ix_eventos_operacionais_iniciado_em ON eventos_operacionais (iniciado_em DESC);

CREATE TABLE IF NOT EXISTS historico_notificacoes (
    id SERIAL PRIMARY KEY,
    canal VARCHAR(30) NOT NULL DEFAULT 'TELEGRAM',
    tipo VARCHAR(80) NOT NULL,
    ticker VARCHAR(10),
    destinatario VARCHAR(80),
    status VARCHAR(30) NOT NULL DEFAULT 'GERADA',
    resumo TEXT,
    erro TEXT,
    criado_em TIMESTAMP NOT NULL DEFAULT NOW(),
    enviado_em TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_historico_notificacoes_tipo ON historico_notificacoes (tipo);
CREATE INDEX IF NOT EXISTS ix_historico_notificacoes_ticker ON historico_notificacoes (ticker);
CREATE INDEX IF NOT EXISTS ix_historico_notificacoes_status ON historico_notificacoes (status);
CREATE INDEX IF NOT EXISTS ix_historico_notificacoes_criado_em ON historico_notificacoes (criado_em DESC);
