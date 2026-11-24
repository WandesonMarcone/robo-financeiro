-- Amplia o cadastro já consumido pelas APIs sem renomear tabelas ou quebrar
-- clientes existentes. O histórico começa na implantação: não há backfill.
ALTER TABLE instrumentos_internacionais
    DROP CONSTRAINT IF EXISTS instrumentos_internacionais_tipo_check;

ALTER TABLE instrumentos_internacionais
    ADD CONSTRAINT instrumentos_internacionais_tipo_check
    CHECK (tipo IN ('ETF', 'BDR', 'CRIPTO', 'MOEDA', 'INDICE', 'COMMODITY'));

INSERT INTO instrumentos_internacionais
    (ticker, tipo, nome, simbolo_yahoo_br, simbolo_exterior, fonte_cadastro, ativo)
VALUES
    ('BTCBRL', 'CRIPTO', 'Bitcoin em reais', 'BTC-USD', 'BTC-USD', 'BASE_INICIAL_SISTEMA', TRUE),
    ('ETHBRL', 'CRIPTO', 'Ethereum em reais', 'ETH-USD', 'ETH-USD', 'BASE_INICIAL_SISTEMA', TRUE),
    ('USDBRL', 'MOEDA', 'Dólar comercial em reais', 'BRL=X', 'BRL=X', 'BASE_INICIAL_SISTEMA', TRUE)
ON CONFLICT (ticker) DO UPDATE SET
    tipo=EXCLUDED.tipo,
    nome=COALESCE(instrumentos_internacionais.nome, EXCLUDED.nome),
    simbolo_yahoo_br=EXCLUDED.simbolo_yahoo_br,
    simbolo_exterior=COALESCE(instrumentos_internacionais.simbolo_exterior, EXCLUDED.simbolo_exterior),
    ativo=TRUE,
    atualizado_em=NOW();
