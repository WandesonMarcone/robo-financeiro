# Migrações do banco (Neon/PostgreSQL)

Este diretório contém migrações de esquema **versionadas e reversíveis** para o
banco de produção (Neon). O projeto **não** executa nenhuma migração
automaticamente: o boot nunca chama `create_all` sobre as tabelas existentes
(`main.criar_tabelas_se_solicitado` é opt-in e não cobre estes arquivos).

## Convenção

- Um arquivo por migração, em `versions/`, nomeado `NNNN_descricao.sql`.
- Cada arquivo contém duas seções delimitadas por comentários:
  - `-- +migrate Up`   — aplicação da mudança;
  - `-- +migrate Down` — reversão (desfaz exatamente o `Up`).
- Migrações devem ser idempotentes sempre que o dialeto permitir
  (`IF NOT EXISTS` / `IF EXISTS`).
- Nenhuma migração pode apagar dados: apenas adicionar/remover colunas de
  controle. Reversão remove apenas o que a própria migração criou.

## Como aplicar (manual, pelo administrador)

A aplicação é **sempre manual e explícita**, fora do boot da aplicação:

```bash
# Aplique a migração "Up" na string de conexão do Neon (variável DATABASE_URL)
psql "$DATABASE_URL" -f migrations/versions/0001_add_status_cadastro_usuarios.sql
```

Para reverter, execute manualmente a seção `Down` do mesmo arquivo.

## Estado atual

| Versão | Arquivo | Situação |
|---|---|---|
| 0001 | `versions/0001_add_status_cadastro_usuarios.sql` | Criada, **não executada**. |
