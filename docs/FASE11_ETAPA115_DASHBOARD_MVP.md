# Fase 11 — Etapa 11.5: primeiro dashboard real

Documento da implementacao real (codigo + testes). Substitui o
placeholder autenticado pela primeira tela operacional do Website
Estrategia Fardada. Nao avanca para a 11.6. Data: 2026-09-10.

Base: Etapa 11.4 (autenticacao web) e contrato 11.1/11.2 (composicao
de GETs existentes, sem BFF `/dashboard`).

Regra:

```
Website (Next.js) -> reverse proxy /api -> Flask /api/v1 -> PostgreSQL
```

Nenhum acesso a banco, Sheets, Fundamentus, Yahoo, CVM, FNET ou
scrapers no frontend. Nenhuma regra financeira nova no cliente.

---

## 1. Objetivo

Transformar o placeholder de `/dashboard` na primeira tela real do
produto:

- cabecalho institucional (AppShell + identidade da pagina);
- visao geral com contagens e capital persistido;
- cards dos ativos da carteira e do acompanhamento;
- inbox de notificacoes do usuario;
- alertas cruzados com os tickers do usuario;
- estados PRESENTE / ZERO / AUSENTE / NAO_APLICAVEL / INVALIDO;
- freshness FRESH / STALE / MISSING quando a API fornecer;
- loading, vazio, erro, 401 e 403.

O backend continua autoridade de autenticacao, RBAC e isolamento.

---

## 2. Endpoints utilizados (somente existentes)

Nenhum endpoint novo. Nenhum BFF. Composicao no cliente:

| Metodo | Caminho | Uso no dashboard |
|---|---|---|
| GET | `/api/v1/me` | sessao (11.4); usuario no header |
| GET | `/api/v1/me/plano` | plano efetivo e limites |
| GET | `/api/v1/carteira` | posicoes, quantidade, preco_medio, valor_investido |
| GET | `/api/v1/ativos-acompanhados` | watchlist do usuario |
| GET | `/api/v1/notificacoes` | inbox |
| GET | `/api/v1/notificacoes?nao_lidas=true` | KPI de nao lidas (`meta.total`) |
| GET | `/api/v1/preferencias` | flags do usuario (web/telegram/mercado) |
| GET | `/api/v1/alertas` | eventos globais, filtrados no cliente pelos tickers do usuario |
| GET | `/api/v1/mercado/snapshots` | cotacao e indicadores de mercado, cruzados por ticker |
| GET | `/api/v1/indicadores` | estado atual por ativo (nao e serie temporal) |
| GET | `/api/v1/mercado/freshness?ticker=` | FRESH/STALE/MISSING por ticker do usuario |

Nao usados de proposito:

- `GET /relatorios` — COUNTs da plataforma, nao do usuario;
- `GET /indicadores/<id>/historico` — `meta.serie_temporal = false`;
- `GET /mercado/snapshots/mais-recente` — N+1; a listagem paginada cobre o cruzamento.

---

## 3. Composicao e isolamento

`frontend/src/lib/dashboard.ts` agrega as respostas.

1. Carrega recursos pessoais em paralelo.
2. 401 propaga e encerra a sessao local (contrato 11.4).
3. 403 de recurso pessoal vira estado `forbidden` na secao — a sessao
   permanece. ADMIN sem `carteira.propria` / `ativos.proprios` /
   `notificacoes.consultar` ve 403, nao dados de terceiros.
4. Tickers do usuario = uniao de carteira + acompanhados.
5. Snapshots e indicadores so sao pedidos quando ha ticker do usuario.
6. `GET /alertas` e global; o dashboard so exibe eventos cujo ticker
   coincide com o conjunto do usuario. Sem ticker, nao atribui alerta.
7. Freshness e pedido por ticker, com teto de 12 chamadas no MVP.

Token somente em `X-Session-Token`. Nunca na URL.

---

## 4. Semantica de dados

`frontend/src/lib/format.ts` exibe o que a API devolve:

- `null` / ausencia -> `AUSENTE` (nunca `0`);
- `0` real -> `ZERO`;
- `campos.*.semantica` da API tem precedencia;
- `aplicavel=false` -> `NAO_APLICAVEL`;
- soma de `valor_investido` ignora ausentes e rotula quantos foram
  somados; se nenhum valor presente, o total e `AUSENTE`.

Nao ha grafico. A API nao oferece serie temporal completa.

---

## 5. Interface

Identidade da 11.3 preservada (sand / olive / gold, Allerta Stencil,
Montserrat ExtraBold, Inter). Header e sidebar da area autenticada
permanecem. A pagina do dashboard acrescenta:

- KPIs: acompanhados, carteira, nao lidas, valor investido;
- freshness por ticker do usuario;
- plano efetivo (`GET /me/plano`);
- cards de ativo (ticker, tipo, preco, indicadores, estado, data);
- inbox e alertas cruzados.

Responsivo: KPIs em 1/2/4 colunas; cards em 1/2 colunas.

---

## 6. O que esta etapa nao fez

- pagamentos, assinatura, Premium comercial na UI;
- conteudo Instagram, LLM, chatbot, Telegram;
- novo sistema de autenticacao;
- tabela, migration, endpoint novo;
- leitura de Sheets ou fontes financeiras externas;
- serie historica inventada;
- IA para analise;
- Etapa 11.6 (telas de Ativos/Indicadores/Documentos/Alertas operacionais).

---

## 7. Limitacoes reais (nao inventadas)

1. **Sem BFF /dashboard.** Varios GETs por carga. Aceito pela 11.1.
2. **Snapshots globais.** Cruzamento por ticker na pagina 1 (`page_size`
   500). Se o ticker do usuario nao estiver nessa janela, preco/DY
   ficam `AUSENTE`.
3. **Freshness N+1 limitado a 12 tickers.** Excedentes ficam sem
   freshness nesta etapa.
4. **`GET /alertas` nao e inbox.** Sem ticker pessoal, o dashboard nao
   mostra eventos globais como se fossem do usuario.
5. **ADMIN sem carteira pessoal.** 403 nas secoes pessoais. Intencional
   na matriz RBAC (11.1 item 10).
6. **Sem MtM oficial.** `valor_investido` e `quantidade * preco_medio`
   persistido. Preco de mercado e rotulo de snapshot, nao valorizacao
   calculada no frontend.
7. **Sem serie temporal.** Indicadores sao estado atual.
8. **Preferencias** sao lidas, nao editadas nesta etapa.

---

## 8. Arquivos

### Criados

| Arquivo | Papel |
|---|---|
| `frontend/src/lib/dashboard.ts` | composicao dos GETs |
| `frontend/src/lib/format.ts` | semantica de exibicao |
| `frontend/src/components/DashboardView.tsx` | tela autenticada |
| `frontend/src/components/AssetCard.tsx` | card de ativo |
| `frontend/src/components/AlertsPanel.tsx` | inbox + alertas cruzados |
| `frontend/src/components/KpiCard.tsx` | KPI |
| `frontend/src/components/DataBadge.tsx` | badge de estado |
| `frontend/src/components/SectionState.tsx` | loading de pagina |
| `frontend/src/lib/dashboard.test.ts` | composicao |
| `frontend/src/lib/format.test.ts` | ausencia vs zero |
| `frontend/src/components/dashboard.test.tsx` | tela autenticada |
| `docs/FASE11_ETAPA115_DASHBOARD_MVP.md` | este documento |

### Alterados

| Arquivo | Papel |
|---|---|
| `frontend/src/app/dashboard/page.tsx` | placeholder -> tela real |
| `frontend/src/lib/api.ts` | GETs de leitura existentes |
| `frontend/src/lib/types.ts` | contratos de payload |
| `frontend/src/components/AlertBadge.tsx` | severidades da API |

Header, AppShell, login, guards e sessao da 11.4 permanecem.

---

## 9. Testes

Frontend (Vitest):

- dashboard autenticado;
- carregamento (loading);
- usuario sem ativos;
- usuario com ativos (API real mockada no contrato);
- erro da API;
- 401;
- 403 (ADMIN / recursos pessoais);
- isolamento de `X-Session-Token`;
- ausencia de indicadores nao vira zero.

Backend (regressao, sem alteracao de API):

- `tests/test_auth_web.py`
- `tests/test_fase112_cors_deploy.py`
- `tests/test_carteira.py`
- `tests/test_ativos_acompanhados.py`
- `tests/test_notificacoes.py`

---

## 10. Veredito

**Etapa 11.5: CONCLUIDA.**

Primeira tela real do Website sobre `/api/v1`. Sem dados financeiros
mockados. Sem 11.6.
