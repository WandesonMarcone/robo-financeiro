# Fase 11 — Etapa 11.8: area de alertas web

Documento da implementacao real (codigo + testes). Substitui o
placeholder autenticado pela pagina `/alertas` do usuario logado.
Nao avanca para a 11.9. Data: 2026-09-23.

Base: Etapa 11.7 (carteira) e contrato 11.1/11.2 (composicao de GETs
existentes, sem BFF).

Regra:

```
Website (Next.js) -> reverse proxy /api -> Flask /api/v1 -> PostgreSQL
```

Nenhum acesso a banco, Sheets, Fundamentus, Yahoo, CVM, FNET, Telegram
ou scrapers no frontend. Nenhuma regra financeira nova no cliente.
Backend, motor de alertas, Fase 8 e Fase 10 permanecem intactos nesta
etapa.

---

## 1. Objetivo

Criar a area operacional de alertas do Website Estrategia Fardada:

- `/alertas` — inbox pessoal + eventos de mercado do usuario autenticado;
- inbox via `GET /notificacoes` (dono = `g.usuario`);
- contagem de nao lidas via `GET /notificacoes?nao_lidas=true`;
- eventos de mercado via `GET /alertas` (escopo da sessao, sem filtro
  de ticker inventado no cliente);
- canais informados via `GET /preferencias`;
- marcar lida via `POST /notificacoes/{id}/lida` e
  `POST /notificacoes/ler-todas`;
- loading, vazio, erro, 401, 403 e campos ausentes.

O backend continua autoridade de autenticacao, RBAC e isolamento.

---

## 2. Rota

| Rota | Componente | Acesso |
|---|---|---|
| `/alertas` | `AlertasView` via `app/alertas/page.tsx` | autenticado (`ProtectedRoute` existente) |

Nao ha rota `/alertas/[id]`. Nao ha detalhe de alerta nesta etapa.

---

## 3. Endpoints utilizados (somente existentes)

Nenhum endpoint novo. Nenhum BFF. Composicao no cliente.

| Metodo | Caminho | Uso |
|---|---|---|
| GET | `/api/v1/notificacoes?page=&page_size=` | inbox pessoal |
| GET | `/api/v1/notificacoes?nao_lidas=true&page_size=1` | total de nao lidas (`meta.total`) |
| GET | `/api/v1/alertas?page=&page_size=` | eventos de mercado (QUALIDADE/MERCADO/CRITICO) |
| GET | `/api/v1/preferencias` | canais web/telegram/mestre/frequencia |
| POST | `/api/v1/notificacoes/{id}/lida` | marcar uma notificacao como lida |
| POST | `/api/v1/notificacoes/ler-todas` | marcar todas as nao lidas do usuario |

Nao usados de proposito:

- POST/PATCH de regras de alerta;
- geracao de notificacoes no cliente;
- Telegram, CVM, Sheets, Yahoo, Fundamentus;
- filtro client-side de ticker em `/alertas`.

O frontend nunca envia `usuario_id`. O dono e sempre `g.usuario` na API
(Fase 6). 401/403 sao tratados no cliente; autorizacao nao e decidida
no Next.js.

---

## 4. Contratos reais

### Inbox (`serializar_notificacao`)

- `id`, `tipo`, `titulo`, `mensagem`
- `ativo_id`, `ticker`, `canal`, `status`
- `dados` (opcional: `prioridade`, `indicador`, `freshness`)
- `criado_em`, `lida_em`, `tentativas`, `enviada_em`

Nao lida = `lida_em` null. Prioridade/freshness/indicador so aparecem
se vierem em `dados`. Ausente = `AUSENTE`, nunca recalculado.

### Mercado (`serializar_alerta`)

- `tipo_alerta`, `ticker`, `indicador`, `severidade`
- `origem`, `data_evento`, `motivo`, `regra`
- `tipo_ativo`, `valor_anterior`, `valor_atual`, `variacao_percentual`

Nao ha `lida` nem `freshness` no evento de mercado. Critico =
`tipo_alerta` CRITICO ou `severidade` CRITICO/ERRO, somente com campos
da API.

---

## 5. Componentes

| Arquivo | Papel |
|---|---|
| `frontend/src/lib/alertas.ts` | composicao dos GETs da area |
| `frontend/src/components/AlertasView.tsx` | pagina autenticada |
| `frontend/src/app/alertas/page.tsx` | rota `/alertas` |

Reuso sem duplicar AuthProvider, ProtectedRoute, cliente HTTP ou
semantica:

- `api.ts` (`getNotificacoes`, `getAlertas`, `getPreferencias`,
  `marcarNotificacaoLida`, `marcarTodasNotificacoesLidas`)
- `resource.ts` (401 propaga; 403 vira secao)
- `format.ts` (PRESENTE / AUSENTE)
- `AlertBadge`, `DataBadge`, `KpiCard`, `EmptyState`, `ErrorState`, `Loading`

---

## 6. Autenticacao / RBAC

- Token somente em `X-Session-Token`. Nunca na URL.
- 401 propaga e encerra a sessao local (contrato 11.4).
- 403 de inbox/mercado/preferencias vira estado de acesso negado na
  secao correspondente — sem alerta inventado.
- Isolamento da Fase 6 preservado: a API filtra inbox por `usuario.id`.
  Eventos de `/alertas` seguem a permissao `alertas.consultar` da sessao.

---

## 7. Estados tratados

| Estado | Comportamento |
|---|---|
| loading | skeleton + "Carregando alertas" |
| vazia | empty state; nenhum ticker inventado |
| erro | HTTP 5xx / falha de comunicacao |
| 401 | "Nao autenticado (401)" |
| 403 | "Acesso negado (403)" na secao |
| campo ausente | `AUSENTE`, nunca inventado |
| lida / nao lida | `lida_em` da API; POST existente, sem persistencia local |

Tons visuais: critico / informativo / lido / nao lido / AUSENTE com
Badge/AlertBadge/DataBadge existentes.

---

## 8. Testes

Frontend (Vitest):

- loading;
- lista vazia nao inventa alerta;
- renderiza campos da API (ticker, tipo, prioridade, freshness, origem);
- diferencia critico e informativo;
- dados ausentes sem inventar ticker;
- erro da API;
- 401;
- isolamento de `X-Session-Token`;
- marcar como lida no endpoint existente.

Regressoes: cliente HTTP (`api.test.ts`), autenticacao, dashboard,
ativos e carteira.

Backend (regressao, sem alteracao de API nesta etapa):

- `tests/test_api.py`
- `tests/test_notificacoes.py`
- `tests/test_auth_web.py`
- `tests/test_sessoes.py`
- `tests/test_autorizacao.py`
- `tests/test_preferencias.py`
- `tests/test_motor_alertas.py`

---

## 9. Verificacao

| Checagem | Resultado |
|---|---|
| Vitest 11.8 (`alertas.test.tsx`, `alertas.test.ts`, `api.test.ts`) | 20 testes aprovados |
| Vitest completo | 87 testes aprovados (15 arquivos) |
| lint (`next lint`) | passou, sem warnings |
| tsc (`npx tsc --noEmit`) | passou |
| pytest auth/notificacoes/alertas | 268 testes aprovados |

---

## 10. Limitacoes reais (nao inventadas)

1. **`GET /alertas` nao e inbox pessoal.** E evento de mercado com
   permissao de sessao. O inbox e `/notificacoes`.
2. **Evento de mercado nao tem `lida`/`freshness`.** Esses campos so
   existem em notificacao (`lida_em`, `dados.freshness`).
3. **Janela `page_size` 100.** Itens alem disso nao aparecem nesta etapa.
4. **Sem filtro de ticker no cliente.** Isolamento e o token da sessao.
5. **Sem persistencia local.** Marcar lida so via POST existente.
6. **Preferencias somente leitura.** Nao ha UI de gravacao nesta etapa.

Futuro (nao nesta etapa): Fase 11.9+, filtros avancados, detalhe de
alerta, IA, graficos, assinatura.

---

## 11. Arquivos

### Criados

| Arquivo | Papel |
|---|---|
| `frontend/src/lib/alertas.ts` | composicao GET inbox + mercado |
| `frontend/src/lib/alertas.test.ts` | prioridade/freshness/critico |
| `frontend/src/components/AlertasView.tsx` | pagina autenticada |
| `frontend/src/components/alertas.test.tsx` | estados, RBAC, mark-read |
| `docs/FASE11_ETAPA118_ALERTAS_WEB.md` | este documento |

### Alterados (11.8)

| Arquivo | Papel |
|---|---|
| `frontend/src/app/alertas/page.tsx` | rota `/alertas` deixa de ser placeholder |
| `frontend/src/lib/api.ts` | `marcarNotificacaoLida`, `marcarTodasNotificacoesLidas` |
| `frontend/src/lib/api.test.ts` | POST `/notificacoes/{id}/lida` |

Backend nao foi alterado nesta etapa. F.3 (serializadores, scraper,
pipeline, mercado) permanece fora do escopo 11.8.

---

## 12. O que esta etapa nao fez

- backend, DB, regras de alerta, Telegram, CVM, Sheets, indicadores;
- Fase 8, Fase 10, Dashboard, Ativos, Carteira;
- F.4, Fase 11.9+, Fase 12;
- endpoint, tabela ou fonte novos;
- IA, graficos, assinatura;
- mock de alerta ou persistencia local.

---

## 13. Veredito

**Etapa 11.8: CONCLUIDA.**

Area real de alertas sobre `/api/v1`. Sem dados inventados. Sem 11.9.
