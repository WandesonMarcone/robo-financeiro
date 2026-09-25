# Fase 11 — Etapa 11.9: area de documentos web

Documento da implementacao real (codigo + testes). Substitui o
placeholder autenticado pela pagina `/documentos` do usuario logado.
Nao avanca para a 11.10. Data: 2026-09-25.

Base: Etapa 11.8 (alertas) e contrato 11.1/11.2 (composicao de GETs
existentes, sem BFF).

Regra:

```
Website (Next.js) -> reverse proxy /api -> Flask /api/v1 -> PostgreSQL
```

Nenhum acesso a banco, Sheets, Fundamentus, Yahoo, CVM, FNET, Google
Drive, Telegram ou scrapers no frontend. Nenhuma regra financeira nova
no cliente. Backend, Content Engine, Fase 8 e Fase 10 permanecem
intactos nesta etapa.

---

## 1. Objetivo

Criar a area operacional de documentos do Website Estrategia Fardada:

- `/documentos` — metadados de documentos via `GET /documentos`;
- ativo relacionado (`ticker` / `ativo_id`) quando a API fornecer;
- tipo (`tipo_documento`), data (`data_publicacao`), origem (`id_b3`)
  e status (`status_processamento`) quando presentes;
- abrir `url_pdf` somente se a API devolver URL http/https valida;
- filtros ja suportados: `ticker`, `tipo_documento`, `status`.

O backend continua autoridade de autenticacao, RBAC e isolamento.

---

## 2. Rota

| Rota | Componente | Acesso |
|---|---|---|
| `/documentos` | `DocumentosView` via `app/documentos/page.tsx` | autenticado (`ProtectedRoute` existente) |

Nao ha rota `/documentos/[id]`. Nao ha `GET /documentos/<id>`.

---

## 3. Endpoints utilizados (somente existentes)

Nenhum endpoint novo. Nenhum BFF. Composicao no cliente.

| Metodo | Caminho | Uso |
|---|---|---|
| GET | `/api/v1/documentos?ticker=&tipo_documento=&status=&page=&page_size=` | lista de metadados |

Filtros reais da API (`api/routes/documentos.py`):

- `ticker` — igualdade exata apos `strip().upper()` no ativo relacionado;
- `tipo_documento` — igualdade exata do texto;
- `status` — igualdade de `status_processamento` apos `strip().upper()`;
- `ativo_id` — inteiro (nao exposto na UI desta etapa; ticker cobre o caso);
- `page`, `page_size` — paginacao existente.

Nao usados de proposito:

- upload / classificacao / IA;
- texto extraido, resumo IA, log de erro, hash;
- Drive/CVM/FNET/B3 direto no frontend;
- `GET /documentos/<id>`.

Token somente em `X-Session-Token`. Nunca na URL.

---

## 4. Contrato real (`serializar_documento`)

- `id`, `ativo_id`, `ticker`
- `data_publicacao`, `tipo_documento`, `url_pdf`
- `assunto`, `id_b3`, `status_processamento`, `data_atualizacao`

Nunca inclui `texto_extraido`, `resumo_ia`, `log_erro` nem `hash_sha256`.
Campo ausente = `AUSENTE`. URL so e link se `url_pdf` for http/https
valida; caminhos relativos e esquemas nao HTTP nao sao inventados.

Origem na UI: `id_b3` quando presente (nao ha campo `fonte` no contrato).

---

## 5. Componentes

| Arquivo | Papel |
|---|---|
| `frontend/src/lib/documentos.ts` | filtros + `loadDocumentos` |
| `frontend/src/components/DocumentosView.tsx` | pagina autenticada |
| `frontend/src/app/documentos/page.tsx` | rota `/documentos` |

Reuso:

- `api.ts` (`getDocumentos`)
- `resource.ts` (401 propaga; 403 vira secao)
- `format.ts`, `DataBadge`, `Badge`, `KpiCard`, `Table`, `EmptyState`,
  `ErrorState`, `Loading`, `Input`, `Button`
- AppShell / ProtectedRoute existentes

---

## 6. Autenticacao / RBAC

- Token somente em `X-Session-Token`.
- 401 propaga e encerra a sessao local (contrato 11.4).
- 403 vira estado de acesso negado — sem documento inventado.
- Permissao da API: `documentos.consultar`.

---

## 7. Estados tratados

| Estado | Comportamento |
|---|---|
| loading | skeleton + "Carregando documentos" |
| vazia | empty state; nenhum ticker inventado |
| erro | HTTP 5xx / falha de comunicacao |
| 401 | "Nao autenticado (401)" |
| 403 | "Acesso negado (403)" |
| campo ausente | `AUSENTE` |
| com ativo | ticker da API |
| sem ativo | ticker `AUSENTE` |
| com `url_pdf` valida | link "Abrir PDF" (`target=_blank`) |
| sem URL | `AUSENTE`, so metadados |

---

## 8. Testes

Frontend (Vitest):

- documentos carregados;
- lista vazia;
- loading;
- erro da API;
- sessao expirada (401);
- documento com ativo;
- documento sem ativo;
- campos opcionais ausentes;
- `url_pdf` quando disponivel;
- autenticacao / isolamento de token;
- filtros existentes enviados aa API;
- `/documentos` nao e rota publica (`guards.test.ts`).

Regressoes: cliente HTTP, autenticacao, dashboard, ativos, carteira,
alertas.

Backend (regressao, sem alteracao de API nesta etapa):

- `tests/test_api.py` (inclui `GET /documentos`)
- `tests/test_auth_web.py`
- `tests/test_sessoes.py`
- `tests/test_autorizacao.py`

---

## 9. Verificacao

| Checagem | Resultado |
|---|---|
| Vitest 11.9 (`documentos.test.tsx`, `documentos.test.ts`, `api.test.ts`, `guards.test.ts`) | 27 testes aprovados |
| Vitest completo | 103 testes aprovados (17 arquivos) |
| lint (`next lint`) | passou, sem warnings |
| tsc (`npx tsc --noEmit`) | passou |
| pytest auth/API/documentos | 130 testes aprovados |

PyPDF2 DeprecationWarning da dependencia do ambiente — nao e falha
desta etapa.

---

## 10. Limitacoes reais (nao inventadas)

1. **Sem `GET /documentos/<id>`.** Somente lista filtrada.
2. **Sem campo `fonte`/`origem` dedicado.** Origem exibida = `id_b3`
   quando a API devolver.
3. **Sem download interno.** O website so abre `url_pdf` da API.
4. **`ativo_id` nao e filtro da UI.** A API aceita; a tela usa `ticker`.
5. **Janela `page_size` 20.** Itens alem da paginacao exigem Proxima.
6. **Catalogo de tipos nao existe na API.** O filtro `tipo_documento`
   e texto livre enviado como igualdade exata.
7. **Sem upload, classificacao ou IA.**

---

## 11. Arquivos

### Criados

| Arquivo | Papel |
|---|---|
| `frontend/src/lib/documentos.ts` | composicao GET /documentos |
| `frontend/src/lib/documentos.test.ts` | ticker/status/url_pdf |
| `frontend/src/components/DocumentosView.tsx` | pagina autenticada |
| `frontend/src/components/documentos.test.tsx` | estados, RBAC, filtros |
| `docs/FASE11_ETAPA119_DOCUMENTOS_WEB.md` | este documento |

### Alterados (11.9)

| Arquivo | Papel |
|---|---|
| `frontend/src/app/documentos/page.tsx` | rota deixa de ser placeholder |
| `frontend/src/lib/api.ts` | `getDocumentos` |
| `frontend/src/lib/api.test.ts` | query de documentos sem token |
| `frontend/src/lib/types.ts` | tipo `Documento` |
| `frontend/src/lib/guards.test.ts` | `/documentos` autenticada |

Backend nao foi alterado nesta etapa.

---

## 12. O que esta etapa nao fez

- backend, DB, CVM, Sheets, indicadores, Telegram;
- Fase 8, Fase 10, Dashboard, Ativos, Carteira, Alertas;
- Content Engine;
- F.4, Fase 11.10+, Fase 12;
- endpoint, tabela ou fonte novos;
- upload, classificacao, IA;
- mock de documento.

---

## 13. Veredito

**Etapa 11.9: CONCLUIDA.**

Area real de documentos sobre `/api/v1`. Sem dados inventados. Sem 11.10.
