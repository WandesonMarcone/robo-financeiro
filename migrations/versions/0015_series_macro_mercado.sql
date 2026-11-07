-- Séries macro e de mercado: observações oficiais e intradiárias ficam separadas.
CREATE TABLE IF NOT EXISTS series_mercado (
    id BIGSERIAL PRIMARY KEY,
    codigo VARCHAR(60) NOT NULL UNIQUE,
    nome VARCHAR(160) NOT NULL,
    classe VARCHAR(30) NOT NULL,
    fonte VARCHAR(100) NOT NULL,
    periodicidade VARCHAR(20) NOT NULL,
    tipo_valor VARCHAR(20) NOT NULL,
    horario_referencia VARCHAR(60),
    ativa BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em TIMESTAMP NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS observacoes_mercado (
    id BIGSERIAL PRIMARY KEY,
    serie_id BIGINT NOT NULL REFERENCES series_mercado(id) ON DELETE CASCADE,
    referencia_em TIMESTAMP NOT NULL,
    valor NUMERIC(24,8),
    abertura NUMERIC(24,8),
    maxima NUMERIC(24,8),
    minima NUMERIC(24,8),
    fechamento NUMERIC(24,8),
    variacao_percentual NUMERIC(12,6),
    origem VARCHAR(100) NOT NULL,
    coletado_em TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uix_observacoes_mercado_serie_referencia UNIQUE (serie_id, referencia_em)
);
CREATE INDEX IF NOT EXISTS ix_observacoes_mercado_serie_data ON observacoes_mercado (serie_id, referencia_em DESC);
CREATE TABLE IF NOT EXISTS titulos_tesouro_observacoes (
    id BIGSERIAL PRIMARY KEY,
    nome_titulo VARCHAR(180) NOT NULL,
    vencimento DATE,
    referencia_em TIMESTAMP NOT NULL,
    taxa_compra NUMERIC(12,6), taxa_venda NUMERIC(12,6),
    preco_compra NUMERIC(18,6), preco_venda NUMERIC(18,6),
    fonte VARCHAR(100) NOT NULL DEFAULT 'TESOURO_DIRETO',
    coletado_em TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uix_tesouro_titulo_referencia UNIQUE (nome_titulo, vencimento, referencia_em)
);
