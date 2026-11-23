CREATE TABLE IF NOT EXISTS configuracoes_sistema (
    chave VARCHAR(80) PRIMARY KEY,
    valor VARCHAR(255) NOT NULL,
    descricao TEXT,
    atualizado_em TIMESTAMP NOT NULL DEFAULT NOW()
);

INSERT INTO configuracoes_sistema (chave, valor, descricao)
VALUES (
    'janela_documentos_dias',
    '30',
    'Janela máxima de coleta e processamento de documentos.'
)
ON CONFLICT (chave) DO NOTHING;
