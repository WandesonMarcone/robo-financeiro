import { afterEach, describe, expect, it, vi } from "vitest";
import { apiFetch, isForbidden, isUnauthorized } from "./api";
import { getSessionToken, setSessionToken, tokenNeverInUrl } from "./session";
import { buildApiUrl } from "./api";

describe("cliente API", () => {
  afterEach(() => {
    sessionStorage.clear();
    vi.unstubAllGlobals();
  });

  it("monta /api/v1 sem token na URL", () => {
    const url = buildApiUrl("/me");
    expect(url).toBe("/api/v1/me");
    expect(tokenNeverInUrl(url)).toBe(true);
  });

  it("aceita query de negocio e recusa token", () => {
    const url = buildApiUrl("/ativos", { ticker: "PETR4", page: 1 });
    expect(url).toContain("ticker=PETR4");
    expect(url).not.toContain("token");
    expect(() => buildApiUrl("/me", { token: "abc" })).toThrow();
  });

  it("envia X-Session-Token no header e nunca na URL", async () => {
    setSessionToken("tok-user-a");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        expect(url).toBe("/api/v1/me");
        expect(url).not.toMatch(/token/i);
        const headers = new Headers(init?.headers);
        expect(headers.get("X-Session-Token")).toBe("tok-user-a");
        return {
          ok: true,
          status: 200,
          json: async () => ({ status: "success", data: { email: "a@x.com" }, meta: {} }),
        };
      }),
    );
    const res = await apiFetch<{ email: string }>("/me");
    expect(res.data?.email).toBe("a@x.com");
  });

  it("401 limpa a sessao local", async () => {
    setSessionToken("tok-expirado");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: false,
        status: 401,
        json: async () => ({ status: "error", data: null, meta: { error: "Não autenticado." } }),
      })),
    );
    await expect(apiFetch("/me")).rejects.toSatisfy((err) => isUnauthorized(err));
    expect(getSessionToken()).toBeNull();
  });

  it("403 nao revoga a sessao", async () => {
    setSessionToken("tok-user-a");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: false,
        status: 403,
        json: async () => ({ status: "error", data: null, meta: { error: "Acesso negado." } }),
      })),
    );
    await expect(apiFetch("/usuarios")).rejects.toSatisfy((err) => isForbidden(err));
    expect(getSessionToken()).toBe("tok-user-a");
  });

  it("isolamento: troca de token nao mistura usuarios", async () => {
    const seen: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init?: RequestInit) => {
        seen.push(new Headers(init?.headers).get("X-Session-Token") || "");
        return {
          ok: true,
          status: 200,
          json: async () => ({ status: "success", data: { ok: true }, meta: {} }),
        };
      }),
    );
    setSessionToken("tok-a");
    await apiFetch("/me");
    setSessionToken("tok-b");
    await apiFetch("/me");
    expect(seen).toEqual(["tok-a", "tok-b"]);
    expect(getSessionToken()).toBe("tok-b");
  });
});
