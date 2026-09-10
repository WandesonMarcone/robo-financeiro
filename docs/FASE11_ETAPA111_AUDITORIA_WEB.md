# Fase 11 — Etapa 11.1: Auditoria e arquitetura web

Documento de auditoria (somente analise). Nao altera codigo, nao cria
frontend, nao cria endpoints, nao altera banco, nao migra Google Sheets
e nao avanca para a Etapa 11.2. Data da auditoria: 2026-09-09. Commit
base: `eb84d1a` (`Initial commit`). Sem `.gitmodules`.

Escopo: preparar o projeto para um Website que consome **exclusivamente**
a API financeira existente (`/api/v1`). Fontes de coleta, scrapers,
Telegram e Sheets ficam fora, exceto quando o futuro frontend poderia
toca-los — neste caso a regra e recusar.

Regra arquitetural desta fase:

```
Website -> API (/api/v1) -> PostgreSQL
```

O Website **nao** le Google Sheets. O Website **nao** duplica regras
financeiras do backend. Nenhuma regra de indicador, cobertura,
freshness, alerta ou plano deve ser reimplementada no cliente.

---

## 1. Diagnostico

A Fase 9 deixou a Financial API como superficie HTTP oficial de leitura
e gestao de conta sobre PostgreSQL/Neon (50 endpoints, envelope estavel,
RBAC, isolamento, paginacao, rate limit in-process, contrato 8.5 no
JSON). A Fase 10 endureceu Telegram/alertas **sem** criar rotas HTTP
novas.

Para um Website autenticado, a API **ja e suficiente como backend** das
telas de Dashboard, Ativos, Indicadores, Documentos e Alertas, desde que
o cliente:

1. fale apenas com `/api/v1`;
2. autentique com `X-Session-Token` (login web) ou `X-API-Key`;
3. componha as telas a partir dos endpoints existentes (nao ha BFF);
4. nunca calcule indicador, P/VP, DY, freshness ou alerta no browser.

O que **nao** esta pronto e a experiencia de producao publica do
browser: CORS ausente, sessao so em cabecalho (sem cookie HttpOnly),
`API_ENABLED=false` por padrao, cadastro publico irrestrito, ADMIN sem
escopo de conta propria (carteira/preferencias/notificacoes), e
historico temporal de indicadores ainda PENDENTE estrutural.

Nenhum CRITICO de vazamento, IDOR, BOLA ou leitura Sheets na API foi
encontrado nesta auditoria. Nao ha frontend no repositorio.

---

## 2. Arquitetura recomendada

### 2.1 Fluxo

```
Browser (SPA ou pages)
  -> HTTPS (terminacao no deploy, nao no Flask)
  -> Flask /api/v1
       -> api/rate_limit.py (in-process, janela 60s)
       -> api/auth.py (X-API-Key | X-Session-Token)
       -> api/routes/* (query/corpo + permissao)
       -> services/* (mercado, usuarios, escopo, planos, preferencias, ...)
       -> pipeline_dados.banco_dados (SQLAlchemy / PostgreSQL-Neon)
       -> api/serializadores.py
       -> api/respostas.py
```

Integracao atual em `main.py`: `integrar_api(app)` so quando
`config.API_ENABLED` e verdadeiro. Padrao fail-closed
(`API_ENABLED=false` em `config.py` e `.env.example`).

### 2.2 O que o Website deve e nao deve fazer

Deve:

- consumir o envelope `{"status","data","meta"}`;
- enviar `X-Session-Token` apos `POST /auth/login`;
- tratar 401 (relogin), 403 (sem permissao), 404 cruzado (recurso
  privado inexistente ou de terceiro), 429 (rate limit);
- paginar com `page` / `page_size` (teto 500);
- exibir `null` como ausencia; nunca substituir por 0;
- respeitar `semantica` / `unidade` / `escala` / `aplicavel` do JSON;
- usar `GET /me/plano` para limites de carteira/acompanhados.

Nao deve:

- importar `gspread`, abrir `BD_FIIs`/`BD_Acoes`, chamar scrapers;
- recalcular DY, P/VP, VPA, vacancia, cobertura ou prioridade de alerta;
- misturar `snapshot.vpa` com `valor_patrimonial_cotas` (CVM);
- misturar `snapshot.dy` com `percentual_dividend_yield_mes`;
- tratar `GET /indicadores/<ativo_id>/historico` como serie temporal
  (`meta.serie_temporal = false`);
- expor ou persistir senha, token ou API Key em logs do cliente.

### 2.3 Auth web recomendada (sem inventar mecanismo paralelo)

Ja existe e deve ser reutilizado:

- `POST /api/v1/auth/register` (publico, forca USER);
- `POST /api/v1/auth/login` (devolve token bruto 1x + usuario);
- `POST /api/v1/auth/logout` (`X-Session-Token`);
- `GET /api/v1/me`, `GET /api/v1/me/plano`.

Sessao: token opaco (`secrets.token_urlsafe`), so hash SHA-256 no PG,
TTL `SESSAO_TTL_HORAS` (padrao 168h). Origem do login web: `"web"`.

Para o browser, o contrato atual e **header**, nao cookie. O SPA tera
de guardar o token (memoria ou storage). Cookie HttpOnly / CSRF /
`Authorization: Bearer` **nao existem**. Nao criar segundo sistema de
sessao nesta fase; se a 11.2 exigir ajuste, deve ser aditivo sobre
`services/sessoes.py` e `api/auth.py`.

### 2.4 Papel do Website vs Telegram vs Sheets

| Consumidor | Fonte hoje | Fonte correta para Website |
|---|---|---|
| API `/api/v1` | PostgreSQL | PostgreSQL |
| Telegram menus | Google Sheets (`dashboard_menus`) | fora do Website |
| Scrapers / `app.py` | Sheets + espelhamento 5C | fora do Website |
| Website (futuro) | inexistente | **somente API** |

Sheets permanece no legado. Nao precisa ser desligado para o Website
nascer. Divergencia temporaria Telegram vs Website e esperada.

---

## 3. O que a API ja suporta para um frontend

Total confirmado: **50** metodos HTTP em `api/routes/` (mesmo inventario
da Fase 9). Fonte: PostgreSQL em 49; sem persistencia em 1 (`healthz`);
Google Sheets na pasta `api/`: **0**.

Envelope: sucesso HTTP 200 + `status/data/meta`. Erro
`status=error, data=null, meta.error`. Criacoes tambem 200 com
`meta.criado` (nao 201).

### 3.1 Sistema e autenticacao (4)

| Metodo | Rota | Auth | Pronto para web? |
|---|---|---|---|
| GET | `/api/v1/healthz` | publica | sim (liveness) |
| POST | `/api/v1/auth/register` | publica (forca USER) | sim, com ressalva de politica |
| POST | `/api/v1/auth/login` | publica | sim |
| POST | `/api/v1/auth/logout` | `X-Session-Token` | sim |

### 3.2 Conta e usuarios (13)

| Metodo | Rota | Authz | Isolamento |
|---|---|---|---|
| GET | `/api/v1/me` | `conta.propria` | proprio |
| GET | `/api/v1/me/plano` | `conta.propria` | proprio |
| GET | `/api/v1/usuarios` | `usuarios.ler` | admin; paginado |
| GET | `/api/v1/usuarios/<id>` | `usuarios.ler` | admin |
| POST | `/api/v1/usuarios` | `usuarios.criar` | admin; rejeita `plano` |
| PATCH | `/api/v1/usuarios/<id>` | proprio ou `usuarios.criar` | SUPERADMIN protegido |
| POST | `/api/v1/usuarios/<id>/ativar` | `usuarios.ativar` | idem |
| POST | `/api/v1/usuarios/<id>/desativar` | `usuarios.desativar` | idem |
| POST | `/api/v1/usuarios/<id>/papel` | `usuarios.alterar_papel` | anti-escalonamento |
| POST | `/api/v1/usuarios/<id>/plano` | SUPERADMIN | anti-auto-alteracao |
| POST | `/api/v1/usuarios/<id>/telegram` | `telegram.administrar` | admin |
| DELETE | `/api/v1/usuarios/<id>/telegram` | `telegram.administrar` | admin |
| POST | `/api/v1/usuarios/<id>/sessoes/revogar` | `usuarios.desativar` | admin |

O Website de usuario comum precisa so de `/me` e `/me/plano`. O restante
e painel administrativo, nao Dashboard.

### 3.3 API keys, preferencias, carteira, acompanhados, notificacoes (21)

Todos isolados por dono (`g.usuario`). `usuario_id` do cliente e
ignorado nas criacoes. Recurso de terceiro = 404.

| Recurso | Operacoes | Permissao |
|---|---|---|
| `/api-keys` | POST/GET/GET id/DELETE | `conta.propria` |
| `/preferencias` | GET/PATCH/POST restaurar | `preferencias.proprias` |
| `/carteira` | GET/POST/GET id/PATCH/DELETE | `carteira.propria` |
| `/ativos-acompanhados` | GET/POST/GET id/DELETE | `ativos.proprios` |
| `/notificacoes` | GET/GET id/POST ler-todas/POST lida/DELETE | `notificacoes.consultar` |

Preferencias ja incluem flags web: `web_ativo`, `telegram_ativo`,
`notificacoes_*`, `frequencia_notificacoes`, `mercado_acoes`,
`mercado_fiis`. A Fase 10.3 ja consome frequencia e filtros de mercado
no motor de notificacoes — o Website so persiste via PATCH.

### 3.4 Dados financeiros (12)

Todos exigem autenticacao + permissao de consulta (USER/ADMIN/SUPERADMIN).
VISITOR autenticado **nao** le mercado.

| Metodo | Rota | Fonte PG | Filtros |
|---|---|---|---|
| GET | `/ativos` | `ativos` + `ativos_perfil` | `tipo`, `ticker` exato |
| GET | `/mercado/snapshots` | `snapshots_fiis` / `snapshots_acoes` | ticker, ativo_id, tipo, data |
| GET | `/mercado/snapshots/mais-recente` | idem (1 registro) | ticker/ativo_id/tipo |
| GET | `/mercado/dados-financeiros` | `dados_financeiros_*` | + `tipo_doc` ITR/DFP |
| GET | `/mercado/freshness` | snapshots + contabil + docs | ticker **obrigatorio** |
| GET | `/mercado/cobertura` | catalogo vs persistido | paginado no catalogo |
| GET | `/mercado/cobertura-fii` | campos FII 8.6 | ticker opcional + pagina |
| GET | `/indicadores` | `indicadores_historico` | ativo_id, ticker, indicador, tipo |
| GET | `/indicadores/<ativo_id>/historico` | estado atual por indicador | `serie_temporal=false` |
| GET | `/alertas` | `alertas_eventos` | ativo, ticker, tipo, severidade |
| GET | `/documentos` | metadados (sem texto/IA) | ativo, ticker, tipo, status |
| GET | `/relatorios` | COUNTs agregados | nenhum |

### 3.5 Contrato HTTP reutilizavel

- Paginacao: `page` 1-indexado, `page_size` (precede `limite`), teto 500.
  `meta`: `total`, `page`, `page_size`, `has_next`, `next_page`, `retornados`.
- Ticker: igualdade exata (`PETR4` != substring `PETR`).
- Serializacao: `None` permanece `null`; zero real permanece `0.0`;
  datas ISO 8601; semantica 8.5 ao lado do numero; dois VPAs/DYs
  rotulados em `proveniencia`.
- Rate limit: 120/min API, 10/min login+register, `healthz` isento,
  identidade = `request.remote_addr` (nao le `X-Forwarded-For`).
- Documentos: nunca `texto_extraido`, `resumo_ia`, `log_erro`, hash.
- Usuario: nunca senha/hash/token; Telegram so booleano
  `telegram_vinculado`.

---

## 4. Prontidao por tela (Dashboard, Ativos, Indicadores, Documentos, Alertas)

Composicao no cliente. **Nao** ha endpoint `/dashboard`. Isso nao e
lacuna comprovada: os dados ja existem. Um BFF so se justificaria se a
11.2 medir N round-trips inaceitaveis.

### 4.1 Dashboard — PRONTO por composicao

| Bloco da tela | Endpoint | Observacao |
|---|---|---|
| Identidade / plano | `GET /me`, `GET /me/plano` | entitlements e limites |
| Posicoes | `GET /carteira` | `quantidade`, `preco_medio`, `valor_investido` |
| Watchlist | `GET /ativos-acompanhados` | ticker/tipo |
| Inbox | `GET /notificacoes?nao_lidas=true` | canal `web` ja existe no modelo |
| Resumo operacional | `GET /relatorios` | COUNTs globais, nao carteira |
| Cotacao recente | `GET /mercado/snapshots/mais-recente?ticker=` | 1 ativo por chamada |
| Saude do dado | `GET /mercado/freshness?ticker=` | FRESH/STALE/MISSING |
| Alertas recentes | `GET /alertas` | mercado/qualidade/critico |

Ressalva: dashboard com N tickers da carteira implica N chamadas a
`/snapshots/mais-recente` (e freshness). Mitigacao sem endpoint novo:
`GET /mercado/snapshots` paginado + filtro `tipo_ativo`, cruzar no
cliente pelos tickers da carteira. Nao criar agregador agora.

`GET /relatorios` e resumo da **plataforma** (todos os ativos), nao do
usuario. Nao usar como "meu patrimonio". Patrimonio = soma de
`valor_investido` da carteira (derivada ja persistida, sem fonte
externa). Preco de mercado **nao** entra nessa derivada — se a tela
quiser MtM, usa snapshot.preco no cliente **sem** inventar regra
financeira extra (apenas `qtd * preco` exibido, rotulado como cotacao
de mercado, nao como valorizacao oficial do backend).

### 4.2 Ativos — PRONTO

| Necessidade | Endpoint | Status |
|---|---|---|
| Lista FII/acao | `GET /ativos?tipo=&ticker=&page=` | pronto |
| Perfil (setor, tipo_fii) | incluso em `serializar_ativo` | pronto |
| Cotacao / multiplos | `GET /mercado/snapshots` + `mais-recente` | pronto |
| Contabil CVM | `GET /mercado/dados-financeiros` | pronto |
| Cobertura FII | `GET /mercado/cobertura-fii?ticker=` | pronto (teto 500) |
| Freshness | `GET /mercado/freshness` | ticker obrigatorio |

Nao ha `GET /ativos/<id>`. Nao e bloqueio: `?ticker=` e igualdade
exata, ou a lista ja traz `id`. Catalogo declarativo
(`ativos_catalogo`) e inquilinos **sem** rota propria — a Fase 8
classificou inquilinos como C/D; nao expor agora.

### 4.3 Indicadores — PRONTO como estado atual

| Necessidade | Endpoint | Status |
|---|---|---|
| Estado atual | `GET /indicadores` | semantica/unidade/escala |
| Por ativo | `GET /indicadores/<ativo_id>/historico` | **nao e serie** |

A tabela `indicadores_historico` tem `UniqueConstraint(ativo_id,
indicador)`: uma linha por indicador (valor_atual / valor_anterior).
Graficos de serie temporal **nao** sao suportados. O Website deve
mostrar card/tabela de estado, nao chart historico, ate fase futura
com migration.

### 4.4 Documentos — PRONTO como metadados

`GET /documentos` lista `url_pdf`, assunto, tipo, status, datas,
ticker. Sem download binario via API, sem texto, sem resumo IA. O
Website pode linkar `url_pdf` (Drive/FNET). Nao ha `GET /documentos/<id>`;
a listagem filtrada por `ativo_id`/`ticker` cobre a tela.

### 4.5 Alertas — PRONTO (leitura + inbox + prefs)

| Necessidade | Endpoint | Status |
|---|---|---|
| Eventos globais | `GET /alertas` | USER/ADMIN/SUPERADMIN |
| Inbox individual | `GET /notificacoes` | escopo proprio |
| Marcar lida | `POST /notificacoes/<id>/lida` | 404 cruzado |
| Preferencias de alerta | `GET/PATCH /preferencias` | 10.3 ja gating |

Nao ha POST de alerta pelo Website — geracao e do motor. Correto.

---

## 5. Lacunas reais para autenticacao e experiencia web

Classificacao: so o que o codigo evidencia. Nada inventado.

### 5.1 Bloqueiam o Website no browser (operacional)

1. **`API_ENABLED=false`** — sem o flag no deploy, `/api/v1` nao existe.
   Nao e bug; e fail-closed. Ligar so no ambiente do Website.
2. **CORS ausente** — Flask nao envia `Access-Control-Allow-*`. SPA em
   origem distinta falha no preflight. `flask-cors` nao esta em
   `requirements.txt`. Ajuste de config, nao endpoint novo.
3. **Token so em cabecalho** — sem cookie HttpOnly. XSS no SPA vaza
   sessao se o token for para `localStorage`. Limitacao conhecida, nao
   IDOR.

### 5.2 Experiencia de conta (nao bloqueiam MVP autenticado)

4. Sem recuperacao de senha / reset.
5. Sem refresh token; TTL 7 dias; logout revoga 1 token.
6. Usuario autenticado **nao lista** sessoes proprias (so admin revoga
   em lote via `/usuarios/<id>/sessoes/revogar`).
7. Sem `GET /auth/me` duplicado (ja existe `/me`) — ok.
8. `POST /auth/register` publico cria USER se a API estiver ligada
   (politica de produto; anti-enumeracao de email ja existe).
9. Sem `Authorization: Bearer`. Cliente web deve usar `X-Session-Token`.

### 5.3 RBAC vs tela logada

10. **ADMIN nao tem** `carteira.propria`, `ativos.proprios`,
    `preferencias.proprias`, `notificacoes.consultar`. Login de ADMIN no
    Website recebe 403 nessas telas pessoais. USER e SUPERADMIN (`*`)
    acessam. Intencional na matriz (ADMIN = operador). Se a 11.2 quiser
    ADMIN usando Dashboard pessoal, isso e ajuste de matriz — nao endpoint
    novo.
11. VISITOR autenticado nao le mercado (`publico.*` sem rota). Website
    visitante nao tem superficie publica de cotacoes.

### 5.4 Dados que o Website nao deve esperar

12. Historico temporal de indicadores — PENDENTE estrutural (Fase 9.5).
13. WALT/vacancia distintas confiaveis, parser FNET, ETF/cripto — Fase 8
    fonte C/D, fora.
14. Texto/IA de documentos — omitidos de proposito.
15. Relatorio financeiro personalizado — `/relatorios` e COUNT global.

Nenhuma dessas lacunas exige endpoint novo **nesta** etapa.

---

## 6. Endpoints que precisam apenas de ajustes

Nao implementar agora. Lista para a 11.2 decidir com evidencia de UX,
sem criar recurso.

| Ajuste | Por que | Tipo |
|---|---|---|
| CORS allowlist da origem do Website | SPA cross-origin | config Flask |
| `API_ENABLED=true` no deploy do Website | API nem registra rotas | config |
| Documentar header `X-Session-Token` no cliente | contrato ja existe | docs/front |
| ADMIN + permissoes de escopo proprio | se ADMIN usar Dashboard | matriz `autorizacao.py` |
| Politica de `POST /auth/register` | producao aberta vs convite | produto |
| Cookie HttpOnly aditivo | reduzir XSS de storage | auth existente |
| Filtro multi-ticker em snapshots | reduzir N+1 do Dashboard | query opcional |
| `GET /ativos/<id>` | conveniencia; `?ticker=` ja resolve | opcional |
| HTTPS / `Secure` cookie | terminacao no proxy | deploy |

Nenhum item acima e correcao financeira. Nenhum exige migration.

---

## 7. Lacunas que exigiriam novos endpoints

So registrar. **Nao criar** sem necessidade comprovada na 11.2+.

| Endpoint hipotetico | Necessidade real? | Veredito 11.1 |
|---|---|---|
| `GET /dashboard` | composicao de 4-6 GETs | **nao** — cliente agrega |
| `GET /ativos/<id>` | detalhe | **nao comprovada** — filtro ticker |
| `GET /ativos_catalogo` | universo 7.2 | **nao** — `/ativos` operacional basta |
| `GET /inquilinos` | Fase 8 C/D | **nao** |
| `GET /documentos/<id>` | metadado unitario | **nao** — lista filtra |
| `GET /indicadores/.../serie` | chart | **nao agora** — exige migration |
| `POST /auth/forgot-password` | UX conta | produto futuro |
| `GET /me/sessoes` | sessao web | produto futuro |
| `POST /auth/refresh` | TTL 7d | desnecessario no MVP |
| WebSocket de alertas | tempo real | inbox HTTP + poll `notificacoes` |

Conclusao: a API existente cobre o Website autenticado. Novos endpoints
nao estao comprovados nesta etapa.

---

## 8. Riscos de seguranca e isolamento multiusuario

### 8.1 Solidos (evidencia no codigo e testes)

- Hash de senha/sessao/API Key nunca serializado.
- Token/chave brutos so na criacao ou no login.
- 401 indistinguivel (chave inexistente, expirada, revogada).
- Login: email inexistente, senha errada e usuario desativado = mesma 401.
- Escopo `buscar_recurso_escopado`: 404 cruzado (anti-IDOR/BOLA).
- `usuario_id` no PATCH de preferencias = 400.
- Plano nunca aceito no cadastro/PATCH comum.
- SUPERADMIN protegido contra ADMIN (anti-escalonamento).
- Rate limit nao substitui 401/403.
- Excecao nao tratada = 500 sem stack trace.
- Documentos sem payload pesado.
- `API_ENABLED` fail-closed; nunca hardcodado `True`.

Testes desta etapa (existentes, sem alteracao): **473 passed**, 0 failed
(ver secao 11).

### 8.2 Riscos reais para o Website (nao CRITICOS de API)

| Risco | Severidade | Notas |
|---|---|---|
| CORS aberto demais se mal configurado na 11.2 | ALTO se feito errado | allowlist; nunca `*` com credenciais |
| Token em `localStorage` (XSS) | MEDIO | contrato atual e header |
| Register publico com API ligada | MEDIO / produto | cria USER irrestrito (plano FREE) |
| Rate limit in-process (N workers = N tetos) | MEDIO | documentado na 9.4 |
| Rate limit por IP, nao por usuario | MEDIO | NAT compartilhado |
| `X-Forwarded-For` ignorado | BAIXO | correto atras de proxy malicioso; pode unificar IPs atras de proxy honesto |
| ADMIN 403 em telas pessoais | BAIXO / UX | nao e vazamento |
| HTTPS nao na app Flask | BAIXO | responsabilidade do deploy |
| Polling agressivo de `/alertas` ou `/cobertura` | MEDIO | teto 500 + 120 req/min |

IDOR/BOLA em carteira, acompanhados, notificacoes, api-keys,
preferencias: **nao encontrado**.

Sheets no frontend: **nao ha caminho**. Qualquer tentativa futura de
ler `services/planilhas.py` do Website viola a regra desta fase.

---

## 9. Dependencias API <-> PostgreSQL e Sheets

### 9.1 PostgreSQL

A API depende de `services.db.SessionDB` / SQLAlchemy. Modelos usados
pelas telas web:

- conta: `usuarios`, `sessoes`, `chaves_api`, `preferencias_usuarios`
- privado: `posicoes_carteira`, `ativos_acompanhados`, `notificacoes`
- mercado: `ativos`, `ativos_perfil`, `snapshots_*`, `dados_financeiros_*`
- qualidade: `indicadores_historico`, `alertas_eventos`, `documentos_qualitativos`

Nao expostos (e nao necessarios ao MVP web): `ativos_catalogo`,
`ativos_inquilinos`, `auditoria_acesso`.

Sem PostgreSQL/Neon a API nao opera. SQLite e so teste/dev. Nenhuma
alteracao de banco comprovada para o Website.

### 9.2 Google Sheets — fora da API, fora do Website

Busca em `api/**/*.py` por `gspread`, `SPREADSHEET`, `worksheet`,
`BD_FIIs`, `BD_Acoes`, `BD_Logs`, `conectar_gspread`: **0**.

Ocorrencias Sheets **legadas** (Telegram, scrapers, espelhamento 5C,
fallback CVM): `services/planilhas.py`, `services/dashboard_menus.py`,
`modules/scraper_*.py`, `modules/utils.py`, `app.py`,
`pipeline_dados/coletor_cvm.py`, `atualizador_documentos.py`.

Regra para o frontend: **proibido** importar ou chamar esses modulos.
Equivalente PG ja esta em `/mercado/*` e `/ativos`.

---

## 10. Mapa consolidado (pedido da etapa)

1. **O que a API ja suporta para um frontend:** 50 endpoints, envelope,
   sessao web, RBAC, isolamento, paginacao, rate limit, semantica 8.5,
   mercado/indicadores/documentos/alertas/conta. Tudo em PostgreSQL.
2. **Pronto para Dashboard, Ativos, Indicadores, Documentos, Alertas:**
   sim, por composicao dos GETs existentes. Indicadores = estado atual,
   nao serie. Documentos = metadados + `url_pdf`. Dashboard = carteira +
   acompanhados + notificacoes + snapshot/freshness/alertas.
3. **Falta para autenticacao e UX web:** CORS, `API_ENABLED` no deploy,
   estrategia de armazenamento do token, reset de senha, listagem de
   sessoes proprias, politica de register, cookie opcional. Nucleo
   login/logout/`/me` **ja existe**.
4. **Ajustes (nao endpoints novos):** CORS, flag de deploy, eventual
   permissao de ADMIN em escopo proprio, eventual filtro multi-ticker.
5. **Novos endpoints:** nenhum comprovado. Historico temporal exigiria
   migration — fora desta etapa.
6. **Riscos:** XSS de token, register publico, rate limit por processo,
   ADMIN sem telas pessoais, polling pesado. Sem IDOR/Sheets na API.

---

## 11. Testes executados

Dependencias de ambiente instaladas so no container de auditoria
(pytest, Flask, SQLAlchemy, PyPDF2, requirements do projeto). Nenhum
teste alterado. Nenhuma falha mascarada.

| Bloco | Arquivos | Resultado |
|---|---|---|
| Hardening / RBAC / escopo / sessoes / keys / seguranca | `test_fase94_hardening`, `test_autorizacao`, `test_escopo`, `test_sessoes`, `test_chaves_api`, `test_seguranca` | 128 passed |
| API HTTP + auth web | `test_api`, `test_auth_web` | 82 passed |
| Fase 9.2 + keys HTTP + usuarios | `test_fase92_api`, `test_chaves_api_http`, `test_usuarios_api` | 79 passed |
| Prefs / carteira / acompanhados / planos / mercado / 10.3 | `test_preferencias`, `test_carteira`, `test_ativos_acompanhados`, `test_planos_api`, `test_planos_enforcement_api`, `test_mercado_service`, `test_etapa103_preferencias_alertas` | 184 passed |

**Total: 473 passed, 0 failed, 0 errors.** Warning unico: `PyPDF2`
deprecado (legado, fora da API).

Cobertura confirmada: autenticacao, RBAC, isolamento 404, paginacao,
ticker exato, semantica, `API_ENABLED` fail-closed, rate limit (suite
com `TESTING` sem 429 salvo flag), preferencias 10.3, enforcement de
planos na API.

---

## 12. Arquivos alterados

Unico artefato desta etapa:

- `docs/FASE11_ETAPA111_AUDITORIA_WEB.md`

Nenhum arquivo de codigo, teste, modelo ou config foi modificado.

---

## 13. Proxima etapa recomendada

**Etapa 11.2** — contrato de consumo do Website (ainda sem UI de
produto, se a fase assim definir): CORS allowlist, ligar `API_ENABLED`
no ambiente de preview, documentar headers e composicao das cinco
telas, decidir politica de register e se ADMIN precisa de escopo
proprio.

Nao nesta 11.2, salvo evidencia nova:

- frontend de telas;
- endpoints novos;
- migration / historico temporal;
- migracao Sheets;
- cookie/refresh/reset de senha;
- BFF `/dashboard`.

**Nao avancar automaticamente para 11.2 neste documento.**

---

## 14. Veredito

A API financeira e **adequada como backend exclusivo do Website
autenticado**. Dashboard, Ativos, Indicadores (estado), Documentos
(metadados) e Alertas (eventos + inbox + preferencias) ja tem dados e
autorizacao.

O que falta e **superficie de browser** (CORS, deploy flag, sessao no
cliente) e **UX de conta** (reset, sessoes proprias), nao um segundo
backend nem leitura de Sheets.

Classificacao: **pronta para o Website consumir `/api/v1` em ambiente
controlado**; **nao pronta como app publica aberta** sem os ajustes
operacionais da secao 5.1.

Nenhuma falha real encontrada que exija correcao de codigo nesta etapa.
Nenhum endpoint novo comprovado. Unico artefato: este documento.
