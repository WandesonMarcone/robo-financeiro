# Fase 11 — Etapa 11.4: autenticacao e area protegida

Documento da implementacao real (codigo + testes). Conecta o Website
Next.js a autenticacao ja existente em `/api/v1`. Nao avanca para a
11.5. Data: 2026-09-10.

Base: Etapa 11.3 (fundacao do frontend) e contrato 11.2 (CORS / token
somente em header).

Regra:

```
Website (Next.js) -> reverse proxy /api -> Flask /api/v1 -> PostgreSQL
```

Nenhum acesso a banco, Sheets ou fontes financeiras no frontend.

---

## 1. Objetivo

Criar uma area autenticada funcional:

- tela de login;
- sessao via `X-Session-Token`;
- verificacao em `GET /me`;
- logout;
- protecao de rotas;
- header com usuario autenticado;
- navegacao entre placeholders da 11.3;
- tratamento de loading, erro, 401 e 403.

O backend continua autoridade final de autenticacao, RBAC e isolamento.

---

## 2. Fluxo de autenticacao

```
Nao autenticado
  -> /login
  -> POST /api/v1/auth/login {email, senha}
  -> data.token + data.usuario
  -> sessionStorage (somente o token)
  -> GET /api/v1/me (X-Session-Token)
  -> /dashboard (area protegida)

Reload / navegacao
  -> token em sessionStorage?
  -> GET /me
  -> autenticado: permanece na area
  -> 401: limpa token, marca sessao expirada, /login

Sair
  -> POST /api/v1/auth/logout (X-Session-Token)
  -> remove token local
  -> /login
```

Endpoints utilizados (existentes, sem criacao):

| Metodo | Caminho | Papel |
|---|---|---|
| POST | `/api/v1/auth/login` | credenciais -> token bruto 1x |
| GET | `/api/v1/me` | sessao valida / usuario publico |
| POST | `/api/v1/auth/logout` | revoga sessao no backend |

Cadastro publico (`POST /auth/register`) nao entra nesta etapa.

---

## 3. Gerenciamento do X-Session-Token

Implementacao em `frontend/src/lib/session.ts` e `frontend/src/lib/api.ts`.

Regras:

- credencial **somente** no header `X-Session-Token`;
- token **nunca** na URL, query, path ou cookie;
- senha **nunca** em `localStorage` / `sessionStorage`;
- token em `sessionStorage` (`ef_session_token`) para sobreviver a
  navegacao e reload na mesma aba, sem persistir apos fechar o browser;
- login nao envia o header (rota publica);
- demais chamadas anexam o token automaticamente;
- 401 com token presente: limpa storage e marca `ef_session_expired`;
- 403: nao revoga a sessao (usuario autenticado sem permissao).

O cliente recusa montar URL com `token`, `x-session-token`, `api-key`
ou `senha`.

---

## 4. Protecao das rotas

`AuthProvider` restaura a sessao via `/me` no boot.

`ProtectedRoute` usa `frontend/src/lib/guards.ts`:

| Estado | Caminho | Destino |
|---|---|---|
| `unauthenticated` | qualquer rota privada | `/login` |
| `authenticated` | `/login` | `/dashboard` |
| `loading` | qualquer | tela de verificacao |
| `error` | qualquer | erro + retry (API indisponivel) |

Rotas privadas (placeholders 11.3, agora atras do login):

- `/dashboard`
- `/ativos`
- `/indicadores`
- `/documentos`
- `/alertas`
- `/preferencias`

`/` continua redirecionando para `/dashboard` (e portanto exige sessao).

`AppGate` renderiza `AppShell` (header + sidebar) so na area autenticada.
A tela de login e full-screen, sem menu.

Nao ha bypass: ausencia de token ou `/me` 401 impede o acesso a area.

---

## 5. Tratamento de sessao

| Evento | UI |
|---|---|
| Boot | "Verificando sessao" |
| Login ok | redireciona para `/dashboard` |
| Credenciais invalidas | alerta na tela de login (401 generico) |
| Sessao expirada / invalida | mensagem "Sessao expirada" no login |
| Logout | revoga na API, limpa token, `/login` |
| API fora no boot | `ErrorState` + tentar novamente |
| 403 em chamada autenticada | banner "Acesso negado" no AppShell |

Header autenticado: nome, email, papel (somente exibicao) e botao Sair.

---

## 6. Integracao com a API

Mesmo cliente da 11.3 (`apiFetch`):

- envelope `{status, data, meta}`;
- base `NEXT_PUBLIC_API_BASE_URL` (padrao `/api/v1`);
- proxy Next ` /api/:path*` -> Flask (`API_PROXY_TARGET`);
- `loginRequest` / `meRequest` / `logoutRequest` em `frontend/src/lib/api.ts`;
- `signIn` / `signOut` / `restoreSession` em `frontend/src/lib/auth.ts`.

O frontend **nao** importa `services/`, banco, Sheets ou scrapers.

Isolamento: cada aba usa o token da propria sessao. Trocar o token
troca o `X-Session-Token` da proxima chamada. O backend continua
isolando dados por usuario autenticado.

---

## 7. Decisoes de seguranca

1. **Nao inventar autenticacao.** Reuso exclusivo de login/logout/me.
2. **Backend e autoridade.** O frontend nao replica a matriz RBAC.
   `papel` e exibido; autorizacao continua em `api/auth.py`.
3. **Token so em header.** Recusa query/path. Nunca `Authorization: Bearer`.
4. **Senha so no POST de login**, no corpo JSON, sem persistir.
5. **sessionStorage, nao localStorage**, para o token: sobrevive a
   reload, some ao fechar a aba. Nao e HttpOnly; cookie nao existe no
   contrato atual (11.1/11.2).
6. **401 != 403.** 401 encerra sessao local. 403 informa negacao.
7. **Sem secrets no frontend.** Nenhuma API Key, DATABASE_URL ou senha
   de servico.
8. **Anti-enumeracao preservada.** Mensagem de login invalido e generica.

---

## 8. RBAC no frontend (preparacao, sem duplicar regras)

`frontend/src/lib/rbac.ts` expoe `papelDoUsuario` / `exibirPapel` para
rotulacao. Nao decide acesso a recurso. Telas futuras devem:

- chamar a API;
- respeitar 403/404 do backend;
- nao esconder endpoint como se isso fosse controle de acesso.

ADMIN sem carteira pessoal permanece regra de backend (11.1).

---

## 9. Identidade visual

Tokens da 11.3 preservados (`sand`, `olive`, `gold`, Inter / Allerta
Stencil / Montserrat). Login usa `LogoSlot` existente. Sem logotipo
novo. Estetica tatico-corporativa, sem excesso militar.

---

## 10. O que esta etapa nao fez

- Dashboard financeiro real, graficos, carteira, analise de ativos
- Documentos / alertas funcionais
- Cadastro publico na UI
- Cookie HttpOnly, refresh, Bearer
- Endpoints novos, banco, Sheets, pagamentos, LLM
- Etapa 11.5

---

## 11. Arquivos

| Arquivo | Papel |
|---|---|
| `frontend/src/lib/session.ts` | token / expiracao / recusa URL |
| `frontend/src/lib/api.ts` | header, login/me/logout, 401/403 |
| `frontend/src/lib/auth.ts` | signIn / signOut / restoreSession |
| `frontend/src/lib/guards.ts` | redirecionamento publico/privado |
| `frontend/src/lib/rbac.ts` | exibicao de papel |
| `frontend/src/lib/types.ts` | Usuario / LoginPayload |
| `frontend/src/components/AuthProvider.tsx` | estado de autenticacao |
| `frontend/src/components/ProtectedRoute.tsx` | guarda de rotas |
| `frontend/src/components/AppGate.tsx` | shell so na area autenticada |
| `frontend/src/components/Header.tsx` | usuario + logout |
| `frontend/src/app/login/page.tsx` | tela de login |
| `frontend/src/app/layout.tsx` | provider + guarda |
| `docs/FASE11_ETAPA114_AUTENTICACAO_WEB.md` | este documento |

---

## 12. Testes

Frontend (Vitest):

- login bem-sucedido;
- login invalido;
- sessao valida (`/me`);
- sessao expirada/invalida;
- logout;
- rota protegida;
- 401 limpa token / 403 preserva;
- isolamento de token entre usuarios;
- token nunca na URL / senha nunca no storage.

Backend: regressao `tests/test_auth_web.py` (contrato login/me/logout
inalterado).

---

## 13. Veredito

**Etapa 11.4: CONCLUIDA.**

Area autenticada funcional sobre `/api/v1`. Sem Dashboard operacional.
Sem 11.5.
