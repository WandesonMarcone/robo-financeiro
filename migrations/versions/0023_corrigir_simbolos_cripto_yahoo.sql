-- O Yahoo não oferece os pares BTC-BRL/ETH-BRL de forma estável. A coleta
-- usa os pares em USD e converte cada candle com BRL=X antes de persistir.
UPDATE instrumentos_internacionais
SET simbolo_yahoo_br = CASE ticker
        WHEN 'BTCBRL' THEN 'BTC-USD'
        WHEN 'ETHBRL' THEN 'ETH-USD'
    END,
    simbolo_exterior = CASE ticker
        WHEN 'BTCBRL' THEN 'BTC-USD'
        WHEN 'ETHBRL' THEN 'ETH-USD'
    END,
    atualizado_em = NOW()
WHERE ticker IN ('BTCBRL', 'ETHBRL');
