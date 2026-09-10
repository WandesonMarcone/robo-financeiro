# Fase 11 — Etapa 11.2: CORS, deploy e contrato de consumo

Documento da implementacao real (codigo + testes + contrato). Nao cria
frontend, nao cria endpoints, nao altera banco, nao migra Sheets, nao
avanca para a 11.3. Data: 2026-09-09.

Base: Etapa 11.1 (auditoria web). 50 endpoints, PostgreSQL, Sheets fora
de `api/`, autenticacao por `X-Session-Token` / `X-API-Key`.

---

## 1. Objetivo

Preparar `/api/v1` para um Website **hospedado em origem distinta**,
sem segundo backend e sem duplicar regras financeiras.

Regra:

```
Website (origem configurada) -> HTTPS -> Flask /api/v1 -> PostgreSQL
```

Token somente em header. Nunca na URL.

---

## 2. CORS

### 2.1 Comportamento

Implementado em `api/cors.py`, registrado por `integrar_api` **somente
quando a API esta ligada**. Sem Flask-CORS. Sem wildcard.

| Situacao | Resultado |
|---|---|
| `API_CORS_ORIGINS` vazio (padrao) | nenhum `Access-Control-Allow-Origin` |
| Origin na allowlist | ecoa essa origem + `Allow-Credentials: true` |
| Origin fora / `*` / ausente | sem cabecalhos CORS (browser bloqueia) |
| Preflight OPTIONS permitido | 204 + cabecalhos CORS (nao autentica) |
| Preflight OPTIONS recusado | 403, sem CORS |
| Rota fora de `/api/v1` | CORS nao se aplica |
| `API_ENABLED=false` | CORS nem e registrado |

Allowlist: env `API_CORS_ORIGINS` (CSV). Parse em
`config.origens_cors_permitidas`: trim, remove `/` final, descarta `*`
e vazio, sem duplicata. Comparacao **exata** (scheme + host + porta).

Cabecalhos permitidos no preflight: `Accept`, `Content-Type`,
`X-API-Key`, `X-Session-Token`. Metodos: GET, POST, PATCH, DELETE,
OPTIONS. `Vary: Origin`. Credentials **nunca** com `*`.

### 2.2 Configuracao

```
# Desenvolvimento (exemplo)
API_CORS_ORIGINS=http://localhost:5173

# Producao (somente a origem HTTPS do Website)
API_CORS_ORIGINS=https://app.exemplo.com
```

Producao **nao** usa `*`. Valor `*` na env e ignorado. Varias origens:
separadas por virgula.

### 2.3 O que o Website deve enviar

- `Origin` automatico do browser.
- Credencial: `X-Session-Token` (apos login) ou `X-API-Key`.
- `Content-Type: application/json` em POST/PATCH.

Nao enviar token em query, path ou cookie. Cookie HttpOnly **nao**
existe nesta etapa.

---

## 3. API_ENABLED (fail-closed)

Inalterado na semantica da Fase 9:

```
API_ENABLED = bool_ambiente("API_ENABLED", padrao=False)
```

- ausente / vazio / invalido = **desligada**
- nunca hardcodado `True` em `config.py`
- `.env.example`: `API_ENABLED=false`
- quando desligada: nenhuma rota `/api/v1`, nenhum CORS, nenhum rate
  limit da API; webhook Telegram e `/` permanecem
- quando ligada: `integrar_api(app)` registra blueprint + CORS + rate
  limit + 404/405 JSON do prefixo

Ativacao **explicita** no ambiente de deploy do Website:

```
API_ENABLED=true
API_CORS_ORIGINS=https://<origem-do-website>
```

Nao ha modo "producao ligada por padrao".

---

## 4. Seguranca do consumo web

Confirmado no codigo desta etapa:

- autenticacao so em `X-API-Key` e `X-Session-Token` (`api/auth.py`);
- token na query **nao** autentica (teste dedicado);
- RBAC (`services/autorizacao`) e escopo (`services/escopo`) intactos;
- 404 cruzado em recurso privado de terceiro;
- serializadores sem senha, hash, token, texto/IA de documento;
- regras financeiras nao alteradas;
- 50 endpoints (nenhum novo).

---

## 5. Contrato Website -> API

Envelope unico:

- sucesso: HTTP 200, `{"status":"success","data":...,"meta":...}`
- erro: `{"status":"error","data":null,"meta":{"error":"..."}}`

Paginacao (listagens): `page` (1-indexado), `page_size` (precede
`limite`), teto 500. `meta`: `total`, `page`, `page_size`, `has_next`,
`next_page`, `retornados`.

Erros HTTP comuns: 400 filtro/corpo, 401 nao autenticado, 403 sem
permissao, 404 recurso, 405 metodo, 429 rate limit, 500 generico.

Estados de dado financeiro: numero presente, `0.0` = zero real, `null`
= ausencia. Usar `campos.<indicador>.semantica` (`PRESENTE` / `ZERO` /
`AUSENTE` / `NAO_APLICAVEL` / `INVALIDO`). Nao substituir `null` por 0
no cliente.

Freshness (quando a tela pedir saude do dado):
`GET /mercado/freshness?ticker=` — categorias com `FRESH` / `STALE` /
`MISSING` e `sla_segundos`. Ticker obrigatorio.

Auth das rotas abaixo, salvo as publicas: header `X-Session-Token`
(login web) ou `X-API-Key`. USER e SUPERADMIN acessam o escopo proprio.
ADMIN **nao** tem carteira/preferencias/notificacoes/acompanhados
(403) — operador, nao Dashboard pessoal (11.1).

### 5.1 Login / logout / me

| Metodo | Rota | Auth | Params | Paginacao | Data | Erros |
|---|---|---|---|---|---|---|
| POST | `/api/v1/auth/register` | publica | JSON `nome`, `email`, `senha` (>= min) | nao | usuario (sem senha); `meta.criado` | 400 cadastro; papel/plano no corpo ignorados/rejeitados |
| POST | `/api/v1/auth/login` | publica | JSON `email`, `senha` | nao | `{token, usuario}` — token bruto **1x** | 401 generico |
| POST | `/api/v1/auth/logout` | `X-Session-Token` | header | nao | `{logout: true}` | 401 sem header |
| GET | `/api/v1/me` | `conta.propria` | — | nao | id, nome, email, papel, plano, ativo, telegram_vinculado, datas | 401/403 |
| GET | `/api/v1/me/plano` | `conta.propria` | — | nao | entitlements/limites (`services.planos`) | 401/403 |
| GET | `/api/v1/healthz` | publica | — | nao | `{status: ok, api: v1}` | — |

Rate limit auth: 10/min por IP em login e register. API geral: 120/min.

Cliente: guardar `token` fora da URL; enviar `X-Session-Token` em toda
rota protegida; no 401, relogar.

### 5.2 Dashboard (composicao — sem `/dashboard`)

| Bloco | Metodo | Rota | Authz | Params | Paginacao | Notas |
|---|---|---|---|---|---|---|
| Identidade | GET | `/me` | `conta.propria` | — | nao | |
| Plano/limites | GET | `/me/plano` | `conta.propria` | — | nao | teto carteira/acompanhados |
| Posicoes | GET | `/carteira` | `carteira.propria` | — | sim | `valor_investido` persistido; nao e MtM |
| Watchlist | GET | `/ativos-acompanhados` | `ativos.proprios` | — | sim | |
| Inbox | GET | `/notificacoes` | `notificacoes.consultar` | `nao_lidas=true`, `tipo`, `status` | sim | `usuario_id` ignorado |
| Cotacao | GET | `/mercado/snapshots/mais-recente` | `dados.consultar` | `ticker` ou `ativo_id`, `tipo_ativo` | 1 registro | 404 se nao houver |
| Lista cotacoes | GET | `/mercado/snapshots` | `dados.consultar` | ticker, tipo, data, page | sim | cruzar no cliente com a carteira |
| Saude | GET | `/mercado/freshness` | `dados.consultar` | **ticker obrigatorio** | nao | FRESH/STALE/MISSING |
| Alertas | GET | `/alertas` | `alertas.consultar` | ticker, tipo, severidade, page | sim | eventos globais de mercado |
| Resumo plataforma | GET | `/relatorios` | `relatorios.consultar` | — | nao | COUNTs globais — **nao** patrimonio do usuario |

Patrimonio da tela = soma de `valor_investido` da carteira. Se exibir
cotacao, `qtd * snapshot.preco` e rotulo de mercado no cliente, nao
regra nova no backend.

### 5.3 Ativos

| Metodo | Rota | Authz | Params | Paginacao | Data |
|---|---|---|---|---|---|
| GET | `/api/v1/ativos` | `dados.consultar` | `tipo=ACAO\|FII`, `ticker` exato, page | sim | id, ticker, cnpj, tipo, setor, tipo_fii |
| GET | `/api/v1/mercado/snapshots` | `dados.consultar` | ticker, ativo_id, tipo_ativo, data_referencia | sim | preco, dy, pvp, vpa, proveniencia, `campos` |
| GET | `/api/v1/mercado/snapshots/mais-recente` | `dados.consultar` | ticker/ativo_id/tipo | nao | 1 snapshot ou 404 |
| GET | `/api/v1/mercado/dados-financeiros` | `dados.consultar` | + `tipo_doc` ITR/DFP | sim | CVM; VPA/DY mensal distintos do snapshot |
| GET | `/api/v1/mercado/cobertura` | `dados.consultar` | page | sim no catalogo | universo vs coletado |
| GET | `/api/v1/mercado/cobertura-fii` | `dados.consultar` | ticker opcional, page | sim | campos 8.6 + freshness aninhado |
| GET | `/api/v1/mercado/freshness` | `dados.consultar` | ticker obrigatorio | nao | por categoria |

Nao ha `GET /ativos/<id>`. Detalhe = `?ticker=PETR4` (igualdade exata).
Nao misturar `snapshot.vpa` com `valor_patrimonial_cotas`.

CRUD privado (Dashboard/Ativos do usuario):

| Metodo | Rota | Authz |
|---|---|---|
| POST/GET/GET id/PATCH/DELETE | `/carteira` | `carteira.propria` |
| POST/GET/GET id/DELETE | `/ativos-acompanhados` | `ativos.proprios` |

POST ignora `usuario_id` do corpo. Terceiro = 404. Limite de plano =
400.

### 5.4 Indicadores

| Metodo | Rota | Authz | Params | Paginacao | Estado |
|---|---|---|---|---|---|
| GET | `/api/v1/indicadores` | `indicadores.consultar` | ativo_id, ticker exato, indicador, tipo_ativo, page | sim | valor_atual/anterior, semantica, unidade, escala |
| GET | `/api/v1/indicadores/<ativo_id>/historico` | `historico.consultar` | page | sim | estado atual por indicador; **`meta.serie_temporal=false`** |

404 se `ativo_id` inexistente no historico. Nao desenhar serie
temporal. Card/tabela somente.

### 5.5 Documentos

| Metodo | Rota | Authz | Params | Paginacao | Data |
|---|---|---|---|---|---|
| GET | `/api/v1/documentos` | `documentos.consultar` | ativo_id, ticker, tipo_documento, status, page | sim | id, ticker, datas, tipo, **url_pdf**, assunto, id_b3, status_processamento |

Nunca `texto_extraido`, `resumo_ia`, `log_erro`. Website abre `url_pdf`.
Sem `GET /documentos/<id>` — filtrar a lista.

### 5.6 Alertas

| Metodo | Rota | Authz | Params | Paginacao | Data |
|---|---|---|---|---|---|
| GET | `/api/v1/alertas` | `alertas.consultar` | ativo_id, ticker, tipo (`QUALIDADE\|MERCADO\|CRITICO`), severidade, tipo_ativo, page | sim | evento, indicador, valores, regra, motivo, severidade, recomendacao, telegram_enviado |

Somente leitura. Geracao e do motor, nao do Website.

Inbox pessoal (nao e o mesmo recurso que `/alertas`):

| Metodo | Rota | Authz |
|---|---|---|
| GET | `/notificacoes` | `notificacoes.consultar` |
| GET | `/notificacoes/<id>` | idem; 404 cruzado |
| POST | `/notificacoes/ler-todas` | proprio |
| POST | `/notificacoes/<id>/lida` | 404 cruzado |
| DELETE | `/notificacoes/<id>` | 404 cruzado |

### 5.7 Preferencias / notificacoes (configuracao)

| Metodo | Rota | Authz | Corpo | Data |
|---|---|---|---|---|
| GET | `/api/v1/preferencias` | `preferencias.proprias` | — | cria defaults se ausente |
| PATCH | `/api/v1/preferencias` | idem | booleanos/enums; `usuario_id` = 400 | flags web/telegram, frequencia, mercado_acoes/fiis |
| POST | `/api/v1/preferencias/restaurar` | idem | — | defaults; `meta.restaurado` |

Campos web relevantes: `web_ativo`, `notificacoes_*`,
`frequencia_notificacoes` (`imediata|diaria|semanal|desativada`),
`mercado_acoes`, `mercado_fiis`. Gating 10.3 ja no backend — o Website
so persiste.

---

## 6. Deploy (checklist)

1. PostgreSQL/Neon em `DATABASE_URL`.
2. `API_ENABLED=true` **somente** neste ambiente.
3. `API_CORS_ORIGINS` = origem HTTPS do Website (dev: localhost).
4. HTTPS no proxy; Flask nao configura TLS.
5. Nao ligar CORS `*`. Nao commitar secrets.
6. Rate limits ja ativos quando a API liga.

Sheets continua no legado (Telegram/scrapers). O Website **nao** le
Sheets.

---

## 7. O que esta etapa nao fez

- frontend / SPA
- endpoints novos (50 permanece)
- cookie, Bearer, refresh, reset de senha
- migration / historico temporal
- Redis / CORS em rotas nao-API
- Etapa 11.3

---

## 8. Arquivos alterados

| Arquivo | Mudanca |
|---|---|
| `api/cors.py` | **novo** — allowlist, preflight, after_request |
| `api/__init__.py` | `registrar_cors` quando a API liga |
| `api/auth.py` | comentario: credencial so em header |
| `config.py` | `origens_cors_permitidas`, `API_CORS_ORIGINS` |
| `.env.example` | `API_CORS_ORIGINS=` (vazio, fail-closed) |
| `tests/test_fase112_cors_deploy.py` | **novo** — CORS, API_ENABLED, auth, escopo |
| `tests/test_config_fase5.py` | padrao vazio + parse da allowlist |
| `docs/FASE11_ETAPA112_CORS_DEPLOY_CONTRATO.md` | este documento |

Nenhum modelo, rota de recurso, serializador financeiro ou teste
antigo foi alterado para mascarar falha.

---

## 9. Testes

Execucao em 2026-09-09. Nenhum teste antigo alterado para mascarar falha.

| Bloco | Arquivos | Resultado |
|---|---|---|
| 11.2 + config | `test_fase112_cors_deploy`, `test_config_fase5` | 30 passed |
| Regressao API/auth/security | `test_api`, `test_auth_web`, `test_fase94_hardening`, `test_autorizacao`, `test_escopo`, `test_sessoes`, `test_chaves_api`, `test_seguranca` | 210 passed |

**Total desta validacao: 240 passed, 0 failed, 0 errors.** Warning unico:
`PyPDF2` deprecado (legado, fora da API).

Cobertura 11.2: CORS permitido, CORS bloqueado, allowlist vazia, `*`
ignorado, preflight 204/403, `API_ENABLED` false/true, token na query
rejeitado, header aceito, 401, 404 cruzado, 50 endpoints.

---

## 10. Veredito

**Etapa 11.2: CONCLUIDA.**

A API pode ser consumida por um Website separado com allowlist CORS e
`API_ENABLED=true` no deploy. Contrato das cinco telas usa so os 50
endpoints existentes. Fail-closed preservado. Sem frontend. Sem 11.3.
