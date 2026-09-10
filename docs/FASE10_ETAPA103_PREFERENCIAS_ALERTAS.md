# Fase 10 — Etapa 10.3: Preferencias da Fase 6 no gating de alertas

Documento da implementacao real (codigo + testes). Nao cria endpoints, nao
altera a API HTTP, nao migra menus de Sheets, nao altera banco, nao cria
segundo sistema de preferencias. Data: 2026-09-08.

Base: Etapa 10.2 (identidade Telegram). Esta etapa consome campos ja
existentes em `PreferenciasUsuario` (`frequencia_notificacoes`,
`mercado_acoes`, `mercado_fiis`) na camada de notificacao/dispatcher.

---

## 1. O que ja existia e o que faltava

Ja existia (preservado):

- Modelo `PreferenciasUsuario` com `frequencia_notificacoes`
  (`imediata|diaria|semanal|desativada`), `mercado_acoes`, `mercado_fiis`.
- API GET/PATCH `/api/v1/preferencias` e validacao em
  `services/preferencias.py`.
- Elegibilidade em `services/notificacoes.py`: mestre
  `notificacoes_ativas`, flags de tipo, `web_ativo`/`telegram_ativo`,
  acompanhamento/carteira, limite de plano, idempotencia
  `(evento_id, usuario_id, tipo, canal)`.
- Dispatcher revalida prefs/RBAC/escopo; Telegram so com
  `Usuario.telegram_chat_id` (teste
  `test_dispatcher_nao_usa_telegram_chat_id_legado`).
- Path C: `notificar_individual` -> `publicar_evento` ->
  `processar_evento` -> dispatcher.

Incompleto (corrigido nesta etapa):

- `frequencia_notificacoes` persistida e exposta, **zero leitura** no
  motor de notificacoes e no dispatcher.
- `mercado_acoes` / `mercado_fiis` persistidos, **nao filtrados** na
  elegibilidade.
- Path A: `motor_alertas.notificar_telegram` enviava todo `AlertaEvento`
  para `config.TELEGRAM_CHAT_ID` (fan-out individual no chat do operador).

Nao feito (fora de escopo):

- Novos tipos de alerta, IA, endpoints, migrations.
- Digest consolidado / horario / silencio (so janela de volume).
- Migracao de menus Sheets, favoritos, historico temporal, `/analisar`.
- Etapa 10.4.

---

## 2. Frequencia (`frequencia_notificacoes`)

Consumo exclusivo em `services/notificacoes.py` e revalidacao no
dispatcher. Nenhuma tabela nova. A geracao financeira
(`detectar_mudanca` / `gerar_alerta`) nao consulta preferencias.

| Valor | Efeito na elegibilidade | Entrega |
|---|---|---|
| `imediata` (default) | Gera a cada evento novo (idempotencia por `evento_id` intacta) | Imediata no ciclo do dispatcher |
| `diaria` | No maximo um lote por usuario a cada 24h (`criado_em` na janela) | O que ja foi gerado segue o dispatcher |
| `semanal` | No maximo um lote por usuario a cada 7 dias | Idem |
| `desativada` | Usuario nao e elegivel | Dispatcher marca `preferencias_desativadas` se a linha ja existia |

Implementacao:

- `_frequencia_notificacoes` / `frequencia_efetiva`: normaliza; valor
  desconhecido cai em `imediata`.
- `_volume_frequencia_ok`: `diaria`/`semanal` recusam se ja existe
  `Notificacao` do mesmo `usuario_id` com `criado_em` na janela.
- `_preferencia_ativa`: `desativada` equivale a mestre desligado.

Controle de volume e na camada de notificacao, nao no pipeline 5C.

---

## 3. Filtros de mercado

`mercado_acoes` e `mercado_fiis` (booleanos da Fase 6):

- Evento com `ativo_id` de `TipoAtivo.ACAO`: exige `mercado_acoes`.
- Evento com `ativo_id` de `TipoAtivo.FII`: exige `mercado_fiis`.
- Sem `ativo_id` (evento de sistema, ex. `RELATORIO_DISPONIVEL`): o
  filtro nao bloqueia.
- ETF/CRIPTO e tipo desconhecido: nao usam esses dois campos.

Leitura do tipo: `sessao.get(Ativo, ativo_id).tipo`. Ausencia de ativo
nao filtra. Revalidacao no dispatcher: motivo `mercado_filtrado`.

Preferencias de A nao alteram elegibilidade de B.

---

## 4. Isolamento e fan-out

Path A desligado para alerta individual:

- `notificar_telegram` nao chama `enviar_mensagem`.
- `processar_indicadores_ativo` so chama `notificar_individual`.
- `TELEGRAM_CHAT_ID` permanece para OPERACIONAL (`orquestrador`,
  varredura, `disparar_alertas` de distorcao de scraper).

Path C inalterado no destino: dispatcher ->
`services.telegram.enviar_notificacao` -> `Usuario.telegram_chat_id`.

Regras:

- Usuario sem `telegram_user_id`: so canal WEB (se `web_ativo`).
- ADMIN da matriz nao tem `notificacoes.consultar`: nao recebe alerta
  individual (operador nao e fan-out).
- A nao recebe o de B; prefs de A nao silenciam B.

---

## 5. Arquivos

Alterados:

- `services/notificacoes.py` — frequencia, volume, filtro de mercado.
- `services/dispatcher_notificacoes.py` — revalida frequencia e mercado.
- `pipeline_dados/motor_alertas.py` — Path A sem fan-out.
- `tests/test_motor_alertas.py` — espera ausencia de envio legado.
- `tests/test_integracao_notificacoes_motor.py` — mesmo.
- `tests/test_etapa103_preferencias_alertas.py` — novo.
- `docs/FASE10_ETAPA103_PREFERENCIAS_ALERTAS.md` — este arquivo.

Preservados: `services/preferencias.py` (sem campos novos),
`bot/identidade.py`, webhook 10.2, API de 50 endpoints.

Migrations: **nenhuma**.

---

## 6. Testes

Cobre: `desativada` / `imediata` / `diaria` / `semanal`; janela diaria
libera apos 24h; `mercado_acoes`/`mercado_fiis` por tipo; evento sem
ativo; isolamento A/B; sem vinculo = sem TELEGRAM; dispatcher nao usa
`TELEGRAM_CHAT_ID`; admin nao recebe individual; idempotencia;
geracao financeira independente da frequencia.

---

## 7. Pendencias (nao 10.3)

- Digest consolidado (um texto agrupado) — so teto por janela.
- Menus Sheets / favoritos / `/analisar`.
- Path B (`modules.utils.disparar_alertas`) ainda operacional.
- Etapa 10.4.
