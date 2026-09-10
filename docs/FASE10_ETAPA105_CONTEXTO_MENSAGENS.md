# Fase 10 — Etapa 10.5: Contexto e qualidade da mensagem de alerta

Documento da auditoria e da implementacao real. Nao cria segundo motor,
nao usa LLM, nao cria endpoints, nao migra banco. Data: 2026-09-09.
Status: **CONCLUIDA**.

Base: Etapa 10.4 (inteligencia e priorizacao deterministica).

---

## 1. Fluxo preservado

```
EVENTO -> validacao -> relevancia -> prioridade
      -> preferencias/frequencia -> dedup
      -> dispatcher -> Telegram individual
```

A 10.5 altera somente o texto e o payload da mensagem. Nao mexe em
regras de prioridade, gating 10.3, deduplicacao nem isolamento.

---

## 2. Auditoria do estado anterior

Geracao: `pipeline_dados/motor_alertas.formatar_mensagem` alimenta
`notificar_individual` (`titulo` + `mensagem` + `dados`). Persistencia:
`services.notificacoes.processar_evento`. Entrega: dispatcher ->
`services.telegram.enviar_notificacao` ->
`[NOTIFICACAO] {titulo}\n\n{mensagem}` no `Usuario.telegram_chat_id`.

### O que ja estava na mensagem

| Campo | Antes |
|---|---|
| Tipo de evento | Sim (`ALERTA DE MERCADO` / `QUALIDADE` / `CRITICO`) |
| Ticker | Sim, linha solta sem rotulo |
| Tipo de ativo | Sim, linha solta |
| Indicador | Sim, chave interna (`preco`) |
| Valor anterior | Sim, omitido se None |
| Valor atual | Sim |
| Variacao | Sim, omitida se None |
| Motivo | Sim |
| Severidade | Sim |
| Prioridade 10.4 | Sim, se `_prioridade` existir |
| Recomendacao | Sim |

### Lacunas reais (nao hipotese)

1. **Data** (`data_referencia`) existia no `AlertaEvento` e no payload
   `dados`, mas **nao ia para o Telegram**.
2. **Origem/proveniencia** (`origem`) idem: persistida, ausente no texto.
3. **Freshness** (FRESH/STALE/MISSING) era usada na relevancia 10.4, mas
   nao ia para a mensagem nem para `dados` da notificacao.
4. **Rotulo CRITICO inconsistente**: corpo `ALERTA CRITICO`, titulo
   `ALERTA CRÍTICO` (acento). Telegram/ASCII divergiam.
5. Identificacao do ativo era so o ticker solto, sem rotulo `Ativo:`.

### O que nao faltava (nao alterado)

- Preferencias, frequencia, dedup, isolamento, dispatcher.
- Estados PRESENTE/ZERO/AUSENTE/NAO_APLICAVEL/INVALIDO.
- Regras de prioridade CRITICO/ALTO/MEDIO/BAIXO.
- Path A sem fan-out para `TELEGRAM_CHAT_ID`.
- Coluna nova / migration: desnecessaria (`_freshness` em memoria,
  `origem`/`data_referencia` ja no modelo).

---

## 3. Mensagem apos 10.5

Exemplo (mercado FII, prioridade MEDIO):

```
* ALERTA DE MERCADO

Ativo: MXRF11
Tipo: FII
Indicador: Preco (preco)
Anterior: 9.87
Atual: 11.5
Variacao: 16.51%

Motivo: Alteracao relevante de 16.51% em Preco.
Severidade: OK
Prioridade: MEDIO
Data: 2026-08-19
Origem: Google Sheets
Freshness: FRESH

Analisar antes de considerar o dado como evento real.
```

Regras de omissao (nao inventar):

- Sem valor anterior -> nao imprime `Anterior:`.
- Sem variacao -> nao imprime `Variacao:`.
- Sem prioridade/data/origem/freshness -> omite a linha.
- Valor atual ausente -> `Atual: -` (nunca inventa numero).
- AUSENTE/INVALIDO/NAO_APLICAVEL continuam sem gerar alerta.

Titulo da notificacao usa o mesmo rotulo ASCII:
`MXRF11 — ALERTA CRITICO` (sem acento).

---

## 4. Arquivos

- `pipeline_dados/motor_alertas.py` — `formatar_mensagem` com rotulos,
  data, origem, freshness; `_rotulo_alerta` unico; `_freshness` no
  evento e no payload `dados`.
- `tests/test_etapa105_contexto_mensagens.py` — novo.
- `docs/FASE10_ETAPA105_CONTEXTO_MENSAGENS.md` — este arquivo.

Preservados: `services/notificacoes.py`, dispatcher, preferencias,
motor de prioridade 10.4.

Migrations: **nenhuma**.

---

## 5. Validacao

```
python3 -m pytest tests/test_etapa105_contexto_mensagens.py tests/test_motor_alertas.py tests/test_etapa104_inteligencia_alertas.py tests/test_etapa103_preferencias_alertas.py tests/test_telegram_etapa102.py -q --tb=short
```

Resultado: **124 passed**.

---

## 6. Fora de escopo (nao 10.5)

- Digest consolidado.
- Markdown Telegram / emojis.
- Coluna `prioridade`/`freshness` em `alertas_eventos`.
- Path B (`modules.utils.disparar_alertas`).
- Fase 11.
