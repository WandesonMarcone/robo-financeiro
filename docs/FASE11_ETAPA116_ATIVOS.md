# Fase 11 — Etapa 11.6: area de ativos e detalhamento

Documento da implementacao real (codigo + testes). Substitui o
placeholder autenticado de `/ativos` pela listagem e pelo detalhe de
um ticker. Nao avanca para a 11.7. Data: 2026-09-10.

Base: Etapa 11.5 (dashboard MVP) e contrato 11.1/11.2 (composicao de
GETs existentes, sem BFF).

Regra:

```
Website (Next.js) -> reverse proxy /api -> Flask /api/v1 -> PostgreSQL
```

Nenhum acesso a banco, Sheets, Fundamentus, Yahoo, CVM, FNET ou
scrapers no frontend. Nenhuma regra financeira nova no cliente.

---

## 1. Objetivo

Criar a area operacional de ativos do Website Estrategia Fardada:

- `/ativos` — catalogo autenticado, pesquisa por ticker (igualdade
  exata) e filtro `tipo` ACAO/FII;
- `/ativos/[ticker]` — detalhe montado com GETs existentes;
- estados PRESENTE / ZERO / AUSENTE / NAO_APLICAVEL / INVALIDO;
- freshness FRESH / STALE / MISSING quando a API fornecer;
- loading, vazio, erro, 401, 403 e ativo inexistente.

O backend continua autoridade de autenticacao, RBAC e isolamento.

---

## 2. Endpoints utilizados (somente existentes)

Nenhum endpoint novo. Nenhum BFF. Composicao no cliente.

| Metodo | Caminho | Uso |
|---|---|---|
| GET | `/api/v1/ativos?ticker=&tipo=&page=&page_size=` | catalogo; `ticker` e igualdade exata |
| GET | `/api/v1/mercado/snapshots` | preco/indicadores na listagem (janela paginada) |
| GET | `/api/v1/mercado/snapshots/mais-recente?ticker=` | cotacao do detalhe |
| GET | `/api/v1/indicadores?ticker=` | estado atual dos indicadores no detalhe |
| GET | `/api/v1/mercado/freshness?ticker=` | FRESH/STALE/MISSING no detalhe |
| GET | `/api/v1/carteira` | badge "Carteira" somente se a API devolver o ticker |
| GET | `/api/v1/ativos-acompanhados` | badge "Acompanhado" somente se a API devolver o ticker |

Nao usados de proposito:

- `GET /indicadores/<id>/historico` — `meta.serie_temporal = false`;
- `GET /mercado/dados-financeiros` — contabil CVM fica para etapa futura;
- `GET /mercado/cobertura` / `cobertura-fii` — relatorio de cobertura, nao tela de ativo;
- CRUD de `/carteira` e `/ativos-acompanhados` — somente leitura de vinculo.

Nao ha `GET /ativos/<id>`. O detalhe resolve por `GET /ativos?ticker=`
(igualdade exata), conforme 11.1.

---

## 3. Pesquisa

Contrato da API (`api/routes/ativos.py` e hardening 9.4):

- `ticker` — igualdade exata apos `strip().upper()`;
- `tipo` — somente `ACAO` ou `FII` (400 caso contrario);
- substring / prefixo / sufixo **nao** encontram o ativo.

O frontend:

1. normaliza o input para maiusculas;
2. envia exatamente `?ticker=PETR4`;
3. **nao** filtra a lista no cliente;
4. se a API devolver `[]` para `PETR`, a tela permanece vazia — nao
   sugere PETR4.

---

## 4. Dados exibidos

Somente campos retornados pela API.

Listagem:

- ticker, tipo, setor/tipo_fii (cadastro);
- preco, DY, P/VP, VPA (snapshot, se presente na janela);
- data de referencia e data de coleta do snapshot;
- badges Carteira / Acompanhado quando o ticker aparece em
  `GET /carteira` ou `GET /ativos-acompanhados`.

Detalhe:

- ticker, tipo, CNPJ, setor, tipo_fii;
- preco, fonte, data_referencia, data_coleta;
- todos os campos de `campos` do snapshot (semantica/unidade/escala);
- indicadores persistidos (`valor_atual`, semantica, origem, datas);
- freshness por categoria;
- proveniencia / fonte_primaria / fonte_intermediaria quando presentes;
- vinculo de carteira/acompanhamento do usuario autenticado.

Nao ha recálculo de indicador. Nao ha grafico. Nao ha serie historica.

---

## 5. Semantica

`frontend/src/lib/format.ts` (11.5) permanece a unica camada de
exibicao:

- `null` / ausencia -> `AUSENTE` (nunca `0`);
- `0` real -> `ZERO`;
- `campos.*.semantica` / `indicador.semantica` tem precedencia;
- `aplicavel=false` -> `NAO_APLICAVEL`;
- `INVALIDO` permanece `INVALIDO`.

Unidades da API (`%`, `R$`, `x`, `un.`) sao exibidas, nao recalculadas.

---

## 6. RBAC e isolamento

- Token somente em `X-Session-Token`. Nunca na URL.
- 401 propaga e encerra a sessao local (contrato 11.4).
- 403 de `GET /ativos` vira estado de acesso negado — sem catalogo inventado.
- 403 de snapshots / indicadores / freshness / carteira / acompanhados
  aparece na secao correspondente; as demais secoes seguem com o que
  a API devolveu.
- ADMIN sem `carteira.propria` / `ativos.proprios` nao recebe badge
  de vinculo e ve 403 na secao, nao dados de terceiros.

---

## 7. Interface

Identidade da 11.3/11.5 preservada (sand / olive / gold, Allerta
Stencil, Montserrat ExtraBold, Inter). Header e sidebar permanecem.
A pagina de ativos acrescenta:

- formulario de pesquisa (ticker exato + tipo);
- tabela paginada (`page` / `page_size` da API);
- detalhe em cards (cadastro, preco, freshness, vinculo, indicadores).

Responsivo: formulario empilha no celular; tabela com scroll
horizontal (`overflow-x-auto`); cards em 1/2/4 colunas.

---

## 8. Estados tratados

| Estado | Onde |
|---|---|
| loading | listagem e detalhe |
| vazio | catalogo sem linhas; pesquisa sem igualdade |
| erro | HTTP 5xx / falha de comunicacao |
| 401 | listagem e detalhe |
| 403 | catalogo, snapshots, indicadores, freshness, vinculo |
| ativo inexistente | `GET /ativos?ticker=` com `data: []` |
| AUSENTE / ZERO / NAO_APLICAVEL / INVALIDO / PRESENTE | indicadores e snapshot |
| FRESH / STALE / MISSING | freshness |

Erros nao sao mascarados.

---

## 9. O que esta etapa nao fez

- carteira completa / CRUD;
- sistema de alertas completo;
- documentos, pagamentos, Premium, conteudo, Instagram;
- LLM, chatbot, Telegram;
- nova autenticacao, tabela ou migration;
- serie historica / grafico;
- endpoint BFF `/dashboard` ou `/ativos/:id`;
- integracao direta com Sheets / CVM / FNET / yfinance / Fundamentus;
- Etapa 11.7.

---

## 10. Limitacoes reais (nao inventadas)

1. **Sem GET /ativos/:id.** Detalhe = `?ticker=` exato.
2. **Snapshots da listagem sao globais.** Cruzamento por ticker na
   pagina 1 (`page_size` 500). Se o ticker da pagina de catalogo nao
   estiver nessa janela, preco/DY ficam `AUSENTE`.
3. **Indicadores da listagem** so sao pedidos quando ha pesquisa por
   ticker; o catalogo amplo mostra indicadores de snapshot.
4. **Freshness N+1** so no detalhe (um ticker).
5. **Vinculo de carteira** usa a pagina 1 de `/carteira` e
   `/ativos-acompanhados` (`page_size` 500). Tickers fora dessa janela
   nao recebem badge.
6. **Sem MtM oficial.** Quantidade e valor_investido so aparecem no
   detalhe se a carteira do usuario devolver a posicao.
7. **Sem serie temporal.** Indicadores sao estado atual.

---

## 11. Arquivos

### Criados

| Arquivo | Papel |
|---|---|
| `frontend/src/lib/resource.ts` | helper 401/403/404 compartilhado |
| `frontend/src/lib/ativos.ts` | composicao dos GETs da area |
| `frontend/src/lib/ativos.test.ts` | contrato de pesquisa/semantica |
| `frontend/src/components/AtivosView.tsx` | listagem autenticada |
| `frontend/src/components/AtivoDetalheView.tsx` | detalhe autenticado |
| `frontend/src/components/AtivoRow.tsx` | linha da tabela |
| `frontend/src/app/ativos/[ticker]/page.tsx` | rota de detalhe |
| `frontend/src/components/ativos.test.tsx` | listagem, pesquisa, detalhe, RBAC |
| `docs/FASE11_ETAPA116_ATIVOS.md` | este documento |

### Alterados

| Arquivo | Papel |
|---|---|
| `frontend/src/app/ativos/page.tsx` | placeholder -> listagem real |
| `frontend/src/lib/api.ts` | GET /ativos, snapshot mais recente, filtros |
| `frontend/src/lib/types.ts` | `AtivoCatalogo`, proveniencia, freshness extra |
| `frontend/src/lib/dashboard.ts` | reutiliza `resource.ts` |
| `frontend/src/lib/api.test.ts` | igualdade exata do ticker |
| `frontend/src/components/SectionState.tsx` | importa ResourceState de resource |
| `frontend/src/components/Sidebar.tsx` | ativo em `/ativos/[ticker]` |

---

## 12. Testes

Frontend (Vitest):

- listagem com dados reais da API;
- pesquisa por ticker (igualdade exata; substring nao encontra);
- detalhamento;
- ativo inexistente;
- indicadores PRESENTE / ZERO / AUSENTE / NAO_APLICAVEL / INVALIDO;
- freshness;
- loading (listagem e detalhe);
- empty;
- erro;
- 401;
- 403;
- isolamento de `X-Session-Token`;
- tabela com scroll horizontal (responsividade).

Backend (regressao, sem alteracao de API):

- `tests/test_api.py`
- `tests/test_auth_web.py`
- `tests/test_carteira.py`
- `tests/test_ativos_acompanhados.py`
- `tests/test_fase112_cors_deploy.py`
- `tests/test_fase94_hardening.py`
- `tests/test_fase84_freshness.py`

---

## 13. Verificacao

| Checagem | Resultado |
|---|---|
| Vitest | 62 testes aprovados (11 arquivos) |
| lint (`next lint`) | passou, sem warnings |
| tsc (`npx tsc --noEmit`) | passou |
| pytest (regressao acima) | 175 testes aprovados |

---

## 14. Problemas encontrados

1. Ambiente Python do workspace nao tinha pytest nem varias
   dependencias de import (PyPDF2, google, gspread, pandas, groq).
   Instaladas localmente so para regressao; nenhum codigo backend foi
   alterado.
2. A listagem depende da janela de snapshots (`page_size` 500) — a
   mesma limitacao aceita na 11.5.

---

## 15. Veredito

**Etapa 11.6: CONCLUIDA.**

Area real de ativos sobre `/api/v1`. Sem dados financeiros mockados.
Sem 11.7.
