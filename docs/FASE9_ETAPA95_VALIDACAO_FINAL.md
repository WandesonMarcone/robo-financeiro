# Fase 9 — Etapa 9.5: Validacao final da API financeira

Documento de validacao final (somente analise e consolidacao). Nao altera
codigo, nao cria endpoints, nao altera banco, nao cria migration, nao
implementa historico temporal, nao corrige CORS/HTTPS/register publico.
Data da validacao: 2026-09-07.

Base: Etapa 9.1 (auditoria) + Etapa 9.2 (correcoes) + Etapa 9.3
(validacao) + Etapa 9.4 (hardening). Working tree no inicio desta etapa:
limpo (`git status` vazio; `git diff --stat` vazio). Branch: `master`.

Escopo desta etapa: confirmar o estado da camada HTTP em `api/` e dos
servicos que ela chama. Coletores, scrapers, Telegram e Website ficam
fora, exceto quando a API os consome. Nenhuma funcionalidade nova.

---

## 1. Escopo da Fase 9

A Fase 9 estabeleceu a Financial API como superficie HTTP unica de
leitura (e gestao de conta) sobre PostgreSQL/Neon.

- Prefixo: `/api/v1`
- Factory: `api.blueprint.criar_blueprint_api()` (14 Blueprints)
- Integracao aditiva em `main.py`: so registra rotas quando
  `config.API_ENABLED` e verdadeiro
- Padrao: **desabilitada** (`API_ENABLED=false`, fail-closed)
- Envelope: sucesso `{"status":"success","data":...,"meta":...}` + 200;
  erro `{"status":"error","data":null,"meta":{"error":"..."}}` + codigo HTTP

Camadas:

```
Cliente HTTP
  -> api/rate_limit.py (in-process, janela 60s)
  -> api/auth.py (X-API-Key | X-Session-Token)
  -> api/routes/* (query/corpo + permissao)
  -> services/* (mercado, usuarios, escopo, planos, ...)
  -> pipeline_dados.banco_dados (SQLAlchemy / PostgreSQL-Neon)
  -> api/serializadores.py
  -> api/respostas.py
```

O que a Fase 9 fez:

| Etapa | Resultado |
|---|---|
| 9.1 | Auditoria: 50 endpoints, Sheets fora de `api/`, lacunas de limite/RBAC |
| 9.2 | Correcoes: ADMIN `alertas.consultar`, paginacao, semantica 8.5 no JSON |
| 9.3 | Validacao: 1156 testes, API oficial de leitura, ainda nao producao publica |
| 9.4 | Hardening: teto em cobertura, rate limit in-process, ticker exato, N+1 |
| 9.5 | Validacao final (este documento): 1172 testes, 0 falhas, sem codigo novo |

O que a Fase 9 **nao** fez (intencional):

- historico temporal de indicadores (PENDENTE estrutural)
- migration / alteracao de banco
- Redis / rate limit distribuido
- CORS / HTTPS na app Flask
- restricao de `POST /auth/register` publico
- migracao do Telegram de Sheets para `services.mercado`
- Website
- endpoints novos (catalogo, inquilinos, GET `/ativos/<id>`)

---

## 2. Inventario: 50 endpoints

Total confirmado nesta etapa: **50** metodos HTTP distintos em
`api/routes/`. Nenhum endpoint novo desde a 9.1. Contagem por `@(bp.get|post|patch|delete)` e pelo teste
`test_nenhum_endpoint_novo_na_9_4`.

### 2.1 Sistema e autenticacao (4)

| Metodo | Rota | Auth |
|---|---|---|
| GET | `/api/v1/healthz` | publica |
| POST | `/api/v1/auth/register` | publica (forca USER) |
| POST | `/api/v1/auth/login` | publica |
| POST | `/api/v1/auth/logout` | `X-Session-Token` |

### 2.2 Conta e usuarios (13)

| Metodo | Rota | Authz |
|---|---|---|
| GET | `/api/v1/me` | `conta.propria` |
| GET | `/api/v1/me/plano` | `conta.propria` |
| GET | `/api/v1/usuarios` | `usuarios.ler` |
| GET | `/api/v1/usuarios/<id>` | `usuarios.ler` |
| POST | `/api/v1/usuarios` | `usuarios.criar` |
| PATCH | `/api/v1/usuarios/<id>` | proprio ou `usuarios.criar` |
| POST | `/api/v1/usuarios/<id>/ativar` | `usuarios.ativar` |
| POST | `/api/v1/usuarios/<id>/desativar` | `usuarios.desativar` |
| POST | `/api/v1/usuarios/<id>/papel` | `usuarios.alterar_papel` |
| POST | `/api/v1/usuarios/<id>/plano` | SUPERADMIN |
| POST | `/api/v1/usuarios/<id>/telegram` | `telegram.administrar` |
| DELETE | `/api/v1/usuarios/<id>/telegram` | `telegram.administrar` |
| POST | `/api/v1/usuarios/<id>/sessoes/revogar` | `usuarios.desativar` |

### 2.3 API keys, preferencias, carteira, acompanhados, notificacoes (21)

| Metodo | Rota | Isolamento |
|---|---|---|
| POST | `/api/v1/api-keys` | dono = `g.usuario` |
| GET | `/api/v1/api-keys` | 404 cruzado |
| GET | `/api/v1/api-keys/<id>` | 404 cruzado |
| DELETE | `/api/v1/api-keys/<id>` | 404 cruzado |
| GET | `/api/v1/preferencias` | 1:1 |
| PATCH | `/api/v1/preferencias` | rejeita `usuario_id` |
| POST | `/api/v1/preferencias/restaurar` | proprio |
| GET | `/api/v1/carteira` | escopo |
| POST | `/api/v1/carteira` | ignora `usuario_id` |
| GET | `/api/v1/carteira/<id>` | 404 cruzado |
| PATCH | `/api/v1/carteira/<id>` | 404 cruzado |
| DELETE | `/api/v1/carteira/<id>` | 404 cruzado |
| GET | `/api/v1/ativos-acompanhados` | escopo |
| POST | `/api/v1/ativos-acompanhados` | ignora `usuario_id` |
| GET | `/api/v1/ativos-acompanhados/<id>` | 404 cruzado |
| DELETE | `/api/v1/ativos-acompanhados/<id>` | 404 cruzado |
| GET | `/api/v1/notificacoes` | usuario da sessao |
| GET | `/api/v1/notificacoes/<id>` | 404 cruzado |
| POST | `/api/v1/notificacoes/ler-todas` | proprio |
| POST | `/api/v1/notificacoes/<id>/lida` | 404 cruzado |
| DELETE | `/api/v1/notificacoes/<id>` | 404 cruzado |

### 2.4 Dados financeiros (12)

| Metodo | Rota | Fonte PG |
|---|---|---|
| GET | `/api/v1/ativos` | `ativos` + `ativos_perfil` |
| GET | `/api/v1/mercado/snapshots` | `snapshots_fiis` / `snapshots_acoes` |
| GET | `/api/v1/mercado/snapshots/mais-recente` | idem (1 registro) |
| GET | `/api/v1/mercado/dados-financeiros` | `dados_financeiros_*` |
| GET | `/api/v1/mercado/freshness` | snapshots + contabil + docs |
| GET | `/api/v1/mercado/cobertura` | catalogo + persistido (paginado) |
| GET | `/api/v1/mercado/cobertura-fii` | campos FII 8.6 (paginado) |
| GET | `/api/v1/indicadores` | `indicadores_historico` |
| GET | `/api/v1/indicadores/<ativo_id>/historico` | estado atual por indicador |
| GET | `/api/v1/alertas` | `alertas_eventos` |
| GET | `/api/v1/documentos` | metadados (sem texto/IA) |
| GET | `/api/v1/relatorios` | COUNTs agregados |

Fonte: PostgreSQL/Neon em **49** endpoints; sem persistencia em **1**
(`GET /healthz`); Google Sheets na API: **0**.

---

## 3. Resultados dos testes

Execucao em 2026-09-07. Dependencias de ambiente instaladas apenas no
container de validacao (pytest, Flask, SQLAlchemy, gspread, yfinance,
PyPDF2, google-auth). Nenhuma dependencia nova no projeto.

### 3.1 Suíte completa

```
python3 -m pytest tests -q --tb=line
1172 passed, 1 warning in 523.37s
```

- **1172 passed**
- **0 failed**
- **0 errors**
- 1 warning: `PyPDF2` deprecado (legado, fora da API)

Referencia 9.4: 1172 passed. Delta desta etapa: **0** (nenhum teste
novo, nenhuma regressao).

### 3.2 Blocos relevantes da API

| Bloco | Arquivos | Resultado |
|---|---|---|
| Hardening 9.4 | `tests/test_fase94_hardening.py` | 16 passed |
| API HTTP | `tests/test_api.py` | 42 passed |
| Auth / RBAC / isolamento | `test_fase92_api`, `test_auth_web`, `test_autorizacao`, `test_escopo`, `test_usuarios_api`, `test_chaves_api`, `test_chaves_api_http` | 190 passed |
| Planos / mercado / config / sessoes | `test_planos_api`, `test_planos_enforcement_api`, `test_mercado_service`, `test_config_fase5`, `test_sessoes`, `test_seguranca` | 106 passed |
| Fases 8.2–8.6 | `test_fase82_*` … `test_fase86_*` | 99 passed |
| Demais dominio (batch 1) | espelhamento, catalogo, seed, auditoria, dispatcher, preferencias, planos, llm, qualidade | 395 passed |
| Demais dominio (batch 2) | motor, carteira, notificacoes, migracao 5b, integracao 5C, CVM 8.9 | 324 passed |

Cobertura confirmada pelos testes (nao so documentacao):

- autenticacao (`X-API-Key`, `X-Session-Token`, 401 indistinguivel)
- autorizacao/RBAC (USER/ADMIN/SUPERADMIN/VISITOR)
- isolamento multiusuario (404 cruzado, `usuario_id` ignorado)
- mercado / cobertura / freshness
- serializacao (None permanece None; semantica 8.5; documentos sem texto)
- rate limit in-process (`429` com `API_RATE_LIMIT_EM_TESTE`)
- `API_ENABLED` fail-closed
- ticker por igualdade exata
- regressoes 8.2–8.6 (NULL != 0, CNPJ, proveniencia, freshness, semantica, INF_MENSAL)

---

## 4. Seguranca e autorizacao

Confirmado no codigo e nos testes:

- Cabecalhos: `X-API-Key` (prioridade) e `X-Session-Token`
- Falha de autenticacao: 401 `"Nao autenticado."` (chave inexistente,
  expirada ou revogada nao se distinguem)
- Hash de senha / sessao / API Key nunca na resposta
- Chave bruta so no POST de criacao
- Matriz `PAPEL_PERMISSOES`: SUPERADMIN `"*"`; ADMIN consulta dados e
  alertas globais, nao promove a SUPERADMIN; USER = consulta financeira
  + escopo proprio; VISITOR autenticado nao le mercado
- SUPERADMIN protegido contra ADMIN
- Login: credenciais invalidas e usuario desativado = mesma 401
- Excecao nao tratada = 500 generico, sem stack trace
- Documentos: sem `texto_extraido`, `resumo_ia`, `log_erro`
- Rate limit nao substitui autenticacao: 401/403 continuam depois do teto
- Identidade do rate limit = `request.remote_addr` (nao le `X-Forwarded-For`)

Nenhum CRITICO de vazamento, IDOR ou BOLA encontrado nesta validacao.

---

## 5. Isolamento multiusuario

`services/escopo.py` via `buscar_recurso_escopado`:

- Recurso inexistente e recurso de terceiro = mesmo 404
- `usuario_id` enviado pelo cliente e ignorado nas criacoes
- Preferencias 1:1; `usuario_id` no payload = 400
- Carteira, acompanhados, notificacoes e api-keys isolados por dono
- Plano nunca aceito em cadastro/PATCH de usuario comum
- ADMIN le alertas globais de mercado/qualidade, nao dados privados
  de outro usuario

Testes de isolamento (`test_escopo.py`, `test_usuarios_api.py`,
`test_chaves_api_http.py`, `test_auth_web.py`, `test_fase92_api.py`)
passaram sem falha.

---

## 6. Paginacao e limites

Contrato HTTP unico (`api/dependencias.py`):

- padrao 100
- teto 500 (`LIMITE_MAXIMO`)
- `page` 1-indexado
- `page_size` tem precedencia sobre `limite`
- valores `<= 0` ou invalidos recaem no padrao
- `meta`: `total`, `page`, `page_size`, `has_next`, `next_page`, `retornados`

Listagens paginadas (incluindo as que a 9.1 apontava sem teto):

- `/usuarios`, `/api-keys`, `/carteira`, `/ativos-acompanhados`,
  `/notificacoes`, `/ativos`, `/mercado/snapshots`,
  `/mercado/dados-financeiros`, `/mercado/cobertura`,
  `/mercado/cobertura-fii`, `/indicadores`,
  `/indicadores/<id>/historico`, `/alertas`, `/documentos`

`GET /mercado/cobertura` pagina o catalogo e avalia so a pagina
(`page_size=9999` vira 500). `GET /mercado/cobertura-fii` aplica o
mesmo teto. Impossibilidade de quantidade ilimitada nas listagens HTTP.

Sem paginacao (por desenho): `/me`, preferencias, itens unicos
(`snapshots/mais-recente`, freshness, GET por id), mutacoes, `/healthz`,
`/relatorios` (agregado).

---

## 7. Rate limit (in-process)

Mecanismo: `api/rate_limit.py` — `collections.deque` + `threading.Lock`
+ `time.monotonic`. Sem Redis, sem Flask-Limiter, sem infra nova.

- `RATE_LIMIT_API_POR_MINUTO` (padrao 120)
- `RATE_LIMIT_AUTH_POR_MINUTO` (padrao 10) — so `/auth/login` e
  `/auth/register`
- `0` desliga o teto daquela classe
- so prefixo `/api/v1`
- `GET /api/v1/healthz` isento
- `TESTING` sem `API_RATE_LIMIT_EM_TESTE` nao aplica 429 (suite intacta)

**Limitacao documentada:** o contador e por processo. N workers = N
tetos independentes. Aceito neste estagio. Redis fica para fase futura.

---

## 8. API_ENABLED fail-closed

```
API_ENABLED = bool_ambiente("API_ENABLED", padrao=False)
```

- ausente / vazio / invalido = API desligada
- nunca hardcodado ligado no codigo (`API_ENABLED = True` inexistente)
- `.env.example`: `API_ENABLED=false`
- producao liga somente com `API_ENABLED=true` no ambiente de deploy
- quando desligada, webhook Telegram e pagina raiz permanecem intactos

Teste `test_api_enabled_fail_closed_nao_e_hardcoded_true` passou.

---

## 9. Sheets fora da API

Busca em `api/**/*.py` por `gspread`, `SPREADSHEET`, `worksheet`,
`BD_FIIs`, `BD_Acoes`, `BD_Logs`, `conectar_gspread`: **0 ocorrencias**.

Teste `test_api_nao_usa_google_sheets` passou.

Sheets permanece no legado **fora** de `/api/v1`
(`services/planilhas.py`, `services/dashboard_menus.py`, scrapers,
fallback CVM). Nao e caminho HTTP. Nao foi migrado. Nao precisa ser
desligado para a API operar. Divergencia temporaria API vs Telegram
e esperada.

---

## 10. Serializacao: nenhum dado inventado

`api/serializadores.py`:

- `_numero`: Decimal -> float; **None permanece None**
- zero real permanece `0.0`
- semantica 8.5 viaja ao lado do numero (`ZERO` / `AUSENTE` /
  `NAO_APLICAVEL` / `INVALIDO` / `PRESENTE`)
- datas ISO 8601
- `data_referencia`, `data_coleta`, `fonte`, `fonte_primaria`,
  `url_origem` permanecem quando existem
- unidades e escala rotulam o valor persistido; **nao convertem** o numero
- dois VPAs / dois DYs rotulados em `proveniencia` (snapshot vs CVM)

Nao ha preenchimento de campos ausentes com zero, media ou placeholder
financeiro. O unico `or 0` observado e `tentativas` de notificacao
(contador operacional, nao dado de mercado).

---

## 11. Ausencia de migration

Nenhuma migration Alembic. Nenhum `CREATE TABLE` / `ALTER TABLE` novo
nesta fase na arvore da API. Modelos ORM nao alterados na 9.4/9.5.

`IndicadorHistorico` permanece com
`UniqueConstraint("ativo_id", "indicador")` — uma linha por indicador
do ativo (estado mais recente), nao serie temporal.

Working tree desta etapa: apenas este documento criado. Codigo da API
intacto.

---

## 12. Historico temporal: PENDENTE

`GET /indicadores/<ativo_id>/historico` **nao** e serie temporal.

- unique `(ativo_id, indicador)`
- `meta.serie_temporal = false` (documentado na rota e nos testes)
- corrigir de verdade exigiria nova tabela ou unique com
  `data_referencia` — alteracao estrutural de banco

**PENDENTE para fase futura.** Sem migration. Sem modelo novo. Nao
bloqueia o encerramento da Fase 9 como camada de leitura do estado
persistido.

---

## 13. N+1

`joinedload` presente nas listagens que serializam `ativo`:

- `api/routes/indicadores.py`
- `api/routes/alertas.py`
- `api/routes/documentos.py`
- `api/routes/ativos.py` (`Ativo.perfil`)
- `services/mercado.py`
- `services/carteira.py`, `notificacoes.py`, `ativos_acompanhados.py`

Teste `test_listagens_carregam_ativo_com_joinedload` passou. Cobertura
ainda avalia campo a campo por ticker da pagina (custo da pagina, nao
N+1 de relacionamento ORM).

---

## 14. Ticker exato

Filtros de identificador usam igualdade (`Ativo.ticker == valor.upper()`):

- `GET /ativos?ticker=`
- `GET /indicadores?ticker=`
- `GET /alertas?ticker=`
- `GET /documentos?ticker=`
- mercado: snapshots, dados-financeiros, freshness, cobertura-fii

`PETR4` encontra `PETR4`. `PETR4X`, `XPETR4` e substring `PETR` nao
sao tratados como `PETR4`. Confirmado em `tests/test_fase94_hardening.py`.

---

## 15. Pendencias para fases futuras

Nao bloqueiam o encerramento da Fase 9. Nao corrigir agora.

1. Historico temporal de indicadores (PENDENTE estrutural / migration).
2. Rate limit in-process nao agrega entre workers (Redis futuro).
3. CORS / HTTPS na app Flask (operacional de producao publica).
4. `POST /auth/register` publico cria USER se a API estiver ligada
   (politica de produto).
5. Catalogo (`ativos_catalogo`) e inquilinos sem endpoint proprio.
6. Sem GET `/ativos/<id>`.
7. Telegram ainda le Sheets (`dashboard_menus`); divergencia esperada.
8. VISITOR sem rota `publico.*`.
9. Criacoes HTTP devolvem 200 + `meta.criado`, nao 201.
10. `cobertura-fii` avalia campo a campo na pagina (mitigado pelo teto).

Nenhum desses e falha da Etapa 9.5. Nenhum e regressao de seguranca
evidenciada nos 1172 testes.

---

## 16. Confirmacoes explicitas

- [x] Nenhum endpoint le Google Sheets diretamente.
- [x] Nenhum dado financeiro e inventado para preencher campos ausentes.
- [x] Sem alteracao / migration de banco nesta etapa.
- [x] Historico de indicadores continua marcado como PENDENTE
      (`meta.serie_temporal = false`).
- [x] Rate limit continua documentado como in-process (por processo).
- [x] `API_ENABLED` continua fail-closed.
- [x] Nenhum endpoint novo (50 metodos HTTP).
- [x] Nenhuma alteracao de arquitetura.
- [x] Sem regressao funcional ou de seguranca evidente (1172/1172).

---

## 17. Veredito final

A API financeira da Fase 9 esta **completa como camada oficial de
acesso aos dados persistidos** (PostgreSQL/Neon):

- 50 endpoints
- envelope estavel
- RBAC e isolamento multiusuario
- paginacao com teto 100/500
- rate limit in-process
- ticker por igualdade exata
- N+1 mitigado com `joinedload`
- contrato 8.5 no JSON
- Sheets fora do caminho HTTP
- `API_ENABLED` fail-closed
- **1172 testes passando, 0 falhas**

Nao e superficie publica endurecida para internet aberta (CORS/HTTPS,
register publico, rate limit distribuido e historico temporal ficam
para fases futuras). Pode ser ligada operacionalmente com
`API_ENABLED=true` em ambiente controlado.

**FASE 9 ENCERRADA** como API financeira de leitura e gestao de conta.

Classificacao operacional: **pronta como camada oficial interna /
autenticada**; **nao pronta como API publica aberta** (pendencias da
secao 15).

Nenhuma falha real encontrada. Nenhum codigo corrigido. Unico artefato
desta etapa: este documento.
