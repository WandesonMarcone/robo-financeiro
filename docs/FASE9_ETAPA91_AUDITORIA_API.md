# Fase 9 — Etapa 9.1: Auditoria da API Existente

Documento de auditoria (somente analise). Nao altera codigo, nao cria
endpoints, nao altera banco, nao migra Google Sheets e nao avanca para a
Etapa 9.2. Data da auditoria: 2026-09-05. Commit base: `b278dd4`
(`v1.3.0` — Fase 8 concluida). Arvore de trabalho limpa.

Escopo: a camada HTTP em `api/` e os servicos que ela chama. Fontes de
coleta (CVM/FNET/scrapers) e o Telegram/website ficam fora desta etapa,
exceto quando a API os consome.

---

## 1. Arquitetura atual da API

### 1.1 Integracao

- Prefixo unico: `/api/v1` (`api/__init__.py:18`).
- Factory: `api.blueprint.criar_blueprint_api()` registra 14 Blueprints de
  recurso.
- Integracao aditiva em `main.py:150`: so registra rotas quando
  `config.API_ENABLED` e verdadeiro. Padrao: **desabilitada**
  (`config.py:105`).
- Quando desabilitada, webhook Telegram e pagina raiz permanecem intactos.
- 404/405 no prefixo `/api/v1` devolvem envelope JSON; fora do prefixo o
  Flask legado e preservado (`api/__init__.py:46-56`).
- Excecao nao tratada no Blueprint vira 500 generico, sem stack trace
  (`api/blueprint.py:51-54`).

### 1.2 Camadas

```
Cliente HTTP
  -> api/auth.py (X-API-Key | X-Session-Token)
  -> api/routes/* (validacao de query/corpo + permissao)
  -> services/*  (dominio: mercado, usuarios, escopo, planos, ...)
  -> pipeline_dados.banco_dados (SQLAlchemy / PostgreSQL-Neon ou SQLite)
  -> api/serializadores.py (dict campo a campo)
  -> api/respostas.py (envelope status/data/meta)
```

Nenhum arquivo em `api/` importa `gspread`, `conectar_gspread`,
`BD_FIIs`, `BD_Acoes` ou `BD_Logs`.

### 1.3 Envelope

Sucesso: `{"status": "success", "data": ..., "meta": ...}` + HTTP 200.

Erro: `{"status": "error", "data": null, "meta": {"error": "<mensagem>"}}`
+ codigo HTTP (`api/respostas.py`).

Codigos observados: 200, 400, 401, 403, 404, 405, 500. Nao ha 201/204:
criacoes tambem retornam 200 com `meta.criado`.

### 1.4 Autenticacao

- Cabecalhos: `X-API-Key` (prioridade) e `X-Session-Token`.
- Validacao: `services/chaves_api.py` (hash SHA-256) e
  `services/sessoes.py`.
- Falha indistinguivel: 401 `"Nao autenticado."` — nao distingue chave
  inexistente, expirada ou revogada.
- Rotas publicas: `GET /healthz`, `POST /auth/register`,
  `POST /auth/login`, `POST /auth/logout` (logout exige o token no
  cabecalho, mas nao usa `rota_protegida`).

### 1.5 Autorizacao

Matriz unica em `services/autorizacao.py` (`PAPEL_PERMISSOES`):

- SUPERADMIN: `"*"`.
- ADMIN: usuarios, dados, documentos, relatorios, indicadores, historico,
  `alertas.gerenciar`, telegram, `conta.propria`. **Nao possui**
  `alertas.consultar`.
- USER: consulta financeira + escopo proprio (conta, carteira,
  acompanhamentos, preferencias, notificacoes, `alertas.consultar`).
- VISITOR / nao autenticado: so permissoes `publico.*` — nenhuma rota da
  API as usa, portanto VISITOR autenticado nao le mercado.

Isolamento de recursos privados: `services/escopo.py` via
`buscar_recurso_escopado`. Recurso inexistente e recurso de terceiro
produzem o mesmo 404 (anti-IDOR/BOLA). `usuario_id` enviado pelo cliente
e ignorado.

### 1.6 Limites HTTP

`api/dependencias.py`: `?limite=` padrao 100, teto 500. Comentario
explicito: "sem paginacao de producao nesta etapa". Nao ha `offset`,
cursor nem pagina. Varias listagens privadas **nao** chamam
`obter_limite()`.

Nao ha rate limiting no codigo da API.

---

## 2. Inventario completo de endpoints

Total: **50** metodos HTTP distintos em `api/routes/`.

Fonte de dados: todos os endpoints que leem/gravam persistencia usam
PostgreSQL/Neon via SQLAlchemy (`services.db.SessionDB`). Nenhum usa
Google Sheets.

### 2.1 Sistema e autenticacao

| Metodo | Rota | Finalidade | Fonte | Auth | Authz | Isolamento | Paginacao/filtros | Status |
|---|---|---|---|---|---|---|---|---|
| GET | `/api/v1/healthz` | Liveness | nenhuma | publica | — | — | — | pronto |
| POST | `/api/v1/auth/register` | Cadastro USER | PG `usuarios` | publica | forca USER | — | corpo nome/email/senha | pronto |
| POST | `/api/v1/auth/login` | Sessao web | PG `usuarios`+`sessoes` | publica | — | — | email/senha | pronto |
| POST | `/api/v1/auth/logout` | Revoga sessao | PG `sessoes` | `X-Session-Token` | — | token proprio | — | pronto |

### 2.2 Conta e usuarios

| Metodo | Rota | Finalidade | Fonte | Auth | Authz | Isolamento | Filtros/limites | Status |
|---|---|---|---|---|---|---|---|---|
| GET | `/api/v1/me` | Perfil autenticado | PG `usuarios` | sim | `conta.propria` | proprio | — | pronto |
| GET | `/api/v1/me/plano` | Entitlements | PG + `services.planos` | sim | `conta.propria` | proprio | — | pronto |
| GET | `/api/v1/usuarios` | Lista usuarios | PG `usuarios` | sim | `usuarios.ler` | admin | `ativos=true`; **sem limite** | corrigir limite |
| GET | `/api/v1/usuarios/<id>` | Consulta usuario | PG `usuarios` | sim | `usuarios.ler` | admin | — | pronto |
| POST | `/api/v1/usuarios` | Cria usuario | PG `usuarios` | sim | `usuarios.criar` + papel | admin | rejeita `plano` no corpo | pronto |
| PATCH | `/api/v1/usuarios/<id>` | Atualiza nome/email/senha | PG `usuarios` | sim | proprio ou `usuarios.criar` | proprio/admin; SUPERADMIN protegido | nome/email/senha | pronto |
| POST | `/api/v1/usuarios/<id>/ativar` | Reativa | PG `usuarios` | sim | `usuarios.ativar` | SUPERADMIN protegido | — | pronto |
| POST | `/api/v1/usuarios/<id>/desativar` | Desativa | PG `usuarios` | sim | `usuarios.desativar` | idem | — | pronto |
| POST | `/api/v1/usuarios/<id>/papel` | Altera papel | PG `usuarios` | sim | `usuarios.alterar_papel` | anti-escalonamento | corpo `papel` | pronto |
| POST | `/api/v1/usuarios/<id>/plano` | Altera plano | PG `usuarios` | sim | SUPERADMIN (`planos.PERMISSAO_ADMINISTRAR_PLANOS`) | anti-auto-alteracao | corpo `plano` | pronto |
| POST | `/api/v1/usuarios/<id>/telegram` | Vincula Telegram | PG `usuarios` | sim | `telegram.administrar` | SUPERADMIN protegido | telegram_user_id | pronto |
| DELETE | `/api/v1/usuarios/<id>/telegram` | Desvincula | PG `usuarios` | sim | `telegram.administrar` | idem | — | pronto |
| POST | `/api/v1/usuarios/<id>/sessoes/revogar` | Revoga sessoes | PG `sessoes` | sim | `usuarios.desativar` | SUPERADMIN protegido | — | pronto |

### 2.3 API Keys, preferencias, carteira, acompanhados, notificacoes

| Metodo | Rota | Finalidade | Fonte | Authz | Isolamento | Limite | Status |
|---|---|---|---|---|---|---|---|
| POST | `/api/v1/api-keys` | Cria chave (exposta 1x) | PG `chaves_api` | `conta.propria` | dono = `g.usuario` | — | pronto |
| GET | `/api/v1/api-keys` | Lista metadados | PG `chaves_api` | `conta.propria` | 404 cruzado | sem `?limite=` | pronto (volume baixo) |
| GET | `/api/v1/api-keys/<id>` | Metadados | PG `chaves_api` | `conta.propria` | 404 cruzado | — | pronto |
| DELETE | `/api/v1/api-keys/<id>` | Revoga | PG `chaves_api` | `conta.propria` | 404 cruzado | — | pronto |
| GET | `/api/v1/preferencias` | Le/cria defaults | PG `preferencias_usuarios` | `preferencias.proprias` | 1:1 | — | pronto |
| PATCH | `/api/v1/preferencias` | Atualiza | PG | `preferencias.proprias` | rejeita `usuario_id` | — | pronto |
| POST | `/api/v1/preferencias/restaurar` | Defaults | PG | `preferencias.proprias` | proprio | — | pronto |
| GET | `/api/v1/carteira` | Lista posicoes | PG `posicoes_carteira` | `carteira.propria` | escopo | sem `?limite=` | corrigir limite |
| POST | `/api/v1/carteira` | Cria posicao | PG | `carteira.propria` | ignora `usuario_id` | plano | pronto |
| GET | `/api/v1/carteira/<id>` | Consulta | PG | `carteira.propria` | 404 cruzado | — | pronto |
| PATCH | `/api/v1/carteira/<id>` | Atualiza qtd/preco | PG | `carteira.propria` | 404 cruzado | — | pronto |
| DELETE | `/api/v1/carteira/<id>` | Remove | PG | `carteira.propria` | 404 cruzado | — | pronto |
| GET | `/api/v1/ativos-acompanhados` | Lista | PG `ativos_acompanhados` | `ativos.proprios` | escopo | sem `?limite=` | corrigir limite |
| POST | `/api/v1/ativos-acompanhados` | Adiciona | PG | `ativos.proprios` | ignora `usuario_id` | plano | pronto |
| GET | `/api/v1/ativos-acompanhados/<id>` | Consulta | PG | `ativos.proprios` | 404 cruzado | — | pronto |
| DELETE | `/api/v1/ativos-acompanhados/<id>` | Remove | PG | `ativos.proprios` | 404 cruzado | — | pronto |
| GET | `/api/v1/notificacoes` | Lista | PG `notificacoes` | `notificacoes.consultar` | usuario_id da sessao | tipo/status/nao_lidas; **sem limite HTTP** | corrigir limite |
| GET | `/api/v1/notificacoes/<id>` | Consulta | PG | `notificacoes.consultar` | 404 cruzado | — | pronto |
| POST | `/api/v1/notificacoes/ler-todas` | Marca todas lidas | PG | `notificacoes.consultar` | proprio | — | pronto |
| POST | `/api/v1/notificacoes/<id>/lida` | Marca lida | PG | `notificacoes.consultar` | 404 cruzado | — | pronto |
| DELETE | `/api/v1/notificacoes/<id>` | Exclui | PG | `notificacoes.consultar` | 404 cruzado | — | pronto |

### 2.4 Dados financeiros (Fase 7/8)

| Metodo | Rota | Finalidade | Tabela/modelo | Authz | Filtros | Limite | Status |
|---|---|---|---|---|---|---|---|
| GET | `/api/v1/ativos` | Catalogo operacional | `ativos` + `ativos_perfil` | `dados.consultar` | `tipo`, `ticker` LIKE | 100/500 | pronto, com ressalva |
| GET | `/api/v1/mercado/snapshots` | Snapshots de mercado | `snapshots_fiis` / `snapshots_acoes` | `dados.consultar` | ticker **exato**, ativo_id, tipo_ativo, data_referencia | 100/500 | pronto |
| GET | `/api/v1/mercado/snapshots/mais-recente` | Ultimo snapshot | idem | `dados.consultar` | ticker/ativo_id/tipo | 1 | pronto |
| GET | `/api/v1/mercado/dados-financeiros` | Contabil CVM | `dados_financeiros_fiis` / `dados_financeiros_acoes` | `dados.consultar` | ticker, ativo_id, tipo, tipo_doc ITR/DFP, data_referencia | 100/500 | pronto |
| GET | `/api/v1/mercado/freshness` | FRESH/STALE/MISSING | snapshots + contabil + docs | `dados.consultar` | ticker **obrigatorio** (ou ativo_id) | — | pronto |
| GET | `/api/v1/mercado/cobertura` | Universo vs coletado | catalogo + snapshots + contabil + docs | `dados.consultar` | nenhum | relatorio completo | corrigir peso |
| GET | `/api/v1/mercado/cobertura-fii` | Cobertura por campo FII | snapshots + contabil + perfil + inquilinos + docs | `dados.consultar` | `ticker` opcional | todos os FIIs se omitido | precisa correcao |
| GET | `/api/v1/indicadores` | Estado atual de indicadores | `indicadores_historico` | `indicadores.consultar` | ativo_id, ticker LIKE, indicador, tipo_ativo | 100/500 | corrigir contrato |
| GET | `/api/v1/indicadores/<ativo_id>/historico` | Indicadores do ativo | `indicadores_historico` (1 linha por indicador, nao serie) | `historico.consultar` | — | 100/500 | corrigir contrato |
| GET | `/api/v1/alertas` | Eventos de alerta | `alertas_eventos` | `alertas.consultar` | ativo_id, ticker LIKE, tipo, severidade, tipo_ativo | 100/500 | corrigir RBAC ADMIN |
| GET | `/api/v1/documentos` | Metadados documentais | `documentos_qualitativos` | `documentos.consultar` | ativo_id, ticker LIKE, tipo_documento, status | 100/500 | pronto |
| GET | `/api/v1/relatorios` | Contagens agregadas | ativos, indicadores, alertas, documentos | `relatorios.consultar` | nenhum | 4 COUNTs + GROUPs | pronto como resumo |

Servico de leitura: `services/mercado.py` (somente leitura; None permanece
None; teto 500). Serializacao de mercado em `api/serializadores.py`
preserva `data_referencia`, `data_coleta`, `fonte`, `fonte_primaria`,
`url_origem` e os campos CVM da Etapa 9 (`valor_patrimonial_cotas`,
`percentual_dividend_yield_mes`, `receita_imoveis`, `despesas_taxas`).

---

## 3. Fonte de dados de cada endpoint

Resumo:

- PostgreSQL/Neon: **49** endpoints (tudo que persiste ou consulta).
- Google Sheets: **0** endpoints da API.
- Sem persistencia: **1** (`GET /healthz`).

Sheets permanece ativo no **legado fora da API**: `services/planilhas.py`
(`BD_FIIs`/`BD_Acoes`) e `services/dashboard_menus.py` (Telegram). Nao e
caminho HTTP `/api/v1`.

Classificacao das ocorrencias Sheets (fora da API, para 9.2 nao migrar):

| Ocorrencia | Pode permanecer temporariamente | Precisa migrar | Equivalente PG |
|---|---|---|---|
| `services/planilhas.py` cache BD_FIIs/BD_Acoes | sim (Telegram/scraper) | nao nesta etapa | `snapshots_fiis` / `snapshots_acoes` |
| `services/dashboard_menus.py` | sim | nao nesta etapa | snapshots + perfil |
| scrapers `modules/scraper_*.py` | sim | nao nesta etapa | espelhamento 5C |
| `coletor_cvm._obter_tickers_sheets` | sim (fallback 7.2) | nao nesta etapa | `ativos_catalogo` |

---

## 4. Dependencias Google Sheets

Na pasta `api/`: **nenhuma**.

`grep` em `api/**/*.py` por `gspread`, `SPREADSHEET`, `worksheet`,
`BD_FIIs`, `BD_Acoes`, `BD_Logs`, `conectar_gspread`: 0 ocorrencias.

A API ja e a superficie de leitura do PostgreSQL. O Sheets nao precisa
ser desligado para a API operar.

---

## 5. Dependencias PostgreSQL / Neon e lacunas de exposicao

Ja expostos:

- `ativos`, `ativos_perfil` (setor/tipo_fii via `GET /ativos`)
- `snapshots_fiis`, `snapshots_acoes`
- `dados_financeiros_fiis`, `dados_financeiros_acoes` (ITR e DFP)
- `documentos_qualitativos` (metadados)
- `indicadores_historico`, `alertas_eventos`
- `usuarios`, `sessoes`, `chaves_api`
- `ativos_acompanhados`, `posicoes_carteira`, `preferencias_usuarios`,
  `notificacoes`

Persistidos no PG e **nao** expostos por endpoint dedicado:

| Modelo | Tabela | Observacao |
|---|---|---|
| `AtivoCatalogo` | `ativos_catalogo` | universo declarativo 7.2/8.3; `obter_universo` existe no servico e nao tem rota |
| `AtivoInquilino` | `ativos_inquilinos` | so aparece dentro do relatorio `cobertura-fii` |
| `AuditoriaAcesso` | `auditoria_acesso` | trilha interna; exposicao seria administrativa e nao e pedida agora |
| `Sessao` | `sessoes` | so revogacao admin; usuario nao lista sessoes proprias |
| Campos de documento pesados | `texto_extraido`, `resumo_ia`, `log_erro` | omitidos de proposito |
| Semantica 8.5 | `services.mercado.interpretar_indicador` | nao ha rota HTTP |

Nao e lacuna desta API (fonte C/D na Fase 8, fora de escopo 9.1): WALT
real, vacancia fisica/financeira distintas, parser FNET, ETF/cripto.

---

## 6. Contrato dos dados (Fases 8.2-8.6)

### 6.1 O que a API ja preserva

- Serializadores usam `_numero` / `_data`: `Decimal` vira float; `None`
  permanece `null` JSON. Zero real (0.0) nao e convertido em null.
- Snapshots e dados financeiros incluem `data_referencia`, `data_coleta`
  (quando o modelo tem a coluna), `fonte`, `fonte_primaria`, `url_origem`.
- Dados FII CVM da Etapa 9: VPA (`valor_patrimonial_cotas`), DY mensal
  fracao (`percentual_dividend_yield_mes`), `receita_imoveis`,
  `despesas_taxas`. Vacancia/WALT/resultado de venda ausentes saem
  `null`, nao 0.
- `GET /mercado/freshness` serializa FRESH/STALE/MISSING com SLA em
  segundos (`serializar_freshness`).
- Documentos nao vazam texto/IA/erro.

### 6.2 Desvios do contrato 8.5

- Nao ha campo de status semantico (`ZERO` / `AUSENTE` / `NAO_APLICAVEL`
  / `INVALIDO` / `PRESENTE`) no JSON. Cliente so ve numero ou `null`.
- Unidades nao sao declaradas no payload (fracao vs %, R$, x). DY de
  snapshot de mercado e DY CVM mensal convivem em objetos diferentes
  (`snapshot.dy` vs `percentual_dividend_yield_mes`) sem rotulo de
  unidade.
- Dois VPAs: `snapshot.vpa` (mercado/Sheets espelhado) e
  `valor_patrimonial_cotas` (CVM INF_MENSAL). Ambos validos; o contrato
  HTTP nao explica a diferenca.
- `GET /indicadores/<id>/historico` nao e serie temporal: a tabela e
  "estado mais recente por (ativo_id, indicador)" (`banco_dados.py:290-297`).
- `meta.total` nas listagens e `len(pagina)`, nao a contagem total do
  filtro. Nao ha `offset`.
- Filtro `ticker`: mercado usa igualdade exata; ativos/indicadores/
  alertas/documentos usam `LIKE %termo%`.

### 6.3 HTTP / erros

Mensagens de 400 sao especificas o bastante para o cliente (filtro
invalido). 401/403 sao genericos. 404 de recurso privado e
indistinguivel. Adequado.

Nao ha `Retry-After`, ETag nem `Last-Modified`.

---

## 7. Seguranca

### 7.1 Pontos sólidos (evidencia no codigo)

- Hash de senha/sessao/API Key nunca serializado.
- Chave bruta so no POST de criacao.
- Login/register anti-enumeracao (`test_auth_web.py` coberto).
- RBAC central; plano nao aceito no cadastro/PATCH.
- SUPERADMIN protegido contra ADMIN.
- Escopo 404 em carteira, acompanhados, notificacoes, api-keys.
- Documentos sem conteudo pesado.
- Telegram ID interno nao vai no `serializar_usuario` (so booleano).
- API desligada por padrao.

### 7.2 Problemas

1. **ADMIN nao le `/alertas`**. Matriz concede `alertas.gerenciar` ao
   ADMIN e `alertas.consultar` ao USER. A rota exige `consultar`. ADMIN
   autenticado recebe 403. Evidencia: `autorizacao.py:48-63` vs
   `routes/alertas.py:23`. (ALTO)
2. **Sem rate limit** em login, register e leitura financeira. (MEDIO)
3. **`cobertura-fii` sem ticker** avalia todos os FIIs do catalogo, com
   N+1 (freshness + snapshot + contabil + perfil + inquilinos por ativo)
   e devolve `freshness` cru (objetos `datetime`/`timedelta`). Risco de
   500 JSON e de carga. (ALTO)
4. **N+1 de ticker** em indicadores/alertas/documentos/snapshots:
   `serializar_*` acessa `registro.ativo.ticker` sem `joinedload`. (MEDIO)
5. **CORS / HTTPS** nao configurados na app Flask da API. Operacional,
   nao e bypass de RBAC. (BAIXO)
6. **Register publico** cria USER irrestrito se `API_ENABLED=true`.
   Intencional na Fase 6; para API financeira de producao precisa de
   politica (nao implementar agora). (BAIXO / produto)

IDOR/BOLA nos recursos com dono: nao encontrado nesta auditoria.

---

## 8. Performance

| Item | Evidencia | Severidade |
|---|---|---|
| Sem offset/cursor | `dependencias.py:10-12` | MEDIO |
| Listagens privadas sem teto HTTP | carteira, acompanhados, notificacoes, usuarios | MEDIO |
| `GET /mercado/cobertura` | `avaliar_ativo` por ticker do universo | MEDIO |
| `GET /mercado/cobertura-fii` sem filtro | `cobertura_campos_fii` em todos os FIIs | ALTO |
| N+1 `ativo.ticker` | serializadores | MEDIO |
| Relatorio geral | COUNTs baratos | BAIXO |
| Snapshots sem tipo | une FII+ACAO em Python e recorta | BAIXO |

---

## 9. Problemas classificados

### CRITICO

Nenhum. Nao ha leitura Sheets na API, nao ha vazamento de hash/token
observado, nao ha escrita financeira via HTTP.

### ALTO

1. ADMIN sem `alertas.consultar` — rota de alertas inacessivel ao ADMIN.
2. `GET /mercado/cobertura-fii` — unbounded + payload de freshness nao
   serializado pelo adapter HTTP (`timedelta` `sla`, datas cruas).
3. API financeira oficial ainda **opt-in** (`API_ENABLED=false`). Nao e
   bug de logica, mas impede consumo por website/Telegram ate ligar o
   flag. Registrar como risco operacional da Etapa 9.2.

### MEDIO

4. Paginacao incompleta (`meta.total` = tamanho da pagina; sem offset).
5. Listagens de conta sem `obter_limite()`.
6. Contrato 8.5 nao viaja no JSON (status/unidade).
7. Dois VPAs / dois DYs sem documentacao no payload.
8. `/indicadores/<id>/historico` nao e historico.
9. Filtro `ticker` LIKE vs exato inconsistente.
10. N+1 nas serializacoes com relacionamento `ativo`.
11. Sem rate limiting.
12. Catalogo (`ativos_catalogo`) e inquilinos sem endpoint proprio.

### BAIXO

13. Sem GET `/ativos/<id>`.
14. `obter_universo` sem rota.
15. Relatorios = contagens, nao relatorio financeiro.
16. Sem CORS explicito.
17. 200 em vez de 201 nas criacoes.
18. VISITOR sem rota `publico.*`.

---

## 10. Endpoints prontos para producao (com `API_ENABLED=true`)

Adequados como leitura autenticada, PostgreSQL, envelope e RBAC:

- `GET /healthz`
- `POST /auth/register`, `/login`, `/logout`
- `GET /me`, `GET /me/plano`
- CRUD admin de usuarios / papel / plano / telegram / sessoes
- API Keys
- Preferencias
- Carteira e ativos acompanhados (exceto teto de listagem)
- Notificacoes (exceto teto de listagem)
- `GET /ativos`
- `GET /mercado/snapshots`
- `GET /mercado/snapshots/mais-recente`
- `GET /mercado/dados-financeiros`
- `GET /mercado/freshness`
- `GET /documentos`
- `GET /relatorios` (como resumo operacional)
- `GET /alertas` para USER e SUPERADMIN (nao para ADMIN)

---

## 11. Endpoints que precisam de correcao

| Endpoint | Problema | Etapa sugerida |
|---|---|---|
| `GET /alertas` | ADMIN 403 | 9.2 (permissao; nao novo sistema) |
| `GET /mercado/cobertura-fii` | JSON/peso/N+1 | 9.2 |
| `GET /mercado/cobertura` | peso no universo | 9.2 (teto/filtro) |
| `GET /indicadores/<id>/historico` | nome/contrato | 9.2 (documentar ou alinhar) |
| Listagens privadas | sem limite HTTP | 9.2 |
| Listagens financeiras | `meta.total` enganoso | 9.2 |

---

## 12. O que deve ser implementado na 9.2

Somente consolidacao da API existente — sem website, Telegram, coletores,
parser FNET, ETF/cripto, assinatura nova, IA.

1. Corrigir matriz: ADMIN deve consultar alertas **ou** a rota deve
   aceitar `alertas.gerenciar` sem criar RBAC paralelo.
2. Serializar `cobertura-fii` / freshness aninhada com o mesmo adapter
   de `serializar_freshness`; exigir ticker ou aplicar teto.
3. Aplicar `obter_limite()` (e, se simples, `offset`) nas listagens que
   ainda devolvem `.all()`.
4. Distinguir no envelope `meta.retornados` vs total, sem quebrar
   clientes de teste alem do necessario.
5. Alinhar filtro `ticker` (exato vs LIKE) e documentar unidades/VPA/DY
   no contrato HTTP — sem inventar valor.
6. Opcional e aditivo: expor `interpretar_indicador` como campo
   `semantica` ao lado do numero, preservando null/zero da 8.2.
7. Decisao operacional de ligar `API_ENABLED` em producao — fora de
   codigo, salvo default consciente.

Nao migrar Sheets. Nao criar endpoint de inquilinos nominais como dado
confiavel (Fase 8 classificou C/D). Nao expor `texto_extraido`.

---

## 13. O que NAO deve ser alterado agora

- Sistema de autenticacao (API Key + sessao) e hashes.
- Envelope `status/data/meta`.
- Regras 8.2-8.6 no pipeline (NULL != 0, CNPJ, datas, semantica de coleta).
- Coletores CVM, INF_MENSAL/TRIMESTRAL, DFP, FNET downloader.
- Modelos ORM e migracoes.
- Telegram, website, motor de alertas, scrapers, universo.
- Parser FNET, WALT, vacancias distintas, ETF/cripto.
- Leitura Sheets do legado (permanece para o bot).

---

## 14. Adequacao a consumidores futuros

| Consumidor | Avaliacao |
|---|---|
| Website | Auth web + `/me` + mercado autenticado existem. Falta paginacao real, semantica 8.5 no JSON, CORS e API ligada. Adequada como base, nao como contrato final. |
| Telegram | Hoje le Sheets (`dashboard_menus`). Pode passar a `services.mercado` / API interna; a API HTTP nao e obrigatoria para o bot. Nao migrar nesta fase. |
| Outros clientes | API Key por usuario ja funciona. Sem rate limit e com `API_ENABLED` off, nao e superficie publica ainda. |

---

## 15. Validacao desta etapa

- Nenhum arquivo fora de `docs/FASE9_ETAPA91_AUDITORIA_API.md` foi
  modificado.
- Testes de evidencia (ja existentes, sem novos casos):
  `tests/test_api.py`, `tests/test_mercado_service.py`,
  `tests/test_auth_web.py`, `tests/test_chaves_api_http.py`:
  **123 passed**, 0 failed.
- `git` no inicio da auditoria: `b278dd4` / tag `v1.3.0`, working tree
  limpa.

8.1 CONCLUIDA no sentido desta etapa: inventario e classificacao com
evidencia de codigo. Nenhuma recomendacao foi implementada.
