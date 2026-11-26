-- A planilha controla a autorização atual; a saída dela não pode apagar a
-- evidência de que um ticker já integrou o universo nem seus dados associados.
ALTER TABLE universo_acoes_autorizadas
    ADD COLUMN IF NOT EXISTS ativo BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE universo_acoes_autorizadas
    ADD COLUMN IF NOT EXISTS desativado_em TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_universo_acoes_ativos
    ON universo_acoes_autorizadas (ticker) WHERE ativo=TRUE;
