# Fase 9 — Etapa 9.4: Hardening da API

Documento de hardening (codigo + testes + consolidacao). Nao cria endpoints,
nao altera banco, nao cria migration, nao introduz Redis, nao altera
coletores/scrapers/Telegram, nao cria Website. Data: 2026-09-06.

Base: Etapa 9.3 (validacao). Problemas abertos na 9.3 tratados aqui.
Working tree da etapa anterior: implementacao ja iniciada em
`api/rate_limit.py`, `config.py`, `api/__init__.py`, `.env.example`,
rotas de ativos/indicadores/alertas/documentos/mercado e
`tests/test_config_fase5.py`. Esta etapa auditou esse estado, preservou
o que estava correto e completou testes/documentacao.

---

## 1. Problema encontrado na 9.3

A 9.3 classificou a API como **NAO PRONTA PARA PRODUCAO**. Itens abertos:

1. `GET /mercado/cobertura` sem teto (ALTO) — percorria o catalogo inteiro.
2. Ausencia de rate limit (MEDIO) — login/register/leitura sem teto.
3. N+1 na serializacao com `ativo.ticker` (MEDIO).
4. `API_ENABLED` desabilitada por padrao (ALTO operacional / fail-closed).
5. Filtro `ticker` LIKE vs igualdade exata (MEDIO).
6. `GET /indicadores/<id>/historico` nao e serie temporal (MEDIO / modelo).

Nenhum CRITICO de vazamento/IDOR. Sheets fora de `api/`. 50 endpoints.

---

## 2. Solucao aplicada

Auditoria primeiro; so se alterou o que ainda faltava.

- Limites: `/mercado/cobertura` e `/mercado/cobertura-fii` ja paginam com
  teto 100/500 via `dependencias.obter_paginacao` + `services.mercado`.
- Rate limit: contador in-process (janela 60s), configuravel por ambiente,
  `healthz` fora, suite `TESTING` nao 429 a menos que
  `API_RATE_LIMIT_EM_TESTE`.
- N+1: `joinedload` ja presente nas listagens que serializam `ativo`.
- API_ENABLED: fail-closed preservado (`padrao` desligado). Nunca
  hardcodado ligado. Producao liga so por variavel de ambiente.
- Ticker: igualdade exata (normalizada) nas rotas de identificador.
- Historico: **PENDENTE** estrutural — unique `(ativo_id, indicador)`.
  Sem migration. `meta.serie_temporal` permanece desligado.

Docstring de `services/mercado.py` atualizado: ticker deixou de ser
descrito como parcial.

---

## 3. Arquivos alterados

Preservados da implementacao ja iniciada (auditados, nao revertidos):

- `api/rate_limit.py`
- `api/__init__.py`
- `config.py`
- `.env.example`
- `api/routes/ativos.py`
- `api/routes/indicadores.py`
- `api/routes/alertas.py`
- `api/routes/documentos.py`
- `api/routes/mercado.py`
- `services/mercado.py` (joinedload + teto cobertura)
- `pipeline_dados/cobertura.py` (limite/offset no catalogo)
- `tests/test_config_fase5.py`
- `tests/test_api.py`

Alteracoes desta continuacao:

- `api/rate_limit.py` — import de `current_app` no modulo; normaliza path
  (trailing slash); auth e API compartilham identidade por IP.
- `services/mercado.py` — docstring: ticker exato.
- `tests/test_fase94_hardening.py` — novo.
- `docs/FASE9_ETAPA94_HARDENING_API.md` — este arquivo.

Nao alterados: modelos, migrations, coletores, scrapers, Telegram,
Website, alertas novos, fontes novas.

---

## 4. Limites

Contrato HTTP unico (`api/dependencias.py`):

- padrao 100
- teto 500 (`LIMITE_MAXIMO`)
- `page` 1-indexado
- `page_size` tem precedencia sobre `limite`
- valores `<= 0` ou invalidos recaem no padrao
- `meta`: `total`, `page`, `page_size`, `has_next`, `next_page`, `retornados`

`GET /mercado/cobertura`:

- pagina o catalogo (`cobertura_catalogo(..., limite, offset)`)
- avalia so a pagina (`avaliar_tickers`)
- totais do universo permanecem no payload
- `page_size=9999` vira 500

`GET /mercado/cobertura-fii`:

- teto/offset sobre `Ativo` tipo FII
- filtro `ticker` avalia so aquele FII (igualdade exata)
- nao percorre a tabela inteira sem pagina

Impossibilidade de quantidade ilimitada: o teto HTTP e o teto do servico
sao o mesmo (500). Filtros existentes (ticker/tipo/data) permanecem.

---

## 5. Rate limit

Mecanismo: in-process, `collections.deque` + `threading.Lock` +
`time.monotonic`. Sem Redis, sem Flask-Limiter, sem infra nova.

Configuracao:

- `RATE_LIMIT_API_POR_MINUTO` (padrao 120)
- `RATE_LIMIT_AUTH_POR_MINUTO` (padrao 10) — so `/auth/login` e
  `/auth/register`
- `0` desliga o teto daquela classe

Comportamento:

- so prefixo `/api/v1`
- `GET /api/v1/healthz` isento
- identidade = `request.remote_addr` (nao le `X-Forwarded-For`)
- autenticacao nao e substituida: 401/403 continuam depois do teto
- `TESTING` sem `API_RATE_LIMIT_EM_TESTE` nao aplica 429 (suite intacta)

Risco restante (multiplas instancias Render): o contador e por processo.
N workers = N tetos independentes. Documentado; sem Redis nesta etapa.

---

## 6. N+1

Problema 9.3: serializadores leem `registro.ativo.ticker` sem eager load.

Estado auditado (ja resolvido; sem alteracao extra):

- `api/routes/indicadores.py` — `joinedload(IndicadorHistorico.ativo)`
- `api/routes/alertas.py` — `joinedload(AlertaEvento.ativo)`
- `api/routes/documentos.py` — `joinedload(DocumentosQualitativos.ativo)`
- `api/routes/ativos.py` — `joinedload(Ativo.perfil)`
- `services/mercado.py` — `_com_ativo` / `joinedload(modelo.ativo)`
- `services/carteira.py`, `notificacoes.py`, `ativos_acompanhados.py` —
  joinedload ja existente

Nao ha N+1 comprovado restante nas listagens HTTP da API. Cobertura ainda
avalia campo a campo por ticker da pagina (custo da pagina, nao N+1 de
relacionamento ORM).

---

## 7. API_ENABLED

Fail-closed preservado:

```
API_ENABLED = bool_ambiente("API_ENABLED", padrao=desligado)
```

- ausente/vazio/invalido = API desligada
- desenvolvimento permanece desligado
- producao liga com `API_ENABLED=true` no ambiente de deploy
- nunca hardcodar ligado no codigo
- nenhum segredo no codigo

`.env.example` documenta o padrao desligado e os tetos de rate limit.

---

## 8. Ticker exato

Filtros de identificador usam igualdade (`Ativo.ticker == valor.upper()`):

- `GET /ativos?ticker=`
- `GET /indicadores?ticker=`
- `GET /alertas?ticker=`
- `GET /documentos?ticker=`
- mercado: snapshots, dados-financeiros, freshness, cobertura-fii

`PETR4` encontra `PETR4`. `PETR4X`, `XPETR4` e substring `PETR` nao sao
tratados como `PETR4`. LIKE intencional (status de documentos no bot)
nao foi tocado.

---

## 9. Historico

`IndicadorHistorico`: unique `(ativo_id, indicador)`. Uma linha por
indicador do ativo (estado mais recente), nao serie temporal.

Corrigir de verdade exigiria nova tabela ou unique com
`data_referencia` — alteracao estrutural de banco.

**PENDENTE para etapa futura.** Sem migration. Sem modelo novo.
A rota documenta `meta.serie_temporal` desligado.

---

## 10. Testes

Arquivo novo: `tests/test_fase94_hardening.py`.

Cobertura:

- teto in-process e reset
- 429 HTTP quando `API_RATE_LIMIT_EM_TESTE`
- `TESTING` nao mascara producao (flag explicito)
- healthz isento
- teto de auth separado do teto da API
- sem bypass por `X-Forwarded-For`
- `/mercado/cobertura` pagina e recusa 9999
- `/mercado/cobertura-fii` teto 500
- ticker exato em ativos/indicadores/alertas/documentos/snapshots
- historico nao temporal
- API_ENABLED fail-closed
- joinedload nas listagens
- Sheets fora de `api/`
- 50 metodos HTTP (nenhum endpoint novo)

Resultados (2026-09-06):

- especificos 9.4: 16 passed (`tests/test_fase94_hardening.py`)
- regressao API/auth/autorizacao: 132 passed
- chaves/escopo/usuarios/config/mercado: 150 passed
- fases 8.2-8.6 + cobertura/semantica: 140 passed
- demais dominio 1: 209 passed
- demais dominio 2: 201 passed
- demais dominio 3: 340 passed
- total: **1172 passed**, 0 failed
- referencia 9.3: 1156 passed; delta = +16 testes da 9.4
- falhas de ambiente na coleta: dependencias ausentes no container
  (pytest/flask extras ja existentes no projeto). Nao e falha de codigo.

---

## 11. Riscos restantes

- Rate limit in-process nao agrega entre workers do Render.
- CORS / HTTPS continuam operacionais (fora desta etapa).
- `POST /auth/register` publico cria USER se a API estiver ligada.
- Historico de indicadores nao e serie (PENDENTE).
- Catalogo e inquilinos sem endpoint proprio (fora de escopo).
- `cobertura-fii` ainda avalia campo a campo na pagina (mitigado pelo teto).
- Sheets permanece fonte do bot Telegram (divergencia esperada).

Nao ha risco de a API ler Sheets, vazar hash/token ou escrever no banco
financeiro. Nenhuma alteracao de banco. Nenhum endpoint novo.

---

## 12. Confirmacoes

- Sheets fora da API.
- Nenhuma alteracao de banco / migration.
- Nenhum endpoint novo (50 metodos HTTP).
- Rate limit in-process aceito neste estagio.
- API_ENABLED fail-closed.
- Historico marcado PENDENTE.
