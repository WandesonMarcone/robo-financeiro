-- Definição; não executar automaticamente no boot.
-- Uma linha por índice e pregão. Os valores são OHLC diários obtidos
-- após o fechamento; a fonte é registrada para não confundir Yahoo com B3.
CREATE TABLE IF NOT EXISTS indices_mercado_diario (
    id BIGSERIAL PRIMARY KEY,
    indice VARCHAR(30) NOT NULL,
    data_pregao DATE NOT NULL,
    abertura NUMERIC,
    maxima NUMERIC,
    minima NUMERIC,
    fechamento NUMERIC,
    fechamento_anterior NUMERIC,
    variacao_percentual NUMERIC,
    fonte VARCHAR(120) NOT NULL,
    atualizado_em TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uix_indices_mercado_diario UNIQUE (indice, data_pregao),
    CONSTRAINT ck_indices_mercado_diario_max_min
        CHECK (maxima IS NULL OR minima IS NULL OR maxima >= minima)
);

CREATE INDEX IF NOT EXISTS ix_indices_mercado_diario_data
    ON indices_mercado_diario (data_pregao DESC);
