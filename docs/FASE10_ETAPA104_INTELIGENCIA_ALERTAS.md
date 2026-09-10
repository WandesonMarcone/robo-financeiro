# Fase 10 — Etapa 10.4: Inteligencia e priorizacao de alertas

Documento da implementacao real (codigo + testes). Inteligencia
deterministica no motor ja existente (`pipeline_dados/motor_alertas.py`).
Nao cria segundo motor, nao usa LLM, nao cria endpoints, nao migra banco.
Data: 2026-09-09. Status: **CONCLUIDA**.

Base: Etapa 10.3 (preferencias e frequencia no gating de notificacoes).

---

## 1. Fluxo completo

```
EVENTO (coleta 5C / processar_indicadores_ativo)
  -> validacao do dado (PRESENTE/ZERO/AUSENTE/NAO_APLICAVEL/INVALIDO)
  -> relevancia (mudanca real + freshness + semantica utilizavel)
  -> prioridade (CRITICO / ALTO / MEDIO / BAIXO)
  -> persistencia AlertaEvento (se relevante e nao duplicado)
  -> preferencias / frequencia (services/notificacoes, Etapa 10.3)
  -> deduplicacao de notificacao (evento_id, usuario, tipo, canal)
  -> dispatcher
  -> Telegram individual (Usuario.telegram_chat_id)
```

A geracao financeira (`detectar_mudanca` / `gerar_alerta`) nao consulta
preferencias. Preferencias continuam na camada de notificacao.

---

## 2. Criterios de prioridade

Somente dados ja existentes (tipo de alerta Fase 4, severidade da regra,
variacao percentual e limiares do catalogo). Nenhum criterio financeiro
inventado.

| Prioridade | Quando |
|---|---|
| `CRITICO` | Qualidade critica (valor implausivel, `severidade=CRITICO`) OU variacao acima do limiar critico da regra (`limite_variacao_critica_pct`, ex. preco FII 30%). |
| `ALTO` | Qualidade `ERRO` (valor impossivel, ex. preco negativo). |
| `MEDIO` | Alerta de mercado acima do limiar da regra OU qualidade `WARNING` com mudanca de valor. |
| `BAIXO` | Qualidade `WARNING` sem mudanca de valor (dado suspeito na primeira observacao). |

Mapeamento com o tipo legado (`tipo_alerta`):

- `tipo_alerta=CRITICO` -> prioridade `CRITICO`
- `tipo_alerta=QUALIDADE` + `ERRO` -> `ALTO`
- `tipo_alerta=MERCADO` -> `MEDIO`
- `tipo_alerta=QUALIDADE` + `WARNING` sem mudanca -> `BAIXO`

A prioridade vai no payload `dados.prioridade` da notificacao. Nao exige
coluna nova em `alertas_eventos`.

---

## 3. Criterios de relevancia

Um alerta so nasce quando:

1. O valor e utilizavel (`PRESENTE` ou `ZERO` real).
2. A classificacao nao e `IGNORADO`.
3. Ha tipo candidato (qualidade, mercado acima do limiar, ou critico).
4. Freshness nao e `STALE`/`MISSING`, salvo prioridade/tipo `CRITICO`.
5. Nao e repeticao do mesmo evento (ver deduplicacao).
6. Na entrega: o usuario acompanha o ativo, as preferencias permitem, e a
   frequencia da Etapa 10.3 nao bloqueia (exceto teto de volume para
   `CRITICO`).

Recusas (nao enviam):

- variacao abaixo do limiar da regra (`evento_irrelevante`);
- dado sem mudanca relevante de mercado;
- AUSENTE / INVALIDO / NAO_APLICAVEL;
- freshness `STALE`/`MISSING` em nao-criticos;
- alerta repetido com o mesmo valor/regra/tipo.

---

## 4. Deduplicacao

Camada financeira (`alerta_duplicado`): o ultimo `AlertaEvento` do par
`(ativo, indicador)` e comparado pela chave

`(ativo_id, indicador, tipo_alerta, regra, valor_atual)`.

Mesmo valor + mesma regra + mesmo tipo = ruido, nao regenera. Valor novo,
regra nova ou tipo novo = evento legitimo.

Camada de notificacao (Etapa 10.3, preservada):
`(evento_id, usuario_id, tipo, canal)` com `evento_id=alerta:{id}`.

Criticos: a primeira ocorrencia e sempre persistida e publicada. Repetir o
mesmo valor critico nao reenvia; um valor critico *novo* nao e silenciado.

---

## 5. Interacao com preferencias (Etapa 10.3)

Inalterado, com um acrescimo:

- `notificacoes_ativas` / `notificacoes_alertas` / `desativada` / filtros
  `mercado_acoes` e `mercado_fiis` continuam bloqueando, inclusive criticos
  (opt-out explicito).
- `frequencia_notificacoes=diaria|semanal`: teto de volume por janela.
  Prioridade `CRITICO` fura o teto de volume (nao o opt-out).
- Path A continua sem fan-out para `TELEGRAM_CHAT_ID`.
- Dispatcher revalida prefs/RBAC/escopo e entrega em
  `Usuario.telegram_chat_id`.

---

## 6. Tratamento dos estados de dado

Reusa `pipeline_dados.semantica_indicadores` (Fase 8.5):

| Estado | Efeito no motor |
|---|---|
| `PRESENTE` | Avalia qualidade, mudanca, prioridade. |
| `ZERO` | Utilizavel (zero real). Nao e ausencia. Pode gerar WARNING se a regra nao aceita zero. |
| `AUSENTE` | Recusa. Nao grava historico, nao gera alerta, nao inventa 0. |
| `NAO_APLICAVEL` | Recusa. Nao e ausencia nem zero. |
| `INVALIDO` | Recusa. Nao vira evento financeiro positivo. Historico anterior preservado. |

Nunca transformar AUSENTE/INVALIDO em evento financeiro positivo.

Freshness (Fase 8.4): `FRESH` permite; `STALE`/`MISSING` bloqueiam nao
criticos. Sem historico ainda, freshness e `None` (nao bloqueia a primeira
coleta).

---

## 7. Exemplos

1. Preco FII 9.87 -> 11.50 (~16.5%, limiar 10%, critico 30%): `MERCADO` /
   prioridade `MEDIO`. Envia se prefs e acompanhamento ok.
2. Preco FII 9.87 -> 15.00 (~52%): `CRITICO` / prioridade `CRITICO`. Fura
   teto `diaria`/`semanal`; respeita `desativada`.
3. Preco -1.00: `QUALIDADE`/`ERRO` / prioridade `ALTO`. Nao e evento de
   mercado positivo.
4. DY 0.30 (fora da faixa usual, primeira observacao): `QUALIDADE` /
   `WARNING` / prioridade `BAIXO`. Segunda coleta com o mesmo valor: silenciada
   (dedup).
5. Preco 9.87 -> 9.90 (~0.3%): irrelevante. Historico atualiza, sem alerta.
6. Preco `"abc"` ou `"-"`: INVALIDO/AUSENTE. Sem alerta, sem corromper
   historico.
7. ROE -0.10 (negativo legitimo): sem alerta.

---

## 8. Limitacoes

- Sem LLM / Groq / Gemini para decidir envio.
- Sem digest consolidado (teto de volume da 10.3 + prioridade critica).
- Sem coluna `prioridade` em `alertas_eventos` (vai no payload da
  notificacao). Migration desnecessaria.
- Sem novos endpoints, menus Sheets, favoritos, `/analisar`, historico
  temporal.
- Path B (`modules.utils.disparar_alertas`) permanece operacional (scraper).
- Freshness de nao-criticos e lida no historico **antes** de
  `detectar_mudanca` atualizar `ultima_coleta`. Sem historico, freshness e
  `None` (nao bloqueia a primeira coleta). STALE/MISSING bloqueiam MERCADO
  e QUALIDADE; CRITICO continua.

---

## 9. Arquivos

Alterados nesta retomada:

- `pipeline_dados/motor_alertas.py` — `processar_indicadores_ativo` deixa de
  forcar `freshness="FRESH"`; le o historico antes de `detectar_mudanca`.
- `tests/test_etapa104_inteligencia_alertas.py` — testes de pipeline para
  STALE bloqueando MERCADO e nao bloqueando CRITICO.
- `docs/FASE10_ETAPA104_INTELIGENCIA_ALERTAS.md` — este arquivo.

Ja existentes (Etapa 10.4):

- `pipeline_dados/motor_alertas.py` — validacao, relevancia, prioridade,
  dedup no motor existente.
- `services/notificacoes.py` — prioridade `CRITICO` fura teto de frequencia.

Preservados: `services/preferencias.py`, dispatcher (revalidacao 10.3),
Path A sem fan-out, API HTTP.

Migrations: **nenhuma**.

---

## 10. Validacao

Comando principal:

```
python3 -m pytest tests/test_etapa104_inteligencia_alertas.py tests/test_motor_alertas.py -q --tb=short
```

Resultado: **54 passed**.

Regressao relevante: `test_etapa103_preferencias_alertas`,
`test_dispatcher_notificacoes`, `test_notificacoes`,
`test_integracao_notificacoes_motor`, `test_preferencias`,
`test_publicador_eventos`, `test_deduplicacao`, `test_regras_indicadores`,
`test_fase85_semantica`, `test_telegram_etapa102` — todos passaram.

Ambiente: pytest, sqlalchemy, telebot, PyPDF2, pandas, gspread, google-api,
groq e openai estavam ausentes e foram instalados para executar os testes.
Nenhum teste existente foi alterado para mascarar falta de dependencia.

---

## 11. Pendencias (nao 10.4 / para 10.5)

- Digest consolidado (um texto agrupado por janela).
- Menus Sheets / favoritos / `/analisar`.
- Persistir prioridade em coluna propria se a API precisar filtrar.
- Path B operacional ainda fora do motor individual.
