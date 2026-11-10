-- Favoritos de ETFs e BDRs são deliberadamente separados de
-- ``ativos_acompanhados``. A tabela antiga referencia apenas ``ativos``
-- (ações/FIIs) e não pode receber instrumentos internacionais.
CREATE TABLE IF NOT EXISTS favoritos_instrumentos_internacionais (
    id BIGSERIAL PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    instrumento_id BIGINT NOT NULL REFERENCES instrumentos_internacionais(id) ON DELETE CASCADE,
    criado_em TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uix_favorito_internacional_usuario_instrumento
        UNIQUE (usuario_id, instrumento_id)
);

CREATE INDEX IF NOT EXISTS ix_favorito_internacional_usuario
    ON favoritos_instrumentos_internacionais (usuario_id);
CREATE INDEX IF NOT EXISTS ix_favorito_internacional_instrumento
    ON favoritos_instrumentos_internacionais (instrumento_id);
