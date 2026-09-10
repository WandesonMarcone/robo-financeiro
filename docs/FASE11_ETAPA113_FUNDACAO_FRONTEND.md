# Fase 11 — Etapa 11.3: fundacao do frontend

Documento da implementacao real (codigo + testes). Cria a base Next.js
do Website. Nao implementa Dashboard funcional, graficos, carteira
operacional nem avanca para a 11.4. Data: 2026-09-10.

Base: Etapa 11.1 (auditoria) e 11.2 (CORS / contrato de consumo).
50 endpoints. Token somente em header. PostgreSQL via Flask `/api/v1`.

---

## 1. Objetivo

Fundar o Website institucional **Estrategia Fardada** em Next.js +
TypeScript + Tailwind, com design system, layout e cliente HTTP que
consome **somente** `/api/v1`. Sem segundo backend. Sem Sheets. Sem
regras financeiras no cliente.

Regra:

```
Website (Next.js) -> reverse proxy /api -> Flask /api/v1 -> PostgreSQL
```

---

## 2. Stack

| Item | Escolha |
|---|---|
| App | Next.js 15 (App Router) em `frontend/` |
| Linguagem | TypeScript strict |
| Estilo | Tailwind CSS 3 + tokens da identidade |
| Testes | Vitest + Testing Library |
| Proxy | `next.config.ts` rewrite `/api/:path*` -> Flask |
| Hospedagem preview | porta 3000 (frontend); Flask 10000 |

Nao havia frontend previo (`package.json` ausente). Nada foi sobrescrito.

---

## 3. Identidade visual

Tokens em `frontend/src/lib/tokens.ts` e `tailwind.config.ts`:

| Token | Valor |
|---|---|
| Fundo | `#F4F1EA` (`sand`) |
| Militar | `#1B2E1C` (`olive`) |
| Dourado | `#C5A059` (`gold`) |
| Branco card | `#FFFFFF` |
| Texto | `#1A1A1A` (`ink`) |

Tipografia:

- titulos: Allerta Stencil (`--font-display`)
- tickers: Montserrat ExtraBold (`--font-ticker`, classe `.ticker`)
- corpo: Inter (`--font-sans`)

Black Ops One e Saira Stencil One permanecem na paleta institucional
para pecas futuras; Allerta Stencil cobre titulos desta fundacao.

Estetica: tatico-corporativo, cards brancos no bege, acento dourado,
sidebar + header, layout responsivo.

Logo: **nao inventada**. `LogoSlot` reserva um quadrado vazio + nome
textual. Quando o asset oficial existir, substitui o slot.

---

## 4. Layout e navegacao

`AppShell` = `Header` + `Sidebar` + `main`.

Itens do menu (placeholders 11.3, telas na 11.4):

- Dashboard
- Ativos
- Indicadores
- Documentos
- Alertas
- Preferencias

Paginas em `frontend/src/app/*/page.tsx` descrevem o contrato HTTP e
exibem empty state. Sem fetch de dados reais. Sem graficos.

Componentes reutilizaveis: `Button`, `Card`, `Badge`, `AlertBadge`,
`Input`, `Table`, `Loading`, `EmptyState`, `ErrorState`.

---

## 5. Cliente API

`frontend/src/lib/api.ts`:

- base `NEXT_PUBLIC_API_BASE_URL` (padrao `/api/v1`)
- envelope `{status, data, meta}`
- credencial **somente** `X-Session-Token` (header)
- recusa query `token`, `api-key`, `x-session-token`
- token em `sessionStorage` (`frontend/src/lib/session.ts`), nunca na URL

Reverse proxy same-origin: o browser fala com o Next; o Next reescreve
`/api/*` para `API_PROXY_TARGET` (padrao `http://localhost:10000`).
CORS do Flask continua valido para origem distinta; no preview
same-origin o CORS nao e exigido.

O frontend **nao** importa `DATABASE_URL`, Sheets, scrapers, CVM/FNET
nem `services/`.

---

## 6. Seguranca desta etapa

- nenhum secret no frontend
- nenhum endpoint novo
- nenhum acesso a banco
- token nunca na URL (teste dedicado)
- `API_ENABLED` e CORS permanecem no backend (11.2)

---

## 7. Como subir

```bash
# Dependencias do Website
cd frontend
npm install
```

```bash
# Desenvolvimento: Next na 3000, proxy para Flask na 10000
npm run dev
```

Backend (outro processo, ambiente de API ligada):

```
API_ENABLED=true
API_CORS_ORIGINS=http://localhost:3000
PORT=10000
```

Script opcional na raiz: `start.sh` (Flask em background + Next no
preview). Preview expoe a porta do frontend.

Testes do Website:

```bash
cd frontend
npm test
```

---

## 8. O que esta etapa nao fez

- Dashboard / Ativos / Indicadores / Documentos / Alertas funcionais
- graficos ou serie temporal
- CRUD de carteira na UI
- login/logout completo (cliente HTTP pronto; tela na 11.4)
- cookie HttpOnly, Bearer, refresh
- endpoints novos
- Etapa 11.4

---

## 9. Arquivos

| Arquivo | Papel |
|---|---|
| `frontend/` | app Next.js |
| `frontend/src/lib/api.ts` | cliente `/api/v1` |
| `frontend/src/lib/session.ts` | token em header / storage |
| `frontend/src/lib/tokens.ts` | cores e nav |
| `frontend/src/components/*` | design system + shell |
| `frontend/src/app/*` | placeholders |
| `frontend/next.config.ts` | proxy `/api` + allowedHosts |
| `package.json` (raiz) | scripts delegam a `frontend/` |
| `start.sh` | sobe Flask + Next |
| `docs/FASE11_ETAPA113_FUNDACAO_FRONTEND.md` | este documento |

`.gitignore`: `*.json` ignorava `package.json`; excecoes
`!package.json`, `!package-lock.json`, `!frontend/**/*.json`.
`node_modules/`, `frontend/.next/`, `frontend/coverage/` ignorados.

---

## 10. Testes

Vitest no frontend (cliente URL, token, LogoSlot). Backend 11.1/11.2
inalterado nesta etapa.

---

## 11. Veredito

**Etapa 11.3: CONCLUIDA.**

Fundacao do Website pronta para a 11.4 consumir os 50 endpoints.
Sem Dashboard funcional. Sem 11.4.
