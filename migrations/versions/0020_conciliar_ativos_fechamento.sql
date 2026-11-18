-- Reconcilia os tickers presentes em BD_Acoes/BD_FIIs em 17/11/2026.
-- CNPJs conferidos no cadastro/documentos oficiais da CVM. RENT4 e RENT3
-- representam classes da mesma emissora: o schema exige CNPJ unico por ticker.
-- O marcador exclusivo de RENT4 permite snapshot de mercado, mas impede que
-- documentos CVM da Localiza sejam vinculados a ele indevidamente.
-- Aplicar em transacao. Divergencias no cadastro existente abortam tudo.
DO $$
DECLARE
    divergencia TEXT;
BEGIN
    WITH esperados(ticker, cnpj, tipo) AS (VALUES
        ('WIZC3', '42.278.473/0001-03', 'ACAO'),
        ('VULC3', '50.926.955/0001-42', 'ACAO'),
        ('VBBR3', '34.274.233/0001-02', 'ACAO'),
        ('TEND3', '71.476.527/0001-35', 'ACAO'),
        ('BEEF3', '67.620.377/0001-14', 'ACAO'),
        ('DIRR3', '16.614.075/0001-00', 'ACAO'),
        ('PSSA3', '02.149.205/0001-69', 'ACAO'),
        ('RENT4', 'PENDENTE-RENT4', 'ACAO'),
        ('UGPA3', '33.256.439/0001-39', 'ACAO'),
        ('KNCR11', '16.706.958/0001-32', 'FII')
    )
    SELECT string_agg(e.ticker || ': ' || a.cnpj || '/' || a.tipo::text, ', ')
      INTO divergencia
      FROM esperados e JOIN ativos a USING (ticker)
     WHERE a.cnpj <> e.cnpj OR a.tipo::text <> e.tipo;
    IF divergencia IS NOT NULL THEN
        RAISE EXCEPTION 'Cadastro existente divergente: %', divergencia;
    END IF;

    INSERT INTO ativos (ticker, cnpj, tipo)
    SELECT e.ticker, e.cnpj, e.tipo::tipoativo
      FROM (VALUES
        ('WIZC3', '42.278.473/0001-03', 'ACAO'),
        ('VULC3', '50.926.955/0001-42', 'ACAO'),
        ('VBBR3', '34.274.233/0001-02', 'ACAO'),
        ('TEND3', '71.476.527/0001-35', 'ACAO'),
        ('BEEF3', '67.620.377/0001-14', 'ACAO'),
        ('DIRR3', '16.614.075/0001-00', 'ACAO'),
        ('PSSA3', '02.149.205/0001-69', 'ACAO'),
        ('RENT4', 'PENDENTE-RENT4', 'ACAO'),
        ('UGPA3', '33.256.439/0001-39', 'ACAO'),
        ('KNCR11', '16.706.958/0001-32', 'FII')
      ) AS e(ticker, cnpj, tipo)
     WHERE NOT EXISTS (SELECT 1 FROM ativos a WHERE a.ticker = e.ticker);

    -- O catalogo legado guardava o CNPJ de outra empresa para BEEF3.
    -- Nao sobrescrever eventual correcao independente/conflitante.
    IF EXISTS (SELECT 1 FROM ativos_catalogo
               WHERE ticker = 'BEEF3'
                 AND cnpj NOT IN ('43.339.004/0001-42', '67.620.377/0001-14')) THEN
        RAISE EXCEPTION 'CNPJ inesperado no catalogo de BEEF3';
    END IF;
    UPDATE ativos_catalogo SET cnpj = '67.620.377/0001-14',
                               fonte = 'CVM', data_atualizacao = NOW()
     WHERE ticker = 'BEEF3' AND cnpj = '43.339.004/0001-42';
    UPDATE ativos_catalogo SET cnpj = '16.706.958/0001-32',
                               fonte = 'CVM', data_atualizacao = NOW()
     WHERE ticker = 'KNCR11' AND cnpj IS NULL;
END $$;
