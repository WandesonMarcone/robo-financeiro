import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "./AuthProvider";
import { ProtectedRoute } from "./ProtectedRoute";
import { Header } from "./Header";
import LoginPage from "@/app/login/page";

const nav = vi.hoisted(() => ({
  pathname: "/login",
  replace: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace, push: vi.fn() }),
  usePathname: () => nav.pathname,
}));

function envelope(status: number, data: unknown, error?: string) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () =>
      status >= 200 && status < 300
        ? { status: "success", data, meta: {} }
        : { status: "error", data: null, meta: { error: error || "erro" } },
  };
}

const usuario = {
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

describe("fluxo autenticado", () => {
  afterEach(() => {
    cleanup();
    sessionStorage.clear();
    localStorage.clear();
    nav.replace.mockReset();
    nav.pathname = "/login";
    vi.unstubAllGlobals();
  });

  it("login bem-sucedido redireciona para a area principal", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => envelope(200, { token: "tok-ok", usuario })),
    );
    render(
      <AuthProvider>
        <LoginPage />
      </AuthProvider>,
    );
    const entrar = await screen.findByRole("button", { name: "Entrar" });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "user@x.com" } });
    fireEvent.change(screen.getByLabelText("Senha"), { target: { value: "senha1234" } });
    fireEvent.click(entrar);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/dashboard"));
    expect(sessionStorage.getItem("ef_session_token")).toBe("tok-ok");
    expect(localStorage.length).toBe(0);
  });

  it("login invalido exibe erro e nao autentica", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => envelope(401, null, "Credenciais inválidas.")),
    );
    render(
      <AuthProvider>
        <LoginPage />
      </AuthProvider>,
    );
    const entrar = await screen.findByRole("button", { name: "Entrar" });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "user@x.com" } });
    fireEvent.change(screen.getByLabelText("Senha"), { target: { value: "errada" } });
    fireEvent.click(entrar);
    expect(await screen.findByRole("alert")).toHaveTextContent("Credenciais invalidas.");
    expect(sessionStorage.getItem("ef_session_token")).toBeNull();
    expect(nav.replace).not.toHaveBeenCalledWith("/dashboard");
  });

  it("rota protegida redireciona nao autenticado para login", async () => {
    nav.pathname = "/dashboard";
    render(
      <AuthProvider>
        <ProtectedRoute>
          <p>area protegida</p>
        </ProtectedRoute>
      </AuthProvider>,
    );
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/login"));
    expect(screen.queryByText("area protegida")).not.toBeInTheDocument();
  });

  it("logout remove sessao e volta ao login", async () => {
    sessionStorage.setItem("ef_session_token", "tok-ok");
    nav.pathname = "/dashboard";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (String(url).endsWith("/me")) {
          return envelope(200, usuario);
        }
        if (String(url).endsWith("/auth/logout")) {
          return envelope(200, { logout: true });
        }
        return envelope(404, null, "nao encontrado");
      }),
    );
    render(
      <AuthProvider>
        <Header onMenu={() => undefined} />
      </AuthProvider>,
    );
    expect(await screen.findByText("Usuario")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sair" }));
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/login"));
    expect(sessionStorage.getItem("ef_session_token")).toBeNull();
  });
});
