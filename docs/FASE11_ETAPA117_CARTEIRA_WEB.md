# Fase 11 — Etapa 11.7: area de carteira web

Documento da implementacao real (codigo + testes). Substitui o
placeholder autenticado pela pagina `/carteira` do usuario logado.
Nao avanca para a 11.8. Data: 2026-09-10.

Base: Etapa 11.6 (ativos) e contrato 11.1/11.2 (composicao de GETs
existentes, sem BFF).

Regra:

```
Website (Next.js) -> reverse proxy /api -> Flask /api/v1 -> PostgreSQL
```

Nenhum acesso a banco, Sheets, Fundamentus, Yahoo, CVM, FNET ou
scrapers no frontend. Nenhuma regra financeira nova no cliente.

---

## 1. Objetivo

Criar a area operacional de carteira do Website Estrategia Fardada:

- `/carteira` — posicoes do usuario autenticado;
- resumo com valor investido (custo), numero de posicoes, quantidade
  de ativos e ultima atualizacao, quando a API fornecer;
- lista ticker / nome / quantidade / preco medio / valor investido /
  mercado e freshness, quando presentes;
- clique na posicao abre `/ativos/[ticker]` (tela da 11.6);
- loading, vazio, erro, 401, 403 e campos ausentes.

O backend continua autoridade de autenticacao, RBAC e isolamento.

---

## 2. Rota

| Rota | Componente | Acesso |
|---|---|---|
| `/carteira` | `CarteiraView` via `app/carteira/page.tsx` | autenticado (`ProtectedRoute` existente) |

Nao ha rota `/carteira/[id]`. O detalhe da posicao reutiliza
`/ativos/[ticker]`.

---

## 3. Endpoints utilizados (somente existentes)

Nenhum endpoint novo. Nenhum BFF. Composicao no cliente.

| Metodo | Caminho | Uso |
|---|---|---|
| GET | `/api/v1/carteira?page=&page_size=` | posicoes do usuario autenticado |
| GET | `/api/v1/mercado/snapshots` | preco de mercado na listagem, se a API devolver o ticker |
| GET | `/api/v1/mercado/freshness?ticker=` | FRESH/STALE/MISSING por ticker da carteira |

Nao usados de proposito:

- POST/PATCH/DELETE `/carteira` — CRUD fica para etapa futura;
- `GET /carteira/<id>` — a lista ja traz o contrato da posicao;
- `GET /indicadores/<id>/historico` — sem serie temporal nesta etapa;
- `GET /mercado/dados-financeiros` — contabil CVM nao entra na 11.7;
- rentabilidade, patrimonio, MtM, CAGR, drawdown, benchmark.

O frontend nunca envia `usuario_id`. O dono e sempre `g.usuario` na API
(Fase 6). 401/403 sao tratados no cliente; autorizacao nao e decidida
no Next.js.

---

## 4. Contrato real da posicao

`api/serializadores.py` (`serializar_posicao`):

- `id`, `ativo_id`, `ticker`, `tipo`
- `quantidade`, `preco_medio`, `valor_investido`
- `criado_em`, `atualizado_em`

Nao ha campo `nome` no contrato. A coluna Nome permanece `AUSENTE`.

`valor_investido` e derivado no backend (`quantidade * preco_medio`)
e e apresentado como **valor investido / custo**. Nao e patrimonio,
valor de mercado nem saldo atual. O frontend nao calcula
rentabilidade nem MtM.

---

## 5. Componentes

| Arquivo | Papel |
|---|---|
| `frontend/src/lib/carteira.ts` | composicao dos GETs da area |
| `frontend/src/components/CarteiraView.tsx` | pagina autenticada |
| `frontend/src/components/CarteiraResumo.tsx` | KPIs de custo/posicoes/ativos/atualizacao |
| `frontend/src/components/PosicaoRow.tsx` | linha da tabela (desktop) |
| `frontend/src/components/PosicaoCard.tsx` | card da posicao (mobile) |

Reuso sem duplicar AuthProvider, ProtectedRoute, cliente HTTP,
freshness ou semantica:

- `api.ts` (`getCarteira`, `getSnapshots`, `getFreshness`)
- `resource.ts` (401 propaga; 403 vira secao)
- `format.ts` (PRESENTE / ZERO / AUSENTE)
- `DataBadge` (FRESH / STALE / MISSING)
- `KpiCard`, `Table`, `EmptyState`, `ErrorState`, `Loading`

---

## 6. Autenticacao / RBAC

- Token somente em `X-Session-Token`. Nunca na URL.
- 401 propaga e encerra a sessao local (contrato 11.4).
- 403 de `GET /carteira` vira estado de acesso negado — sem carteira
  inventada. ADMIN sem `carteira.propria` nao ve posicoes de terceiros.
- 403 de snapshots / freshness aparece na secao correspondente; as
  posicoes da API continuam visiveis.
- Isolamento da Fase 6 preservado: a API filtra por `usuario.id`.

---

## 7. Freshness

Taxonomia existente, sem nova:

- `FRESH`
- `STALE`
- `MISSING`
- `AUSENTE` quando a API nao devolve categoria

Reuso de `freshnessSummary` (`frontend/src/lib/ativos.ts`) e
`DataBadge`. MISSING nao e mascarado como FRESH.

---

## 8. Semantica de `valor_investido`

- Fonte: campo da API, nao recálculo no cliente para a linha.
- KPI de resumo soma somente valores `number` presentes
  (`sumPresent`); posicoes com `null` entram como `AUSENTE` e nao
  viram `0`.
- Rotulo da UI: "Valor investido".
- Proibido nesta etapa: patrimonio, valor de mercado, saldo atual,
  lucro/prejuizo, rentabilidade.

---

## 9. Estados tratados

| Estado | Comportamento |
|---|---|
| loading | skeleton + "Carregando carteira" |
| vazia | empty state; nenhum ticker inventado |
| erro | HTTP 5xx / falha de comunicacao |
| 401 | "Nao autenticado (401)" |
| 403 | "Acesso negado (403)" na secao da carteira |
| campo ausente | `AUSENTE`, nunca `0` |
| ZERO real | `0` somente se a API devolver `0` |

---

## 10. Testes

Frontend (Vitest):

- carteira com dados reais da API;
- carteira vazia;
- loading;
- erro;
- 401;
- 403;
- campos ausentes nao viram zero;
- `valor_investido` como custo (nao patrimonio);
- navegacao para `/ativos/[ticker]`;
- isolamento de `X-Session-Token`;
- rota `/carteira` protegida (`guards.test.ts`).

Regressoes relevantes: cliente HTTP (`api.test.ts`), autenticacao
(`auth.test.ts`, `auth-flow.test.tsx`), dashboard e ativos.

Backend (regressao, sem alteracao de API):

- `tests/test_carteira.py`
- `tests/test_auth_web.py`

---

## 11b. Verificacao

| Checagem | Resultado |
|---|---|
| Vitest | 74 testes aprovados (13 arquivos) |
| lint (`next lint`) | passou, sem warnings |
| tsc (`npx tsc --noEmit`) | passou |
| pytest (`test_carteira.py` + `test_auth_web.py`) | 68 testes aprovados |

---

## 11. Limitacoes reais (nao inventadas)

1. **Sem campo `nome`.** Cadastro do ativo na carteira so traz
   ticker/tipo. Nome = `AUSENTE`.
2. **Sem patrimonio / MtM oficial.** Preco de mercado, quando
   existir no snapshot, e exibido aparte. Nao ha lucro/prejuizo.
3. **Snapshots globais.** Cruzamento por ticker na pagina 1
   (`page_size` 500). Fora da janela, mercado fica `AUSENTE`.
4. **Freshness N+1** limitado a 12 tickers (mesmo teto do dashboard).
5. **Sem CRUD.** Inclusao/edicao/remocao de posicao nao entra na 11.7.
6. **Sem serie temporal, CAGR, drawdown, benchmark ou graficos.**
7. **Janela de listagem** `page_size` 500. Posicoes alem disso nao
   aparecem nesta etapa.

Futuro (nao nesta etapa): CRUD da carteira, patrimonio oficial,
rentabilidade historica, nome cadastral do ativo, paginacao completa.

---

## 12. Decisao sobre TELEGRAM_CHAT_ID

Auditoria pontual de `.github/workflows/main.yml`.

Caminho real ainda dependente:

- job `build` executa `python app.py`;
- `app.py` chama `modules.utils.disparar_alertas`;
- `disparar_alertas` le `config.TELEGRAM_CHAT_ID` (env
  `TELEGRAM_CHAT_ID`).

A Fase 10 removeu o fan-out de alertas individuais para esse chat,
mas o job agendado do robo (distorcoes Sheets) ainda usa o destino
legado. A variavel **nao** ficou obsoleta nesse workflow.

Correcao pontual (sem ID real no YAML):

```
TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
```

junto dos demais secrets do job `build`. Nenhum valor concreto foi
escrito em codigo, YAML ou logs. O workflow nao foi refatorado.

---

## 13. Arquivos

### Criados

| Arquivo | Papel |
|---|---|
| `frontend/src/lib/carteira.ts` | composicao GET /carteira + mercado |
| `frontend/src/lib/carteira.test.ts` | contagem e datas do resumo |
| `frontend/src/components/CarteiraView.tsx` | pagina autenticada |
| `frontend/src/components/CarteiraResumo.tsx` | KPIs |
| `frontend/src/components/PosicaoRow.tsx` | linha da tabela |
| `frontend/src/components/PosicaoCard.tsx` | card mobile |
| `frontend/src/components/carteira.test.tsx` | estados, RBAC, navegacao |
| `frontend/src/app/carteira/page.tsx` | rota `/carteira` |
| `docs/FASE11_ETAPA117_CARTEIRA_WEB.md` | este documento |

### Alterados

| Arquivo | Papel |
|---|---|
| `frontend/src/lib/tokens.ts` | item Carteira no menu |
| `frontend/src/lib/guards.test.ts` | `/carteira` nao e publica |
| `.github/workflows/main.yml` | `TELEGRAM_CHAT_ID` via secret |

`types.ts` ja refletia o contrato de `PosicaoCarteira`; sem
alteracao. Backend nao foi alterado. README nao foi atualizado.

---

## 14. O que esta etapa nao fez

- rentabilidade historica / lucro/prejuizo;
- graficos patrimoniais, CAGR, drawdown, benchmark;
- CRUD de posicoes;
- nova tabela, migration, modelo, BFF ou endpoint;
- mock financeiro;
- Etapa 11.8.

---

## 15. Veredito

**Etapa 11.7: CONCLUIDA.**

Area real de carteira sobre `/api/v1`. Sem dados financeiros
mockados. Sem 11.8.
