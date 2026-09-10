import { afterEach, describe, expect, it, vi } from "vitest";
import { restoreSession, signIn, signOut, credentialsWereStored } from "./auth";
import { getSessionToken, setSessionToken } from "./session";
import type { Usuario } from "./types";

const usuario: Usuario = {
  id: 1,
  nome: "Usuario",
  email: "user@x.com",
  papel: "USER",
  plano: "free",
  ativo: true,
  telegram_vinculado: false,
  ultimo_login: null,
  criado_em: null,
  atualizado_em: null,
};

function envelope<T>(data: T, status = 200, error?: string) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () =>
      status >= 200 && status < 300
        ? { status: "success", data, meta: {} }
        : { status: "error", data: null, meta: { error: error || "erro" } },
  };
}

describe("auth manager", () => {
  afterEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("login bem-sucedido guarda token e usuario", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => envelope({ token: "tok-a", usuario })),
    );
    const result = await signIn("user@x.com", "senha1234");
    expect(result.email).toBe("user@x.com");
    expect(getSessionToken()).toBe("tok-a");
    expect(credentialsWereStored()).toBe(false);
    const call = vi.mocked(fetch).mock.calls[0];
    const url = String(call[0]);
    const init = call[1] as RequestInit;
    expect(url).toBe("/api/v1/auth/login");
    expect(url).not.toContain("token");
    expect(JSON.parse(String(init.body))).toEqual({ email: "user@x.com", senha: "senha1234" });
    const headers = new Headers(init.headers);
    expect(headers.get("X-Session-Token")).toBeNull();
  });

  it("login invalido nao cria sessao", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => envelope(null, 401, "Credenciais inválidas.")),
    );
    await expect(signIn("user@x.com", "errada")).rejects.toMatchObject({ statusCode: 401 });
    expect(getSessionToken()).toBeNull();
  });

  it("sessao valida via /me", async () => {
    setSessionToken("tok-a");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        expect(url).toBe("/api/v1/me");
        const headers = new Headers(init?.headers);
        expect(headers.get("X-Session-Token")).toBe("tok-a");
        return envelope(usuario);
      }),
    );
    const me = await restoreSession();
    expect(me?.email).toBe("user@x.com");
    expect(getSessionToken()).toBe("tok-a");
  });

  it("sessao expirada limpa o token", async () => {
    setSessionToken("tok-expirado");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => envelope(null, 401, "Não autenticado.")),
    );
    const me = await restoreSession();
    expect(me).toBeNull();
    expect(getSessionToken()).toBeNull();
  });

  it("logout revoga na API e remove token local", async () => {
    setSessionToken("tok-a");
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      expect(url).toBe("/api/v1/auth/logout");
      const headers = new Headers(init?.headers);
      expect(headers.get("X-Session-Token")).toBe("tok-a");
      return envelope({ logout: true });
    });
    vi.stubGlobal("fetch", fetchMock);
    await signOut();
    expect(getSessionToken()).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
