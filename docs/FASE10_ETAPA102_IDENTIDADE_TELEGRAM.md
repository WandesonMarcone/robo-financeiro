# Fase 10 — Etapa 10.2: Identidade Telegram

Documento da implementacao real (codigo + testes). Nao cria endpoints, nao
altera a API HTTP, nao migra menus de Sheets, nao altera banco. Data:
2026-09-08.

Base: Etapa 10.1 (auditoria). Working tree no inicio desta continuacao:
limpo (`master`, `29d9c8c`). A implementacao ja estava parcialmente no
commit inicial (`bot/identidade.py`, `services/telegram.py`, handlers
com `exigir_fluxo_*`, webhook `secret_token`). Esta etapa auditou esse
estado, preservou o correto, corrigiu o catch-all e acrescentou testes
e este documento.

---

## 1. O que ja existia e o que faltava

Ja implementado (preservado):

- Ponte Telegram ID -> `Usuario` existente (`services.telegram.usuario_do_telegram`).
- Vinculo administrativo (`telegram.administrar`) e autoatendimento por
  token de sessao web/API (`vincular_telegram_por_sessao`).
- Classificacao PUBLICO / USUARIO / OPERACIONAL (`fluxo_do_telegram`).
- Camada do bot em `bot/identidade.py` (unica; sem segunda identidade).
- Guardas `exigir_fluxo_mensagem` / `exigir_fluxo_callback` nos comandos
  e callbacks.
- Menus financeiros omitidos no teclado PUBLICO (`markup_inicio`).
- Webhook `secret_token` via `TELEGRAM_WEBHOOK_SECRET` (ambiente).
- `config.py` le o segredo do ambiente; `.env.example` documenta a var.

Incompleto / incorreto (corrigido nesta continuacao):

- Catch-all `func=lambda call: True` em `bot/callbacks_menus.py`
  registrado **antes** dos handlers dedicados (`main.py` importava
  `callbacks_menus` primeiro). FIFO do pyTelegramBotAPI interceptava
  `ajuda_comandos`, `ajuda_roadmap`, `rev_*`, `ia_*`, reset, etc.
- Ausencia de `tests/test_telegram_etapa102.py`.
- `TELEGRAM_WEBHOOK_SECRET` existia em `config` / `.env.example`, mas
  `test_config_fase5.py` so verificava `hasattr`.

Nao feito (fora de escopo):

- Migrar menus de Sheets para PostgreSQL (10.3+).
- Novos endpoints / alteracao da API.
- Migration de banco.
- Digest/volume de alertas (recomendacao 10.1 item 4).

---

## 2. Mecanismo Telegram ID -> User

Fonte unica: tabela `usuarios.telegram_user_id`.

```
message.from_user.id  (ou callback.from_user.id)
        |
        v
telegram.usuario_do_telegram(id)
        |
        v
usuarios.buscar_usuario_por_telegram(id)
        |
        +-- Usuario encontrado -> fluxo_do_telegram classifica pelo papel
        +-- None               -> PUBLICO (ou OPERACIONAL legado se eh_admin)
```

Regras reais em `services/telegram.py`:

- Nao cria `Usuario`. Nao cria `Sessao`.
- `usuario_do_telegram(None)` retorna `None`.
- `fluxo_do_telegram`:
  - SUPERADMIN/ADMIN ativo -> `operacional`
  - USER ativo -> `usuario`
  - VISITOR, desativado (`papel_de` = None), sem vinculo -> `publico`
  - Sem vinculo + `modules.seguranca.eh_admin(id)` -> `operacional` (legado)
- `comando_permitido(id, minimo)`: PUBLICO sempre; USUARIO aceita
  usuario+operacional; OPERACIONAL so operacional.

O bot extrai o id em `bot/identidade.telegram_id` (`from_user.id`) e
delega ao servico. Nao ha segunda implementacao de identidade.

---

## 3. Mecanismo de vinculacao

Dois caminhos, ambos gravam o mesmo `Usuario.telegram_user_id`:

### 3.1 Administrativo (ja existia na Etapa 8)

`vincular_telegram_usuario(autor, usuario, telegram_user_id)` exige
`telegram.administrar`. Reutiliza `usuarios.vincular_telegram`
(unicidade no banco; `ValueError` se o ID ja pertence a outro).

### 3.2 Autoatendimento (Etapa 10.2)

`/start TOKEN` -> `identidade.processar_start` ->
`telegram.payload_comando_start` -> `vincular_telegram_por_sessao`.

O TOKEN e o token bruto da sessao web/API (`sessoes.criar_sessao` /
`sessoes.validar_sessao`). Nao e um codigo arbitrario, nao e o
Telegram ID, nao e senha.

Falhas (todas retornam `None` + auditoria `TELEGRAM_VINCULO_SESSAO_NEGADO`,
sem revelar a etapa e sem gravar o token):

- token ausente/invalido/expirado/revogado (`sessao_invalida`)
- Telegram ID nulo (`telegram_ausente`)
- Telegram ja vinculado a outro usuario (`telegram_em_uso`)
- Usuario da sessao ja vinculado a outro Telegram (`usuario_ja_vinculado`)
- `ValueError` de unicidade (`vinculo_rejeitado`)

Quem prova a sessao vincula **somente a si mesmo**. Nao usa
`telegram.administrar`. Idempotente se o mesmo par usuario/Telegram
ja estiver vinculado.

Usuario nao vinculado permanece PUBLICO: `/status`, `/relatorios`,
coleta, Raio-X, revisao e menus financeiros sao bloqueados
(`exigir_fluxo_*` responde e retorna False).

---

## 4. Isolamento

- Unicidade de `telegram_user_id` no banco: um Telegram nao pode
  representar dois usuarios.
- `recurso_visivel_para_telegram` devolve o recurso so se o Usuario
  vinculado passar em `escopo.usuario_pode_acessar`. Sem vinculo,
  recurso alheio ou desativado: `None` (anti-IDOR).
- Entrega individual (`enviar_notificacao`) usa apenas
  `Usuario.telegram_chat_id` persistido — o cliente nunca informa o
  chat de destino.
- Dois Telegram IDs distintos resolvem usuarios distintos.

Menus do bot ainda leem Sheets para o universo de ativos (legado,
fora desta etapa). O isolamento de identidade impede que um chat
nao vinculado acesse esses menus; o isolamento de carteira/favoritos
por usuario permanece na API/`escopo`, nao nos paineis Sheets.

---

## 5. Separacao dos fluxos

| Fluxo | Quem | Teclado inicial | Comandos |
|---|---|---|---|
| PUBLICO | sem vinculo, VISITOR, desativado | so Ajuda | `/start` `/menu` |
| USUARIO | USER ativo vinculado | FIIs, Acoes, Macro, Ajuda | menus de mercado (callback USUARIO) |
| OPERACIONAL | ADMIN/SUPERADMIN vinculado ou `eh_admin` legado | mesmo teclado de USUARIO | coleta, `/status`, `/relatorios`, revisao, reset (SUPERADMIN extra) |

Callbacks publicos (`voltar_menu`, `menu_ajuda`, `ajuda_comandos`,
`ajuda_roadmap`) passam mesmo quando o catch-all exige USUARIO:
`exigir_fluxo_callback` libera `CALLBACKS_PUBLICOS` antes da checagem.
O teclado PUBLICO nao inclui `menu_fiis` / `menu_acoes` / `menu_macro`.

Comandos operacionais em `bot/comandos.py` passam por
`_exige_operacional` (`FLUXO_OPERACIONAL`). `/resetar_docs` ainda
exige `seguranca.eh_superadmin` depois do fluxo.

---

## 6. Catch-all

Problema real: `@bot.callback_query_handler(func=lambda call: True)`
em `callbacks_menus.py` era importado primeiro em `main.py`. O
pyTelegramBotAPI avalia handlers na ordem de registro.

Correcao:

1. Predicado `identidade.callback_pertence_ao_menu`: recusa
   `ajuda_roadmap`, `ajuda_comandos`, `ver_raiox_docs`,
   `reset_confirmar`, `reset_cancelar` e prefixos `tipo_fii_`,
   `setor_fii_`, `setor_acao_`, `ia_`, `ajuda_cvm_`, `rev_`.
2. Import em `main.py`: `callbacks_revisao`, `comandos`,
   `confirmacoes`, `handlers`, e `callbacks_menus` por ultimo.

Assim `ajuda_comandos` / `ajuda_roadmap` (handlers publicos em
`handlers.py`) nao sao engolidos pelo catch-all de menus.

---

## 7. Protecao do webhook

`config.TELEGRAM_WEBHOOK_SECRET = os.environ.get(..., "").strip()`.
Nunca hardcoded.

`main.py`:

- `set_webhook(**telegram.parametros_set_webhook(url))` inclui
  `secret_token` so se o ambiente tiver valor.
- POST `/{TELEGRAM_BOT_TOKEN}`: exige `content-type: application/json`
  e header `X-Telegram-Bot-Api-Secret-Token` comparado com
  `hmac.compare_digest`. Sem segredo configurado, aceita o legado
  (so o token no path) e emite aviso em `verificar_configuracao`.
- Logs: "Webhook secret_token ativo (valor omitido)" — o valor nao
  e impresso. Comparacao nao registra recebido nem esperado.

---

## 8. Arquivos

Preservados (auditados, nao revertidos):

- `bot/identidade.py` (identidade unica do bot)
- `services/telegram.py` (ponte + vinculo por sessao + webhook)
- `bot/handlers.py`, `bot/comandos.py`, `bot/confirmacoes.py`,
  `bot/callbacks_revisao.py` (guardas de fluxo)
- `config.py`, `.env.example`

Alterados nesta continuacao:

- `bot/identidade.py` — predicado `callback_pertence_ao_menu`.
- `bot/callbacks_menus.py` — catch-all usa o predicado (nao `True`).
- `main.py` — ordem de import dos handlers.
- `tests/test_config_fase5.py` — secret lido do ambiente.
- `tests/test_telegram_etapa102.py` — novo.
- `docs/FASE10_ETAPA102_IDENTIDADE_TELEGRAM.md` — este arquivo.

Migrations: **nenhuma**.

---

## 9. Testes

| Bloco | Resultado |
|---|---|
| `test_telegram_etapa102` + `test_config_fase5` + `test_telegram_etapa8` | 75 passed |
| regressao: + `test_sessoes` + `test_seguranca` + `test_escopo` + `test_usuarios` | **163 passed, 0 failed** |

Cobre: resolucao Telegram->User, token de sessao obrigatorio,
associacao arbitraria recusada, nao vinculado sem acesso autenticado,
isolamento, fluxos, markup PUBLICO sem menus financeiros, catch-all
vs handlers publicos, webhook secret via ambiente, token/segredo
ausentes da auditoria/logs.

---

## 10. Pendencias (nao 10.2)

- Menus ainda leem Google Sheets (`dashboard_menus` / `planilhas`).
- Favoritos do bot continuam `config.FAVORITOS`, nao
  `ativos_acompanhados`.
- Caminho A (`TELEGRAM_CHAT_ID` fan-out de alertas) intacto (10.1).
- `ajuda_comandos` ainda cita `/analisar` (comando inexistente).
- Webhook ainda autentica tambem pelo token no path (legado).
- Etapa 10.3 nao iniciada.
