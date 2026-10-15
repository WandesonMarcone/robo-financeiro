-- +migrate Up
-- Versao:    0001
-- Objetivo:  Adicionar o estado de cadastro/aprovacao a tabela "usuarios".
-- Reversivel: sim (ver secao Down).
-- Execucao:   manual, pelo administrador. NAO e executada automaticamente
--             pelo projeto e NAO deve rodar no boot da aplicacao.
--
-- Justificativa (Fase B da Etapa 2):
--   A tabela "usuarios" ja existente nao possui um campo inequivoco de status
--   de aprovacao. Combinar "papel" + "ativo" seria ambiguo (por exemplo,
--   ativo=FAÇO pode significar conta pendente, rejeitada ou suspensa). Por isso
--   adicionamos UMA unica coluna com vocabulario controlado:
--     pendente | aprovado | rejeitado | suspenso
--
-- Preservacao dos registros existentes:
--   * A alteracao e puramente aditiva: nenhum registro e apagado ou alterado
--     em outros campos.
--   * A coluna recebe DEFAULT 'pendente', de modo que todas as linhas ja
--     existentes passam a ter um valor valido sem reescrita destrutiva.
--   * Nenhuma coluna existente e renomeada, removida ou tem tipo alterado.
--   * Como o controle de acesso atual do bot usa config.USUARIOS_AUTORIZADOS
--     como fonte primaria, as contas ja operantes continuam acessando
--     normalmente; a coluna so passa a valer para o fluxo de autocadastro.
--
-- IMPORTANTE: execute manualmente e apenas apos backup. Exemplo:
--   psql "$DATABASE_URL" -f migrations/versions/0001_add_status_cadastro_usuarios.sql

BEGIN;

ALTER TABLE usuarios
    ADD COLUMN IF NOT EXISTS status_cadastro VARCHAR(20) NOT NULL DEFAULT 'pendente';

-- Backfill OPCIONAL (descomente e adapte SOMENTE se souber a semantica das
-- linhas pre-existentes). Nao e executado por padrao para nao presumir que
-- contas antigas estao aprovadas:
--
-- UPDATE usuarios
--    SET status_cadastro = 'aprovado'
--  WHERE status_cadastro = 'pendente'
--    AND ativo IS TRUE;

COMMIT;

-- +migrate Down
-- Reverte exatamente a mudanca do Up: remove apenas a coluna criada.
-- Nenhum dado de outras colunas e afetado.

BEGIN;

ALTER TABLE usuarios
    DROP COLUMN IF EXISTS status_cadastro;

COMMIT;
