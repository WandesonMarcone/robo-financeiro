-- Catálogo central: ticker é único para negociação; CNPJ pode se repetir
-- entre classes da mesma companhia. A alteração preserva todas as linhas.
ALTER TABLE ativos_catalogo DROP CONSTRAINT IF EXISTS ativos_catalogo_cnpj_key;
DROP INDEX IF EXISTS ativos_catalogo_cnpj_key;
CREATE INDEX IF NOT EXISTS idx_ativos_catalogo_cnpj
    ON ativos_catalogo (cnpj) WHERE cnpj IS NOT NULL;
