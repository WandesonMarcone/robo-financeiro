-- Permite comprovar quando cada dado CVM de ação foi persistido.
-- Registros antigos permanecem com NULL.
ALTER TABLE dados_financeiros_acoes
    ADD COLUMN IF NOT EXISTS data_coleta TIMESTAMP;
