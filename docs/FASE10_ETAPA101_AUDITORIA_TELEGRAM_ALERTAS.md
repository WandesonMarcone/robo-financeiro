# Fase 10 — Etapa 10.1: Auditoria do Telegram e sistema de alertas

Documento de auditoria (somente analise). Nao altera codigo, nao cria
endpoints, nao altera banco, nao faz migration, nao refatora legado e nao
implementa as recomendacoes. Data: 2026-09-07.

Base: Fase 9 encerrada (API financeira, 50 endpoints, 1172 testes, Sheets
fora da API). Esta etapa mapeia o que ja existe no Telegram e no motor de
alertas antes da Fase 10 (Telegram multiusuario + inteligencia de alertas).

Working tree no inicio: apenas `docs/FASE9_ETAPA95_VALIDACAO_FINAL.md`
nao commitado. Nenhum arquivo de codigo modificado nesta etapa.

---

## 1. Arquitetura atual

O sistema tem **dois modos de Telegram** que convivem, sem unificacao:

```
                    +------------------+
  Scrapers/Sheets ->| app.py (legado)  |-- disparar_alertas --> TELEGRAM_CHAT_ID
                    +--------+---------+
                             | ESPELHAMENTO_PG_ATIVO
                             v
                    +------------------+
  Snapshots PG  --> | motor_alertas    |-- notificar_telegram --> TELEGRAM_CHAT_ID
                    | (Fase 4)         |-- notificar_individual --> publicador
                    +--------+---------+                              |
                             |                                        v
                             v                            +-------------------+
                    alertas_eventos                       | notificacoes.py   |
                                                          | (elegibilidade)   |
                                                          +--------+----------+
                                                                   v
                                                          notificacoes (PG)
                                                                   v
                                                          dispatcher (5 min)
                                                                   v
                                                          telegram.enviar_notificacao
                                                                   v
                                                          Usuario.telegram_chat_id
```

Simultaneamente, o bot HTTP (webhook) e um **terminal institucional de
operador unico**: menus leem Google Sheets; comandos administrativos
disparam coletores; `/start` nao autentica nem isola usuario.

Tres caminhos de entrega Telegram:

| Caminho | Destino | Origem | Individual? |
|---|---|---|---|
| A. Operador legado | `config.TELEGRAM_CHAT_ID` | `motor_alertas.notificar_telegram` | nao |
| B. Distorsao Sheets | `config.TELEGRAM_CHAT_ID` | `modules.utils.disparar_alertas` (app.py) | nao |
| C. Notificacao individual | `Usuario.telegram_chat_id` | dispatcher via `services.telegram` | sim |

O caminho C e o unico alinhado a Fase 10. A e B continuam ativos e
explicam volume excessivo no chat do operador.

---

## 2. Modulos envolvidos

### 2.1 Telegram / bot

| Arquivo | Papel |
|---|---|
| `bot/loader.py` | Instancia unica `TeleBot`; `_BotNoop` sem token; `enviar_mensagem` |
| `bot/comandos.py` | Comandos `/start` `/status` `/relatorios` e admin de coleta |
| `bot/callbacks_menus.py` | Catch-all de callbacks; menus FII/acao; paineis; docs |
| `bot/handlers.py` | Callbacks de setor/tipo, ajuda, Raio-X, IA |
| `bot/callbacks_revisao.py` | `/revisao` e fluxo de documentos AGUARDANDO_REVISAO |
| `bot/confirmacoes.py` | Confirmacao SUPERADMIN de `/resetar_docs` |
| `services/telegram.py` | Identidade DB + vinculo admin + entrega individual |
| `services/dashboard_menus.py` | Paineis/favoritos/oportunidades **via Sheets** |
| `services/planilhas.py` | Cache gspread (BD_FIIs / BD_Acoes) |
| `modules/seguranca.py` | Papel DB-first com fallback `ADMIN_CHAT_IDS` |
| `modules/utils.py` | `disparar_alertas` (segundo `TeleBot`) |
| `main.py` | Webhook `/{TOKEN}`, scheduler, seed SUPERADMIN |
| `config.py` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `FAVORITOS` |

### 2.2 Alertas / notificacoes

| Arquivo | Papel |
|---|---|
| `pipeline_dados/motor_alertas.py` | Detectar mudanca, classificar, persistir, notificar |
| `pipeline_dados/regras_indicadores.py` | Catalogo FII (8) e ACAO (24) com limiares |
| `pipeline_dados/espelhamento_mercado_5c.py` | Dispara o motor apos snapshot PG |
| `services/publicador_eventos.py` | Isola `processar_evento` (erros nao derrubam 5C) |
| `services/notificacoes.py` | Elegibilidade + persistencia idempotente |
| `services/dispatcher_notificacoes.py` | Entrega WEB/TELEGRAM, retry, job APScheduler |
| `services/preferencias.py` | Flags 1:1 (frequencia **nao e consumida**) |
| `services/ativos_acompanhados.py` | Vinculo usuario-ativo (origem ACOMPANHAMENTO) |
| `services/carteira.py` | Posicao (origem CARTEIRA) |
| `services/planos.py` | `limite.notificacoes_ativas` (20/100/1000) |
| `api/routes/alertas.py` | GET listagem global autenticada |
| `api/routes/notificacoes.py` | CRUD caixa do usuario autenticado |
| `api/routes/preferencias.py` | GET/PATCH preferencias proprias |

### 2.3 Scheduler / pipeline

| Arquivo | Papel |
|---|---|
| `main.py` | `varredura_diaria` 08:00 seg-sex; dispatcher a cada 5 min |
| `services/orquestrador.py` | Varredura B3/CVM + mensagens operacionais ao dono |
| `app.py` | Job GitHub Actions: scrapers Sheets + espelhamento 5C |
| `services/motor_ia.py` | Envia resultado de IA ao `TELEGRAM_CHAT_ID` |

A API HTTP **nao gera** alertas nem envia Telegram. So consulta o que o
pipeline ja persistiu.

---

## 3. Fluxo Telegram

### 3.1 Entrada HTTP

1. `main.py` registra webhook em `WEBHOOK_URL_BASE + "/" + TELEGRAM_BOT_TOKEN`
   (token no path). Sem `secret_token`.
2. POST JSON -> `tele_bot.process_new_updates`.
3. Handlers registrados por import em `main.py` (ordem):
   `callbacks_menus` -> `callbacks_revisao` -> `comandos` ->
   `confirmacoes` -> `handlers`.
4. Sem token: `_BotNoop`, rota de webhook nao registrada.

### 3.2 Identidade

- Mensagem: `message.from_user.id` (Telegram user id).
- Entrega individual: `Usuario.telegram_user_id` + `Usuario.telegram_chat_id`
  (chat_id **nunca** vem do cliente HTTP).
- Resolucao de papel (`modules/seguranca.py`):
  1. Banco por `telegram_user_id` se ATIVO;
  2. DESATIVADO -> VISITOR (sem fallback);
  3. Sem vinculo / banco indisponivel -> legado
     (`SUPERADMIN_CHAT_IDS`, `ADMIN_CHAT_IDS`, `TELEGRAM_CHAT_ID`).
- Sem vinculo, qualquer id cai em **USER legado** (nao VISITOR).
- Vinculo/desvinculo so via API (`telegram.administrar`). **Nao ha
  comando de bot para o usuario se vincular.**

### 3.3 Comandos existentes

| Comando | Auth | Fonte | Observacao |
|---|---|---|---|
| `/start` `/menu` | nenhuma | — | Terminal institucional para qualquer chat |
| `/status` | nenhuma | PG `ativos`/`documentos` | Contagens globais |
| `/relatorios` `/docs` | nenhuma | PG documentos | Ultimos 10 PDFs + URLs |
| `/adicionar TICKER` | ADMIN | **Sheets** | Escreve BD_FIIs/BD_Acoes |
| `/forcar_varredura` | ADMIN | B3/FNET | Thread; responde no chat do autor |
| `/forcar_docs_acoes [ano]` | ADMIN | CVM IPE | Dispara IA se houver novos |
| `/processar_acoes_ia` | ADMIN | Drive/IA | Thread |
| `/forcar_cvm [ano]` | ADMIN | CVM acoes | Thread |
| `/forcar_fiis` | ADMIN | INF_MENSAL | Thread |
| `/alimentar_ia` | ADMIN | PDFs -> `texto_extraido` | Thread |
| `/mapear_nomes` | ADMIN | FNET HTTP | Gera TXT e envia documento |
| `/revisao` | ADMIN | PG revisao | Central hibrida |
| `/resetar_docs` | SUPERADMIN | PG delete | Confirmacao em dois passos |

Help (`ajuda_comandos`) cita `/analisar [TICKER]`: **comando inexistente**.

Callbacks de menu (sem auth): `menu_fiis`, `menu_acoes`, favoritos
globais (`config.FAVORITOS`), oportunidades (filtros fixos em Sheets),
`painel_{ticker}_{tipo}`, dados CVM, lista de PDFs.

### 3.4 Isolamento no bot

**Nao existe.** Menus, `/status` e `/relatorios` mostram o universo
inteiro a qualquer `chat.id`. Favoritos sao lista hardcoded em
`config.py`, nao `ativos_acompanhados`. O bot e um terminal compartilhado
de operador, nao um cliente multiusuario.

Isolamento **existe** na camada C (notificacoes/API): `escopo.py`, 404
cruzado, `usuario_id` ignorado. Essa camada nao e usada pelos menus.

### 3.5 RBAC no bot vs API

Duas matrizes:

- Bot: hierarquia `modules/seguranca.py` (USER < ADMIN < SUPERADMIN).
- API: `services.autorizacao.PAPEL_PERMISSOES`.

Efeitos:

- USER da API tem `notificacoes.consultar`; ADMIN da API **nao** tem
  (so consulta alertas globais). ADMIN autenticado no bot dispara coletas
  mas **nao recebe** notificacoes individuais.
- Comandos admin usam `eh_admin` (Telegram id), nao a matriz da API.
- Fallback legado ainda promove `TELEGRAM_CHAT_ID` a SUPERADMIN se nao
  houver vinculo no banco.

---

## 4. Fluxo de alertas

### 4.1 Geracao

Gatilho principal: `espelhamento_mercado_5c` apos gravar snapshot
(Sheets -> PG, se `ESPELHAMENTO_PG_ATIVO`).

Por ativo, `processar_indicadores_ativo`:

1. Para cada indicador do catalogo (8 FII / 24 ACAO), se valor nao-None:
2. `detectar_mudanca` atualiza `indicadores_historico` (1 linha por
   `(ativo_id, indicador)` — estado atual, nao serie).
3. `gerar_alerta` classifica e, se relevante, persiste `AlertaEvento`.
4. Se `notificar=True` (padrao): **A e C ao mesmo tempo**.

Prioridade do tipo:

1. CRITICO — qualidade critica ou variacao >= limiar critico
2. QUALIDADE — WARNING/ERRO de regra
3. MERCADO — mudou e variacao >= limiar de mercado
4. Senao, nenhum alerta

Primeira observacao: **nao** gera alerta de mercado; **gera** qualidade
se o valor ja nascer fora da faixa. Sem mudanca de valor: so qualidade.

### 4.2 Regras existentes

FII: `preco`, `pvp`, `dy`, `liquidez`, `vpa`, `lucro_12m`,
`dividendo_mensal`, `qtd_imoveis`.

ACAO: `preco`, `dy`, `pl`, `pvp`, `p_ativo`, margens, `p_ebit`,
`ev_ebit`, `div_liq_patrimonio`, `psr`, `p_cap_giro`, `p_at_circ_liq`,
`liq_corrente`, `roe`, `roa`, `roic`, `cagr_rec_5a`, `liq_media`, `vpa`,
`lpa`, `peg_ratio`, `valor_mercado`.

Limiares tipicos: mercado 10–30%, critico 30–60%. Preco FII/acao: 10%/30%.
Negativo legitimo (ROE, margens, LPA) nao e ERRO.

### 4.3 Eventos que disparam alerta de mercado

Hoje **so** mudanca de indicador de snapshot (Sheets espelhado).

Catalogo de `services/notificacoes.py` declara tambem:

- `PRECO_ATINGIDO`, `VARIACAO_PRECO`, `DIVIDENDO`, `DOCUMENTO_NOVO`,
  `RESULTADO_PUBLICADO`, `RELATORIO_DISPONIVEL`

Nenhum coletor/pipeline publica esses tipos. Estao prontos na
elegibilidade, **sem produtor**.

### 4.4 Prioridade / frequencia / duplicidade

- Prioridade de **tipo** no motor (CRITICO > QUALIDADE > MERCADO).
- Planos PREMIUM/PRO tem entitlement `notificacoes.prioridade` —
  **nao usado** na entrega.
- `frequencia_notificacoes` (`imediata|diaria|semanal|desativada`) e
  persistida e exposta na API. **Zero leitura** em
  `notificacoes.py` / `dispatcher_notificacoes.py`. Entrega e sempre
  imediata (dispatcher 5 min).
- Dedup de notificacao: unique
  `(evento_id, usuario_id, tipo, canal)` com
  `evento_id = f"alerta:{alerta.id}"`. Reprocessar o **mesmo** alerta
  nao duplica. Novo `AlertaEvento` = novas notificacoes.
- Unique de `alertas_eventos`: `(ativo_id, indicador, data_evento)`.
  `data_evento = datetime.now()`, logo **quase nunca colide**. Nao ha
  dedup por dia/indicador.

### 4.5 Como chega ao Telegram

1. Imediato no ciclo 5C: mensagem formatada para `TELEGRAM_CHAT_ID`
   (caminho A). `telegram_enviado=True` no evento.
2. Aditivo: `publicar_evento` -> `processar_evento` persiste WEB +
   TELEGRAM para elegiveis.
3. Job `dispatcher_notificacoes` (5 min, `max_instances=1`, retry 3x/60s)
   entrega TELEGRAM so se houver vinculo + `telegram_ativo`.
4. Paralelo: `app.py` consolida distorsoes de scraper e chama
   `disparar_alertas` (caminho B, outro `TeleBot`).

### 4.6 Personalizacao por usuario

Existe na camada C:

- Acompanhar ativo **ou** ter posicao (conforme `origem`).
- Flags: `notificacoes_ativas`, `notificacoes_alertas`, `telegram_ativo`,
  `web_ativo`, `mercado_acoes` / `mercado_fiis` (os dois ultimos **nao
  filtrados** no motor de eventos).
- Limite de caixa nao lida por plano.

Nao existe:

- Digest / lote / silencio / horario
- Uso da frequencia
- Preferencia por indicador, severidade ou ticker alem do acompanhamento
- Comando Telegram para ligar/desligar alertas
- Favoritos de menu ligados a acompanhamentos

Defaults: **tudo ligado**, frequencia `imediata`. Usuario sem linha de
preferencias e tratado como “todos ativos”.

### 4.7 Por que o volume explode

1. Caminho A manda **todos** os alertas ao operador, sem filtro de
   acompanhamento.
2. Caminho C replica para cada USER que acompanha (WEB + TELEGRAM).
3. Caminho B (scrapers) e independente do motor Fase 4.
4. Ate 24 indicadores por acao por ciclo de coleta (cron 5x/dia util).
5. QUALIDADE dispara na primeira carga se o valor ja e outlier.
6. Unique de alerta inclui timestamp -> nao agrupa.
7. Frequencia ignorada -> sem digest diario.
8. Defaults todos True.
9. Mensagens operacionais do orquestrador (inicio/fim de varredura, IA)
   no mesmo chat do operador.
10. Sem rate limit / anti-spam no bot nem no envio de alertas.

---

## 5. Integracoes (DADOS -> EVENTO -> ALERTA -> USUARIO -> TELEGRAM)

```
Google Sheets (fonte ativa scrapers)
    -> app.py grava abas
    -> ESPELHAMENTO_PG_ATIVO?
         nao: so disparar_alertas (B) para TELEGRAM_CHAT_ID
         sim: snapshots_* + processar_indicadores_ativo
                -> indicadores_historico
                -> alertas_eventos
                -> A: TELEGRAM_CHAT_ID
                -> C: publicador -> notificacoes
                       |-- WEB (API /api/v1/notificacoes)
                       `-- TELEGRAM (dispatcher -> chat do usuario)

CVM / FNET / docs
    -> PG documentos / dados_financeiros
    -> orquestrador avisa TELEGRAM_CHAT_ID
    -> NAO gera DOCUMENTO_NOVO / RESULTADO_PUBLICADO

API /api/v1
    -> le alertas_eventos e notificacoes
    -> NAO dispara Telegram
    -> PATCH preferencias (frequencia morta no consumo)

Scheduler
    -> 08:00 varredura_diaria (operador)
    -> a cada 5 min dispatcher (individuais)
```

PostgreSQL e a fonte da API e das notificacoes individuais. Sheets
continua fonte da **UI do bot** e dos scrapers. As duas verdades podem
divergir (ja documentado na Fase 9).

---

## 6. Seguranca

| Tema | Estado | Severidade |
|---|---|---|
| Token do bot | So env; webhook path `/{TOKEN}`; log da URL truncado | MEDIO (secrecy by URL) |
| `secret_token` do webhook | Ausente | MEDIO |
| Chat_id no envio individual | So colunas do `Usuario`; recusado do cliente | OK |
| Chat_id legado | `TELEGRAM_CHAT_ID` recebe o universo | ALTO operacional |
| Autorizacao bot | Admin nos comandos de coleta; menus publicos | ALTO (dado financeiro publico) |
| IDOR/BOLA API | 404 cruzado nas notificacoes | OK |
| IDOR bot | Nao ha recurso por dono; todos veem tudo | ALTO para multiusuario |
| Exposicao entre usuarios (C) | Elegibilidade por acompanhamento + RBAC | OK |
| Exposicao entre usuarios (bot) | Qualquer um ve relatorios/PDFs/CVM | ALTO |
| Logs de secrets | Token nao impresso; auditoria sanitiza `token/senha/key` | OK |
| Comandos destrutivos | `/resetar_docs` SUPERADMIN + confirmar; recheca no callback | OK (se o callback chegar) |
| Rate limit / anti-spam | Nenhum no bot | MEDIO |
| Erros | Varios `str(e)` no Telegram (paths, msgs internas) | BAIXO/MEDIO |
| Fallback legado | Id sem vinculo = USER; `TELEGRAM_CHAT_ID` = SUPERADMIN | MEDIO |
| Catch-all callbacks | `func=lambda call: True` registrado **primeiro** | ALTO de integridade de handlers |
| Segundo TeleBot | `disparar_alertas` instancia bot paralelo | BAIXO |
| ADMIN sem `notificacoes.consultar` | Nao recebe caminho C | MEDIO produto |

Webhook: so aceita `content-type: application/json`; 403 caso contrario.
Quem conhece o token na URL consegue postar updates.

Confirmacao de reset: `confirmacoes.py` revalida SUPERADMIN. Se o
catch-all de `callbacks_menus` interceptar o clique (`reset_confirmar`
nao esta no `if/elif` do catch-all), o botao pode **nao executar**.
Risco de integridade, nao de bypass (o pior caso e o delete nao rodar).

---

## 7. Problemas encontrados

Ordenados por impacto na Fase 10 (nao corrigir agora).

1. Bot e terminal de operador, nao cliente multiusuario.
2. Tres caminhos de Telegram; A+B ignoram preferencias/acompanhamento.
3. Menus e `/status`/`/relatorios` sem autenticacao.
4. UI do bot ainda le Sheets; API ja le PG.
5. Catch-all de callback registrado antes dos handlers especificos.
6. `frequencia_notificacoes` e `mercado_acoes`/`mercado_fiis` mortos no
   consumo.
7. Tipos de evento alem de `ALERTA_MERCADO` sem produtor.
8. Unique de alerta com `data_evento` nao agrupa.
9. QUALIDADE na primeira carga + 24 indicadores = pico de volume.
10. Sem self-service de vinculo Telegram no bot.
11. Favoritos globais hardcoded vs `ativos_acompanhados`.
12. `/analisar` documentado e inexistente.
13. Entitlement `notificacoes.prioridade` / `alertas.avancados` sem uso.
14. Help e mensagens ainda em tom de bot unico.

Nenhum CRITICO de vazamento de hash/token/senha. Nenhum IDOR na API de
notificacoes. O risco dominante e **superficie Telegram publica + dump
no chat do operador**.

---

## 8. Duplicacoes

| Capacidade | Copias |
|---|---|
| Envio Telegram | `bot.loader.enviar_mensagem`, `modules.utils.disparar_alertas` (novo TeleBot), `services.telegram.enviar_notificacao`, `services.motor_ia` (`bot.send_message`) |
| RBAC | `modules.seguranca` (bot) vs `services.autorizacao` (API) |
| Destino | `TELEGRAM_CHAT_ID` vs `Usuario.telegram_chat_id` |
| Dados de mercado na UI | Sheets (`dashboard_menus`) vs PG (`services.mercado` / API) |
| Listagem FII por setor | `handlers.py` (`tipo_fii_`/`setor_fii_`) e `callbacks_menus.py` (`macro_fii_`/`subsetor_fii_`) |
| Alertas de distorsao | Regras de scraper (`disparar_alertas`) vs `motor_alertas` |

---

## 9. Classificacao de reaproveitamento

### REUTILIZAR (base da Fase 10)

- `services/notificacoes.py` — catalogo, elegibilidade, idempotencia, sanitizacao
- `services/dispatcher_notificacoes.py` — entrega, retry, job, anti-IDOR
- `services/telegram.py` — vinculo admin + envio so com chat_id persistido
- `services/preferencias.py` — modelo 1:1 e flags (ligar a frequencia depois)
- `services/autorizacao.py` — matriz; `escopo.py`; `planos.py` limites
- `pipeline_dados/motor_alertas.py` — deteccao/classificacao/persistencia
- `pipeline_dados/regras_indicadores.py` — limiares
- `services/publicador_eventos.py` — isolamento de erro
- `ativos_acompanhados` / `carteira` como filtro de elegibilidade
- `bot/loader.py` (`enviar_mensagem`, `_BotNoop`)
- API ` /notificacoes`, `/preferencias`, `/alertas`, `/ativos-acompanhados`
- Testes: `test_notificacoes`, `test_dispatcher_*`, `test_telegram_etapa8`,
  `test_motor_alertas`, `test_integracao_notificacoes_motor`

### AJUSTAR FUTURAMENTE

- Desligar ou filtrar caminho A (`notificar_telegram` -> chat do dono)
  quando o caminho C estiver no ar
- Consumir `frequencia_notificacoes` (digest)
- Filtrar `mercado_acoes` / `mercado_fiis`
- Auth nos menus / comandos de leitura
- Ordem dos callback handlers (catch-all por ultimo)
- Unique de alerta sem timestamp (ou janela)
- Webhook `secret_token`
- Self-service `/start` que vincula ou pede login
- Produzir `DOCUMENTO_NOVO` / dividendos se a Fase 10 pedir
- Unificar favoritos com acompanhamentos
- ADMIN: decidir se recebe notificacoes individuais

### LEGADO (nao remover nesta fase)

- `TELEGRAM_CHAT_ID` como inbox operacional
- `modules.utils.disparar_alertas`
- `services/orquestrador.py` mensagens de varredura
- Menus Sheets (`dashboard_menus`, `handlers` setor)
- `config.FAVORITOS` / `FILTROS_FIXOS`
- Fallback `ADMIN_CHAT_IDS` / `SUPERADMIN_CHAT_IDS`
- `/adicionar` gravando planilha
- Segundo `TeleBot` nos scrapers

### RISCO / PROBLEMA

- Dados financeiros no bot sem login
- Token no path do webhook sem secret extra
- Catch-all de callback primeiro
- Volume A+B+C
- Frequencia morta (usuario acha que “diaria” vale)
- `str(e)` em respostas
- Qualidade na primeira observacao
- Dois RBACs (bot vs API)

---

## 10. Lacunas para a Fase 10

O que **falta** para Telegram multiusuario + inteligencia de alertas:

1. Identidade no bot: `/start` reconhecer `Usuario`, recusar ou limitar
   VISITOR, self-service de vinculo.
2. Isolamento da UI: paineis/favoritos/alertas so do escopo do usuario
   (ou papel admin explícito).
3. Uma unica tubulacao de entrega (C), com A/B como operacional opt-in.
4. Inteligencia de volume: digest, severidade minima, teto por ciclo,
   agrupar por ativo, honrar frequencia.
5. Ligar produtores aos tipos de evento ja catalogados, se forem
   requisito de produto — ou documentar que so `ALERTA_MERCADO` existe.
6. Migrar leitura do bot de Sheets para `services.mercado` (PG), sem
   desligar Sheets do scraper.
7. Anti-spam de comandos e de envio.
8. Webhook endurecido (`secret_token`).
9. Nao criar endpoints novos nesta fase so para o bot; reusar API
   interna via servicos (nao HTTP).
10. Nao implementar historico temporal (PENDENTE da Fase 9).

Fora de escopo imediato (ja recusado na 9.5): CORS/HTTPS/register
publico, Redis, migration de indicadores.

---

## 11. Recomendacoes para a Etapa 10.2

Somente direcao; **nao implementar agora**.

1. Desenhar o contrato de identidade Telegram-usuario (vinculo, papéis
   no bot alinhados a matriz da API, o que VISITOR ve).
2. Inventariar comandos que permanecem publicos vs autenticados vs admin.
3. Decidir o destino do caminho A (`TELEGRAM_CHAT_ID`): manter como
   canal operacional (varredura/erros) e **sair** da fan-out de
   `AlertaEvento`.
4. Especificar regras de volume (digest, teto, frequencia) reusando
   `preferencias` existentes, sem campo novo se possivel.
5. Nao mexer em coletores, modelos, API de 50 endpoints, nem Sheets
   dos scrapers.
6. Corrigir ordem do catch-all so quando a 10.2/10.3 tocar handlers —
   nao como refactor solto.
7. Testes da 10.2 devem cobrir: isolamento de entrega, nao duplicar
   caminho A+C no mesmo usuario, preferencias desligam o envio.

---

## 12. Validacao desta etapa

Auditoria apenas. Testes existentes executados como evidencia (0 falhas):

| Bloco | Resultado |
|---|---|
| `test_telegram_etapa8` + `test_motor_alertas` + `test_regras_indicadores` + `test_publicador_eventos` + `test_seguranca` + `test_seed` | 106 passed |
| `test_integracao_notificacoes_motor` + `test_preferencias` | 61 passed |
| `test_notificacoes` + `test_dispatcher_notificacoes` | 97 passed |
| **Subtotal evidencia 10.1** | **264 passed, 0 failed** |

Nenhuma suíte nova. Nenhuma correcao de codigo.

Arquivos analisados (leitura): `bot/*`, `services/telegram.py`,
`notificacoes.py`, `dispatcher_notificacoes.py`, `preferencias.py`,
`publicador_eventos.py`, `autorizacao.py`, `planos.py`,
`dashboard_menus.py`, `orquestrador.py`, `motor_ia.py`,
`pipeline_dados/motor_alertas.py`, `regras_indicadores.py`,
`espelhamento_mercado_5c.py`, `modules/seguranca.py`, `modules/utils.py`,
`main.py`, `app.py`, `config.py`, `api/routes/alertas.py`,
`api/routes/notificacoes.py`, testes listados acima.

Alteracoes: **somente este documento**.
