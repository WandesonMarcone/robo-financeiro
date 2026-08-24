# MIGRAÇÃO PARA O GITHUB REAL — BLOCO 5C / FASE 4 (PREPARAÇÃO)

> Documento de controle da migração controlada da versão validada no ZIP para o
> repositório GitHub real. NÃO executa push. NÃO ativa produção. NÃO encerra a
> Fase 4.

---

## 1. Estado atual do ZIP

- Fase 3 concluída (Blocos 1–4, 5A, 5B, 5C).
- Fase 4: Bloco 1 concluído; Bloco 2 ainda **aguardando execução real ponta a ponta**.
- **199 testes passando**, Ruff OK no escopo trabalhado (exceto aviso legado I001
  em `banco_dados.py`, intencionalmente preservado), `py_compile` OK.
- Google Sheets continua a fonte ativa; PostgreSQL é espelho paralelo.
- `ESPELHAMENTO_PG_ATIVO` permanece `false` por padrão.
- `pipeline_dados/banco_dados.py` contém os modelos do Bloco 5B/5C
  (`AtivoPerfil`, `SnapshotFii`, `SnapshotAcao`, `AtivoInquilino`, `TipoAtivo`).
- `.github/workflows/main.yml` já encaminha `GOOGLE_CREDS`, `SPREADSHEET_URL`,
  `DATABASE_URL` e `ESPELHAMENTO_PG_ATIVO` ao processo Python.

## 2. Estado esperado do GitHub após a migração

- Todo o comportamento legado do robô preservado (garimpo FIIs/Ações,
  `batch_update` no Sheets, `disparar_alertas`).
- Adicionada a integração validada do espelhamento PostgreSQL (Bloco 5C),
  acionada somente quando `ESPELHAMENTO_PG_ATIVO=true`.
- Sheets continua a fonte ativa; falha do PostgreSQL não desfaz/bloqueia o Sheets.
- Pipeline `pipeline_dados` com os módulos novos de qualidade, mapeamento,
  espelhamento e migração 5B.
- Testes do 5C/Fase 4 presentes e passando.
- Workflow corrigido para levar as variáveis de ambiente ao processo Python.

## 3. Lista exata de arquivos a substituir (GRUPO A + B)

Todos estes arquivos JÁ existem no GitHub e devem ser substituídos pelos que
estão nesta pasta `migration_package/`:

| Arquivo (destino no repo) | O que mudou | Por que é necessário | Depende de | Risco de conflito |
|---|---|---|---|---|
| `app.py` | Adicionada a integração do espelhamento 5C **após** a gravação no Sheets (bloco guardado por `config.ESPELHAMENTO_PG_ATIVO`). | Sem ele, o espelhamento nunca roda no fluxo real. | `config`, `pipeline_dados.espelhamento_mercado_5c` | **MÉDIO**: se o GitHub tiver versão com outras alterações locais, integrar o bloco novo em vez de sobrescrever o arquivo todo (ver seção 6). |
| `config.py` | Adicionados `obter_database_url()`, `DATABASE_URL`, `SPREADSHEET_URL` via env, `bool_ambiente()`, `ESPELHAMENTO_PG_ATIVO`. | Config central das novas variáveis usadas por app.py e espelhamento. | — | **BAIXO**: alterações aditivas; conferir se o GitHub não tem preferências locais no mesmo bloco. |
| `.env.example` | Documentadas `DATABASE_URL`, `ESPELHAMENTO_PG_ATIVO`, `SPREADSHEET_URL`, `GOOGLE_CREDS`/`GOOGLE_CREDS_FILE`. | Referência de configuração para quem clonar. | — | **NULO**: apenas documentação. |
| `.github/workflows/main.yml` | Passo `Rodar o Robô` agora exporta `GOOGLE_CREDS`, `SPREADSHEET_URL`, `DATABASE_URL`, `ESPELHAMENTO_PG_ATIVO`. | Corrige o gap que impedia o processo Python de receber as variáveis no CI. | Secrets do repo (`GOOGLE_CREDENTIALS`, `SPREADSHEET_URL`, `DATABASE_URL`, `ESPELHAMENTO_PG_ATIVO`) | **BAIXO**: bloco `env` aditivo. |
| `pipeline_dados/banco_dados.py` | Já contém os modelos 5B/5C. | Importado por `espelhamento_mercado_5c`, `migracao_5b`, `deduplicacao` e testes. | `SQLAlchemy` | **MÉDIO**: se o GitHub tiver versão mais antiga sem os modelos, substituir; NÃO corrigir o aviso legado I001. |
| `tests/test_config.py` | Testa `obter_database_url()` e `verificar_configuracao()` (novas variáveis). | Cobertura da config alterada. | — | **BAIXO**. |
| `tests/test_main.py` | Testa comportamento da URL do banco no entrypoint. | Cobertura do main/legado. | — | **BAIXO**. |

## 4. Lista de arquivos novos (GRUPO A + B — adicionar)

| Arquivo (destino no repo) | O que é | Depende de | Risco de conflito |
|---|---|---|---|
| `pipeline_dados/espelhamento_mercado_5c.py` | Núcleo do Bloco 5C (espelhamento FIIs/Ações/inquilinos, idempotente). | `espelhamento_sheets`, `mapeamento_sheets`, `qualidade_dados`, `normalizacao`, `banco_dados`, `config`, `services.planilhas` | **NULO** (novo) |
| `pipeline_dados/espelhamento_sheets.py` | Espelhamento base (`_criar_sessao` com `pool_pre_ping`+`pool_recycle=1800`, `espelhar_ativo`). | `banco_dados`, `mapeamento_sheets`, `qualidade_dados`, `config` | **NULO** (novo) |
| `pipeline_dados/mapeamento_sheets.py` | Mapeamento/transformação das colunas do Sheets. | `normalizacao`, `qualidade_dados`, `config`, `banco_dados` | **NULO** (novo) |
| `pipeline_dados/qualidade_dados.py` | Validação e diagnóstico (VALID/WARNING/INVALID). | `banco_dados` (parcial) | **NULO** (novo) |
| `pipeline_dados/normalizacao.py` | Normalização de CNPJ/nomes/datas. | — | **NULO** (novo) |
| `pipeline_dados/migracao_5b.py` | Migração versionada/reversível das tabelas 5B. | `banco_dados`, SQLAlchemy | **NULO** (novo) |
| `tests/test_espelhamento_mercado_5c.py` | Testes FIIs 5C. | — | **NULO** (novo) |
| `tests/test_espelhamento_mercado_acoes_5c.py` | Testes Ações 5C. | — | **NULO** (novo) |
| `tests/test_espelhamento_inquilinos_5c.py` | Testes de inquilinos 5C. | — | **NULO** (novo) |
| `tests/test_espelhamento_sheets.py` | Testes do espelhamento base (pool settings). | — | **NULO** (novo) |
| `tests/test_integracao_5c.py` | Testes de integração produção 5C (flag, ordem Sheets→PG, idempotência). | — | **NULO** (novo) |
| `tests/test_mapeamento_sheets.py` | Testes de mapeamento. | — | **NULO** (novo) |
| `tests/test_migracao_5b.py` | Testes da migração 5B. | — | **NULO** (novo) |
| `tests/test_normalizacao.py` | Testes de normalização. | — | **NULO** (novo) |
| `tests/test_qualidade_dados.py` | Testes de qualidade de dados. | — | **NULO** (novo) |
| `tests/test_deduplicacao.py` | Testes de deduplicação. | — | **NULO** (novo) |

## 5. Lista de arquivos que NÃO devem ser alterados

- `pipeline_dados/banco_dados.py` **não deve ser alterado além da versão deste pacote**
  (não corrigir o aviso I001 de import order — regra do projeto).
- `pipeline_dados/deduplicacao.py` — caso já exista no GitHub em versão idêntica,
  não substituir; o pacote não o inclui (não é necessário para o 5C).
- `pipeline_dados/coletor_cvm.py`, `coletor_fiis.py`, `coletor_docs_acoes.py` —
  fluxo B3/FNET/CVM não é tocado por este bloco.
- `modules/scraper_fiis.py`, `modules/scraper_acoes.py` — **proibido alterar scrapers**.
- `main.py`, `atualizador_documentos.py`, `fnet_scraper.py`, `bot/`, `services/` —
  não fazem parte da migração 5C/Fase 4.
- `requirements.txt` — se o GitHub já tiver `SQLAlchemy` + `psycopg2-binary`,
  não substituir.
- Nenhum arquivo de segredo (`.env`, `credenciais.json`) deve existir no repo.

## 6. Alterações importantes em cada arquivo

### `app.py` — integrar, não substituir cegamente
A versão atual do GitHub tem o fluxo legado `rodar_garimpo_fiis()` /
`rodar_garimpo_acoes()` / `batch_update()` / `disparar_alertas()`. A migração
deve **preservar** esse comportamento e acrescentar **somente**:

```python
from pipeline_dados.espelhamento_mercado_5c import espelhar_mercado_se_ativo
...
if config.ESPELHAMENTO_PG_ATIVO:
    matriz_fiis = aba_fiis.get_all_values() if batch_updates_fiis else None
    matriz_acoes = aba_acoes.get_all_values() if batch_updates_acoes else None
    try:
        espelhar_mercado_se_ativo(matriz_fiis=matriz_fiis, matriz_acoes=matriz_acoes)
    except Exception as e:
        logger.exception("Espelhamento PostgreSQL falhou (Sheets preservado): %s", e)
```
- O bloco roda **depois** do `batch_update` (Sheets primeiro, PG depois).
- Falha do PG é registrada e **não** desfaz o Sheets.
- Se o GitHub tiver versão de `app.py` divergente, aplicar apenas este delta.

### `config.py`
- `obter_database_url()` normaliza `postgres://` → `postgresql://` e padroniza
  o fallback SQLite.
- `SPREADSHEET_URL`, `DATABASE_URL` e `ESPELHAMENTO_PG_ATIVO` lidos de env.
- `bool_ambiente()` interpreta `1/true/yes/sim/on`.

### `.github/workflows/main.yml`
- O secret `GOOGLE_CREDENTIALS` é mapeado para `GOOGLE_CREDS` no passo
  `Rodar o Robô`, além de `SPREADSHEET_URL`, `DATABASE_URL` e
  `ESPELHAMENTO_PG_ATIVO`. Nenhum valor é gravado em arquivo versionado.

## 7. Ordem recomendada para aplicar a migração

1. Criar branch de migração (ex.: `migracao-bloco5c`).
2. Adicionar os arquivos **novos** (seção 4) — sem conflito.
3. Substituir `config.py`, `banco_dados.py`, `test_config.py`, `test_main.py`.
4. Aplicar o delta em `app.py` (seção 6).
5. Substituir `.env.example` e `.github/workflows/main.yml`.
6. Configurar os Secrets no GitHub (se ainda não existirem):
   `GOOGLE_CREDENTIALS`, `SPREADSHEET_URL`, `DATABASE_URL`,
   `ESPELHAMENTO_PG_ATIVO`.
7. Rodar a suíte de testes e o Ruff localmente antes do push.

## 8. Como validar depois da migração

```bash
python -m pytest -q        # esperado: 199 passed
ruff check pipeline_dados/ tests/   # apenas aviso legado I001 em banco_dados.py
python -m py_compile app.py config.py pipeline_dados/*.py
```

> Nota: rodar a suíte **dentro de `migration_package/`** produz **193 passed**,
> porque este pacote inclui apenas os testes do 5C/Fase 4. Os 6 testes restantes
> pertencem a `tests/test_seguranca.py` (legado, não relacionado à migração) e já
> existem no GitHub — no repositório completo espera-se **199 passed**.
>
> As pastas `__pycache__/` presentes dentro de `migration_package/` são artefatos
> gerados por esta validação e estão cobertas pelo `.gitignore` do repositório
> (`__pycache__/`, `*.pyc`) — não devem ser versionadas.

## 9. Como reverter caso algo dê errado

- Nenhuma migração de dados é executada por estes arquivos.
- Se a integração quebrar, basta reverter `app.py` para a versão legada
  (removendo o bloco `if config.ESPELHAMENTO_PG_ATIVO:`) — o comportamento
  legado fica intacto.
- Para reverter as tabelas 5B no banco, usar `migracao_5b.reverter()` (somente
  remove as tabelas criadas por ela).
- Usar `git revert`/`git checkout` do commit da branch de migração.

## 10. Relação com a Fase 4

Este pacote NÃO encerra a Fase 4. Depois de aplicado no GitHub, o próximo passo
é a **execução real do Bloco 2** em ambiente com credenciais (Render ou GitHub
Actions):

1. Ativar `ESPELHAMENTO_PG_ATIVO=true` somente na execução controlada.
2. Ler `BD_FIIs`/`BD_Acoes` reais → transformação → espelhamento → Neon.
3. Validar FIIs, ações, inquilinos, NUMERIC/Decimal, INVALID/WARNING,
   idempotência, ausência de duplicação/resíduos.
4. Desativar `ESPELHAMENTO_PG_ATIVO` após o teste.

O Bloco 3 da Fase 4 NÃO deve ser iniciado até o Bloco 2 ser realmente concluído.
