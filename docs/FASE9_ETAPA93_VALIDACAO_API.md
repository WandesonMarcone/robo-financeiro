# Fase 9 — Etapa 9.3: Validacao e consolidacao final da API

Documento de validacao (somente analise e consolidacao). Nao altera codigo,
nao cria endpoints, nao altera banco, nao migra Google Sheets, nao implementa
Website nem Telegram. Data da validacao: 2026-09-06.

Base: Etapa 9.1 (auditoria) + Etapa 9.2 (correcoes). Working tree desta etapa:
unico diff de codigo herdado da 9.2 em `pipeline_dados/numerico.py` (`Decimal`
do ORM classificado como PRESENTE/ZERO, nao INVALIDO). Nenhum endpoint novo.

Escopo: camada HTTP em `api/` e servicos que ela chama. Coletores, scrapers,
Telegram e Website ficam fora, exceto quando a API os consome.

---

## 1. Estado final da API

A Financial API e a superficie HTTP unica de leitura (e de gestao de conta)
sobre PostgreSQL/Neon. Prefixo `/api/v1`. Factory em
`api/blueprint.py` (14 Blueprints, 50 metodos HTTP). Integracao aditiva em
`main.py`: so registra rotas quando `config.API_ENABLED` e verdadeiro.
Padrao: **desabilitada** (`config.py`, `API_ENABLED=false`).

Camadas:

```
Cliente HTTP
  -> api/auth.py (X-API-Key | X-Session-Token)
  -> api/routes/* (query/corpo + permissao)
  -> services/* (mercado, usuarios, escopo, planos, ...)
  -> pipeline_dados.banco_dados (SQLAlchemy / PostgreSQL-Neon)
  -> api/serializadores.py
  -> api/respostas.py (envelope status/data/meta)
```

Envelope: sucesso `{"status":"success","data":...,"meta":...}` + 200;
erro `{"status":"error","data":null,"meta":{"error":"..."}}` + codigo HTTP.
Excecao nao tratada vira 500 generico, sem stack trace.

Correcoes da 9.2 confirmadas nesta validacao:

- ADMIN possui `alertas.consultar`; `GET /alertas` deixa de devolver 403.
- `GET /mercado/cobertura-fii` tem teto, paginacao e JSON estruturado
  (`serializar_cobertura_fii` + `serializar_freshness`; SLA em segundos).
- Colecoes usam `page` / `page_size` / `offset` com teto 500 e `meta.total`
  do filtro, nao o tamanho da pagina.
- Semantica 8.5 viaja no JSON (`campos[].semantica|unidade|escala` e
  campos equivalentes em indicadores). `Decimal` persistido nao e INVALIDO.
- `data_referencia`, `data_coleta` e `fonte` permanecem quando existem.
- Sheets continua fora de `api/`.

A API e a camada oficial de acesso aos dados financeiros **persistidos**.
Nao e ainda uma superficie publica endurecida para producao (ver secao 14).

---

## 2. Quantidade de endpoints

Total: **50** metodos HTTP distintos em `api/routes/`. Nenhum endpoint novo
foi criado nas Etapas 9.2/9.3.

### 2.1 Sistema e autenticacao (4)

| Metodo | Rota | Auth | Authz | Observacao |
|---|---|---|---|---|
| GET | `/api/v1/healthz` | publica | — | liveness |
| POST | `/api/v1/auth/register` | publica | forca USER | anti-enumeracao de email |
| POST | `/api/v1/auth/login` | publica | — | token so na resposta |
| POST | `/api/v1/auth/logout` | `X-Session-Token` | — | ausencia do token = 401 |

### 2.2 Conta e usuarios (13)

| Metodo | Rota | Authz |
|---|---|---|
| GET | `/api/v1/me` | `conta.propria` |
| GET | `/api/v1/me/plano` | `conta.propria` |
| GET | `/api/v1/usuarios` | `usuarios.ler` |
| GET | `/api/v1/usuarios/<id>` | `usuarios.ler` |
| POST | `/api/v1/usuarios` | `usuarios.criar` + politica de papeis |
| PATCH | `/api/v1/usuarios/<id>` | proprio ou `usuarios.criar` |
| POST | `/api/v1/usuarios/<id>/ativar` | `usuarios.ativar` |
| POST | `/api/v1/usuarios/<id>/desativar` | `usuarios.desativar` |
| POST | `/api/v1/usuarios/<id>/papel` | `usuarios.alterar_papel` |
| POST | `/api/v1/usuarios/<id>/plano` | SUPERADMIN |
| POST | `/api/v1/usuarios/<id>/telegram` | `telegram.administrar` |
| DELETE | `/api/v1/usuarios/<id>/telegram` | `telegram.administrar` |
| POST | `/api/v1/usuarios/<id>/sessoes/revogar` | `usuarios.desativar` |

### 2.3 API keys, preferencias, carteira, acompanhados, notificacoes (21)

| Metodo | Rota | Authz | Isolamento |
|---|---|---|---|
| POST | `/api/v1/api-keys` | `conta.propria` | dono = `g.usuario` |
| GET | `/api/v1/api-keys` | `conta.propria` | 404 cruzado |
| GET | `/api/v1/api-keys/<id>` | `conta.propria` | 404 cruzado |
| DELETE | `/api/v1/api-keys/<id>` | `conta.propria` | 404 cruzado |
| GET | `/api/v1/preferencias` | `preferencias.proprias` | 1:1 |
| PATCH | `/api/v1/preferencias` | `preferencias.proprias` | rejeita `usuario_id` |
| POST | `/api/v1/preferencias/restaurar` | `preferencias.proprias` | proprio |
| GET | `/api/v1/carteira` | `carteira.propria` | escopo |
| POST | `/api/v1/carteira` | `carteira.propria` | ignora `usuario_id` |
| GET | `/api/v1/carteira/<id>` | `carteira.propria` | 404 cruzado |
| PATCH | `/api/v1/carteira/<id>` | `carteira.propria` | 404 cruzado |
| DELETE | `/api/v1/carteira/<id>` | `carteira.propria` | 404 cruzado |
| GET | `/api/v1/ativos-acompanhados` | `ativos.proprios` | escopo |
| POST | `/api/v1/ativos-acompanhados` | `ativos.proprios` | ignora `usuario_id` |
| GET | `/api/v1/ativos-acompanhados/<id>` | `ativos.proprios` | 404 cruzado |
| DELETE | `/api/v1/ativos-acompanhados/<id>` | `ativos.proprios` | 404 cruzado |
| GET | `/api/v1/notificacoes` | `notificacoes.consultar` | usuario da sessao |
| GET | `/api/v1/notificacoes/<id>` | `notificacoes.consultar` | 404 cruzado |
| POST | `/api/v1/notificacoes/ler-todas` | `notificacoes.consultar` | proprio |
| POST | `/api/v1/notificacoes/<id>/lida` | `notificacoes.consultar` | 404 cruzado |
| DELETE | `/api/v1/notificacoes/<id>` | `notificacoes.consultar` | 404 cruzado |

### 2.4 Dados financeiros, indicadores, alertas, documentos, relatorios (12)

| Metodo | Rota | Authz | Fonte PG |
|---|---|---|---|
| GET | `/api/v1/ativos` | `dados.consultar` | `ativos` + `ativos_perfil` |
| GET | `/api/v1/mercado/snapshots` | `dados.consultar` | `snapshots_fiis` / `snapshots_acoes` |
| GET | `/api/v1/mercado/snapshots/mais-recente` | `dados.consultar` | idem (1 registro) |
| GET | `/api/v1/mercado/dados-financeiros` | `dados.consultar` | `dados_financeiros_*` |
| GET | `/api/v1/mercado/freshness` | `dados.consultar` | snapshots + contabil + docs |
| GET | `/api/v1/mercado/cobertura` | `dados.consultar` | catalogo + persistido |
| GET | `/api/v1/mercado/cobertura-fii` | `dados.consultar` | campos FII 8.6 |
| GET | `/api/v1/indicadores` | `indicadores.consultar` | `indicadores_historico` |
| GET | `/api/v1/indicadores/<ativo_id>/historico` | `historico.consultar` | estado atual por indicador |
| GET | `/api/v1/alertas` | `alertas.consultar` | `alertas_eventos` |
| GET | `/api/v1/documentos` | `documentos.consultar` | metadados (sem texto/IA) |
| GET | `/api/v1/relatorios` | `relatorios.consultar` | COUNTs agregados |

Comportamento consistente entre grupos: autenticacao unica, envelope unico,
RBAC da matriz central, serializadores campo a campo, filtros de query
validados (400) e teto HTTP nas listagens.

---

## 3. Fonte de dados

Endpoints financeiros leem exclusivamente PostgreSQL/Neon via SQLAlchemy
(`services.db.SessionDB` / `services.mercado` / queries nas rotas).

- PostgreSQL/Neon: **49** endpoints (tudo que persiste ou consulta).
- Sem persistencia: **1** (`GET /healthz`).
- Google Sheets na API: **0**.

Servico de mercado: somente leitura; `None` permanece `None`; teto 500.
Nao ha escrita financeira via HTTP (snapshots, CVM, indicadores, alertas
de mercado nao sao criados pela API).

Persistidos no PG e **nao** expostos por rota dedicada (nao e lacuna desta
etapa; nao criar endpoint agora):

- `ativos_catalogo` (universo 7.2/8.3; `obter_universo` so no servico)
- `ativos_inquilinos` (so dentro de `cobertura-fii`)
- `auditoria_acesso` (trilha interna)
- listagem das proprias sessoes pelo usuario
- `texto_extraido` / `resumo_ia` / `log_erro` (omitidos de proposito)

---

## 4. Dependencia de Sheets

Na pasta `api/`: **nenhuma**.

Busca em `api/**/*.py` por `gspread`, `SPREADSHEET`, `worksheet`,
`BD_FIIs`, `BD_Acoes`, `BD_Logs`, `conectar_gspread`: 0 ocorrencias.
Teste `test_api_nao_usa_google_sheets` cobre o mesmo contrato.

Sheets permanece no **legado fora da API** (`services/planilhas.py`,
`services/dashboard_menus.py`, scrapers, fallback CVM). Nao e caminho
`/api/v1`. Nao precisa ser desligado para a API operar. Nao foi migrado.

---

## 5. Autenticacao e autorizacao

### Autenticacao

- Cabecalhos: `X-API-Key` (prioridade) e `X-Session-Token`.
- Validacao: `services/chaves_api.py` (SHA-256) e `services/sessoes.py`.
- Falha indistinguivel: 401 `"Nao autenticado."` (chave inexistente,
  expirada ou revogada nao se distinguem).
- Login: credenciais invalidas e usuario desativado produzem a mesma 401.
- Chave bruta so no POST de criacao; hash nunca serializado.
- Senha nunca em texto puro nem em auditoria.

### Autorizacao (matriz `PAPEL_PERMISSOES`)

- SUPERADMIN: `"*"`. Unico que atribui SUPERADMIN e altera planos.
- ADMIN: usuarios, dados, documentos, relatorios, indicadores, historico,
  `alertas.consultar`, `alertas.gerenciar`, telegram, `conta.propria`.
  **Nao** promove a SUPERADMIN. **Nao** possui carteira/notificacoes/
  preferencias/acompanhados de terceiros (escopo proprio so do USER).
- USER: consulta financeira + escopo proprio.
- VISITOR / nao autenticado: so `publico.*`. Nenhuma rota da API usa
  essas permissoes; VISITOR autenticado nao le mercado.

Isolamento: `services/escopo.py`. Recurso inexistente e recurso de
terceiro = mesmo 404. `usuario_id` do cliente e ignorado. Plano nunca
aceito em cadastro/PATCH.

ADMIN consulta alertas (corrigido na 9.2). Isolamento entre usuarios
permanece intacto.

---

## 6. Contrato JSON

Consistencia observada:

- Decimal -> float JSON; `None` -> `null`; zero real permanece `0.0`.
- Datas ISO 8601 (`date`/`datetime`).
- Snapshots e dados financeiros: `data_referencia`, `data_coleta`
  (quando a coluna existe), `fonte`, `fonte_primaria`, `url_origem`.
- Semantica 8.5 ao lado do numero: `ZERO` / `AUSENTE` / `NAO_APLICAVEL`
  / `INVALIDO` / `PRESENTE`, com `unidade` e `escala`.
- Unidades: monetario `R$`, fracao `%` (valor persistido 0-1), multiplo
  `x`, quantidade `un.`.
- Dois VPAs / dois DYs rotulados em `proveniencia` (snapshot vs CVM
  INF_MENSAL). Valores armazenados nao sao convertidos.
- Freshness: FRESH/STALE/MISSING; `sla_segundos` (int), sem `timedelta`.
- Documentos: sem `texto_extraido`, `resumo_ia`, `log_erro`.
- Usuario: sem `senha_hash`, sessoes, tokens; Telegram so booleano.

Residuos de contrato (nao bloqueiam leitura, mas o cliente precisa saber):

- Filtro `ticker`: mercado = igualdade exata; ativos/indicadores/alertas/
  documentos = `LIKE %termo%`.
- `GET /indicadores/<ativo_id>/historico` **nao** e serie temporal.
  A tabela guarda o estado mais recente por `(ativo_id, indicador)`.
  A 9.2 documenta isso em `meta.serie_temporal = false`.
- Criacoes HTTP devolvem 200 + `meta.criado`, nao 201.
- `GET /relatorios` e resumo operacional (contagens), nao relatorio financeiro.

---

## 7. Paginacao

Contrato HTTP unico (`api/dependencias.py`):

- `page` 1-indexado (padrao 1)
- `page_size` (precedencia sobre `limite`)
- `limite` legado, mesmo teto
- `meta`: `total`, `page`, `page_size`, `has_next`, `next_page`, `retornados`

Colecoes paginadas (13):

- `/usuarios`, `/api-keys`, `/carteira`, `/ativos-acompanhados`,
  `/notificacoes`, `/ativos`, `/mercado/snapshots`,
  `/mercado/dados-financeiros`, `/mercado/cobertura-fii`,
  `/indicadores`, `/indicadores/<id>/historico`, `/alertas`, `/documentos`

Sem paginacao (por desenho): recursos 1:1 (`/me`, preferencias), itens
unicos (`snapshots/mais-recente`, freshness, GET por id), mutacoes,
`/healthz`, `/relatorios` (agregado).

`GET /mercado/cobertura` **nao** pagina: relatorio completo do catalogo
(ver secao 10). Nao se inventou paginacao onde o contrato e um resumo
unico, exceto este caso, que permanece pesado.

---

## 8. Limites

- Padrao: 100 registros.
- Teto: 500 (`LIMITE_MAXIMO` na HTTP e em `services.mercado`).
- Valores `<= 0` ou invalidos recaem no padrao.
- Planos (Fase 6) limitam criacao de carteira/acompanhados/notificacoes;
  listagem HTTP e independente desses tetos comerciais.
- Sem rate limit de requisicoes (login, register, leitura financeira).

Consultas potencialmente ilimitadas restantes: apenas
`GET /mercado/cobertura` (avalia freshness por ticker do universo).
`cobertura-fii` aplica teto/offset sobre o catalogo e nao percorre a
tabela inteira.

---

## 9. Seguranca

Pontos solidos (evidencia no codigo e nos testes):

- Hash de senha/sessao/API Key nunca na resposta.
- Anti-enumeracao de login/register.
- RBAC central; ADMIN nao escala a SUPERADMIN.
- SUPERADMIN protegido contra ADMIN.
- Escopo 404 (IDOR/BOLA) em carteira, acompanhados, notificacoes, api-keys.
- Preferencias 1:1; `usuario_id` no payload = 400.
- Documentos sem conteudo pesado.
- API desligada por padrao.
- ADMIN le alertas globais (eventos de mercado/qualidade), nao dados
  privados de outro usuario.

Problemas restantes (nenhum CRITICO de vazamento/IDOR):

1. Sem rate limit em login/register/leitura. (MEDIO)
2. `POST /auth/register` publico cria USER irrestrito se a API estiver
   ligada. Intencional na Fase 6; para superficie publica precisa de
   politica. (BAIXO / produto)
3. CORS / HTTPS nao configurados na app Flask da API. Operacional, nao
   e bypass de RBAC. (BAIXO)
4. VISITOR sem rota `publico.*`. (BAIXO)

IDOR/BOLA em recursos com dono: nao encontrado.

---

## 10. Performance

Problemas evidentes (sem otimizacao especulativa nesta etapa):

| Item | Evidencia | Severidade |
|---|---|---|
| `GET /mercado/cobertura` sem teto | `cobertura_catalogo` chama `avaliar_ativo` por ticker do universo, varias categorias | ALTO |
| N+1 `ativo.ticker` | serializadores acessam `registro.ativo` sem `joinedload` | MEDIO |
| `cobertura-fii` por pagina | ainda avalia campo a campo cada FII da pagina (mitigado pelo teto 100/500) | MEDIO |
| Snapshots sem `tipo` | une FII+ACAO em Python e recorta | BAIXO |
| Relatorio geral | COUNTs + GROUP BY | BAIXO |

A 9.1 classificava `cobertura-fii` unbounded como ALTO; a 9.2 removeu
esse risco. O ALTO residual e `/mercado/cobertura`.

---

## 11. Compatibilidade com Website e Telegram

| Consumidor | Avaliacao |
|---|---|
| Website (nao implementado) | Auth web + `/me` + mercado autenticado + paginacao + semantica 8.5 existem. Falta CORS, `API_ENABLED=true` no deploy, e cuidado com `/cobertura`. Adequada como base de consumo autenticado. |
| Telegram | Hoje le Sheets (`dashboard_menus`). Pode passar a `services.mercado` internamente; a API HTTP nao e obrigatoria para o bot. Nao migrar nesta fase. |
| Clientes externos | API Key por usuario funciona. Sem rate limit e com flag off, nao e superficie publica. |

A API esta adequada para ser a fonte unica de dados financeiros de um
Website futuro e de clientes autenticados. Nao substitui o Telegram nesta
etapa.

---

## 12. Problemas restantes

Corrigidos desde a 9.1 (nao reabrir):

- ADMIN sem `alertas.consultar`
- `cobertura-fii` unbounded e freshness nao JSON
- listagens privadas sem teto HTTP
- `meta.total` = tamanho da pagina
- semantica 8.5 ausente no JSON
- `Decimal` classificado como INVALIDO

Ainda abertos (nao implementar nesta etapa):

1. `GET /mercado/cobertura` sem limite / N+1 no catalogo. (ALTO)
2. Sem rate limiting. (MEDIO)
3. N+1 nas serializacoes com `ativo`. (MEDIO)
4. Filtro `ticker` LIKE vs exato. (MEDIO / documentado)
5. `/indicadores/<id>/historico` nao e historico temporal. (MEDIO / documentado)
6. Catalogo e inquilinos sem endpoint proprio. (MEDIO / fora de escopo)
7. `API_ENABLED=false` por padrao. Gate operacional, nao bug. (ALTO operacional)
8. Register publico, CORS ausente, 200 vs 201, VISITOR sem rota publica. (BAIXO)
9. Sem GET `/ativos/<id>`. (BAIXO)

Nenhum desses exige alteracao estrutural imediata nesta etapa. O item 1
e o 7 impedem declarar a API como superficie de producao publica.

---

## 13. Riscos tecnicos

- Ligar `API_ENABLED` sem rate limit expone login/register e leitura
  financeira a abuso.
- `/mercado/cobertura` em catalogo grande pode estourar tempo/CPU/memoria.
- Consumir `/indicadores/.../historico` como serie temporal gera leitura
  errada (estado atual, nao historico).
- Dois VPAs / dois DYs: cliente que misturar snapshot e CVM sem ler
  `proveniencia` / `campos` interpreta escala/origem errada.
- Sheets continua fonte do bot; divergencia temporaria API vs Telegram
  e esperada ate o bot passar a `services.mercado`.
- N+1 de ticker e aceitavel no teto 500, mas cresce com `page_size`.

Nao ha risco de a API ler Sheets, vazar hash/token ou escrever no banco
financeiro.

---

## 14. Classificacao final

A API e a **camada oficial de acesso aos dados financeiros persistidos**
(PostgreSQL/Neon): 50 endpoints, envelope estavel, RBAC, isolamento,
paginacao, contrato 8.5 no JSON, Sheets fora do caminho HTTP.

Nao e superficie publica endurecida: flag desligada por padrao, sem rate
limit, `/cobertura` ainda pesada, CORS ausente.

Classificacao:

**NAO PRONTA PARA PRODUCAO**

Motivo: testes 1156/1156 nao bastam. Restam um endpoint de cobertura sem
teto, ausencia de rate limit e o gate `API_ENABLED=false`. Pode ser
consumida internamente e como base de Website/Telegram apos ligar o flag
com controle operacional; nao deve ser publicada como API financeira
aberta neste estado.

---

## 15. Validacao executada

Testes da API / autenticacao / autorizacao / mercado / cobertura /
serializacao (320 passed):

- `tests/test_fase92_api.py`
- `tests/test_autorizacao.py`
- `tests/test_api.py`
- `tests/test_mercado_service.py`
- `tests/test_auth_web.py`
- `tests/test_chaves_api_http.py`
- `tests/test_fase84_cobertura.py`
- `tests/test_fase86_cobertura_fii.py`
- `tests/test_fase85_semantica.py`
- `tests/test_fase85_escala.py`
- `tests/test_numerico.py`
- `tests/test_escopo.py`
- `tests/test_usuarios_api.py`
- `tests/test_chaves_api.py`

Suite completa `tests/` em blocos: **1156 passed**, 0 failed.
Comparacao com a Etapa 9.2: mesmo total, 0 regressao.

Confirmacoes:

- Nao houve alteracao de banco nesta etapa.
- Nenhum endpoint novo foi criado.
- Sheets continua fora da API.
- Unico arquivo de codigo modificado no working tree permanece o da 9.2
  (`pipeline_dados/numerico.py`); esta etapa so criou este documento.
