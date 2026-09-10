import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "./AuthProvider";
import { CarteiraView } from "./CarteiraView";
import { setSessionToken } from "@/lib/session";

const nav = vi.hoisted(() => ({
  pathname: "/carteira",
  replace: vi.fn(),
  push: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace, push: nav.push }),
  usePathname: () => nav.pathname,
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    className,
  }: {
    href: string;
    children: unknown;
    className?: string;
  }) => (
    <a href={href} className={className}>
      {children as string}
    </a>
  ),
}));

const usuarioA = {
  id: 1,
  nome: "Alice",
  email: "alice@x.com",
  papel: "USER",
  plano: "FREE",
  ativo: true,
  telegram_vinculado: false,
  ultimo_login: null,
  criado_em: null,
  atualizado_em: null,
};

const usuarioB = {
  ...usuarioA,
  id: 2,
  nome: "Bob",
  email: "bob@x.com",
};

function envelope(status: number, data: unknown, meta: Record<string, unknown> = {}, error?: string) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () =>
      status >= 200 && status < 300
        ? { status: "success", data, meta }
        : { status: "error", data: null, meta: { error: error || "erro" } },
  };
}

function pathOf(url: string): string {
  return String(url).split("?")[0];
}

const posicaoAlice = {
  id: 11,
  ativo_id: 101,
  ticker: "HGLG11",
  tipo: "FII",
  quantidade: 10,
  preco_medio: 150,
  valor_investido: 1500,
  criado_em: "2026-01-01T00:00:00",
  atualizado_em: "2026-01-02T00:00:00",
};

const posicaoParcial = {
  id: 12,
  ativo_id: 202,
  ticker: "PETR4",
  tipo: "ACAO",
  quantidade: null,
  preco_medio: null,
  valor_investido: null,
  criado_em: null,
  atualizado_em: null,
};

const snapshotHglg = {
  id: 31,
  ativo_id: 101,
  ticker: "HGLG11",
  tipo: "FII",
  data_referencia: "2026-09-01",
  data_coleta: "2026-09-01T12:00:00",
  data_publicacao: null,
  fonte: "persistido",
  preco: 160.5,
  dy: 0.08,
  pvp: 0.95,
  vpa: 170,
  campos: {
    preco: { semantica: "PRESENTE", unidade: "R$", escala: "monetario", aplicavel: true },
  },
};

function freshnessOk() {
  return envelope(200, {
    ticker: "HGLG11",
    tipo: "FII",
    categorias: {
      mercado: {
        categoria: "mercado",
        status: "FRESH",
        valor: 160.5,
        data_referencia: "2026-09-01",
        data_coleta: "2026-09-01T12:00:00",
        data_publicacao: null,
        fonte: "persistido",
      },
    },
  });
}

type Scenario = {
  usuario?: typeof usuarioA;
  me?: ReturnType<typeof envelope>;
  carteira?: ReturnType<typeof envelope>;
  snapshots?: ReturnType<typeof envelope>;
  freshness?: ReturnType<typeof envelope>;
};

function installApi(scenario: Scenario) {
  const seenTokens: string[] = [];
  const seenUrls: string[] = [];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const headers = new Headers(init?.headers);
    seenTokens.push(headers.get("X-Session-Token") || "");
    seenUrls.push(String(url));
    const path = pathOf(url);
    if (path.endsWith("/me") && !path.endsWith("/me/plano")) {
      return scenario.me || envelope(200, scenario.usuario || usuarioA);
    }
    if (path.endsWith("/carteira")) {
      return scenario.carteira || envelope(200, [], { total: 0 });
    }
    if (path.endsWith("/mercado/snapshots")) {
      return scenario.snapshots || envelope(200, [], { total: 0 });
    }
    if (path.endsWith("/mercado/freshness")) {
      return scenario.freshness || freshnessOk();
    }
    return envelope(404, null, {}, "nao encontrado");
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, seenTokens, seenUrls };
}

function renderCarteira(token = "tok-alice") {
  setSessionToken(token);
  return render(
    <AuthProvider>
      <CarteiraView />
    </AuthProvider>,
  );
}

describe("carteira autenticada", () => {
  afterEach(() => {
    cleanup();
    sessionStorage.clear();
    localStorage.clear();
    nav.replace.mockReset();
    vi.unstubAllGlobals();
  });

  it("exibe loading enquanto busca a API", async () => {
    let release: () => void = () => undefined;
    const pending = new Promise<void>((resolve) => {
      release = resolve;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const path = pathOf(url);
        if (path.endsWith("/me") && !path.endsWith("/me/plano")) {
          return envelope(200, usuarioA);
        }
        await pending;
        return envelope(200, [], { total: 0 });
      }),
    );
    renderCarteira();
    expect(await screen.findByText("Carregando carteira")).toBeInTheDocument();
    release();
    await waitFor(() => expect(screen.queryByText("Carregando carteira")).not.toBeInTheDocument());
  });

  it("carteira vazia nao inventa ticker nem valor investido", async () => {
    installApi({
      carteira: envelope(200, [], { total: 0 }),
    });
    renderCarteira();
    expect(await screen.findByText("Carteira vazia")).toBeInTheDocument();
    expect(screen.queryByText("HGLG11")).not.toBeInTheDocument();
    expect(screen.queryByText("R$ 0,00")).not.toBeInTheDocument();
    expect(screen.getByText("Valor investido")).toBeInTheDocument();
  });

  it("carteira com dados reais da API", async () => {
    const { seenUrls } = installApi({
      carteira: envelope(200, [posicaoAlice], { total: 1 }),
      snapshots: envelope(200, [snapshotHglg], { total: 1 }),
      freshness: freshnessOk(),
    });
    renderCarteira();
    expect((await screen.findAllByText("HGLG11")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Valor investido").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/R\$\s*1\.500,00/).length).toBeGreaterThan(0);
    expect(screen.queryByText("patrimonio")).not.toBeInTheDocument();
    expect(screen.queryByText("Patrimonio")).not.toBeInTheDocument();
    expect(seenUrls.some((url) => url.startsWith("/api/v1/carteira"))).toBe(true);
    expect(seenUrls.some((url) => url.startsWith("/api/v1/mercado/snapshots"))).toBe(true);
    expect(seenUrls.every((url) => !url.toLowerCase().includes("token="))).toBe(true);
  });

  it("navega da posicao para /ativos/[ticker]", async () => {
    installApi({
      carteira: envelope(200, [posicaoAlice], { total: 1 }),
      snapshots: envelope(200, [snapshotHglg], { total: 1 }),
      freshness: freshnessOk(),
    });
    renderCarteira();
    const links = await screen.findAllByRole("link", { name: "HGLG11" });
    expect(links.length).toBeGreaterThan(0);
    expect(links.every((link) => link.getAttribute("href") === "/ativos/HGLG11")).toBe(true);
  });

  it("campos ausentes nao viram zero", async () => {
    installApi({
      carteira: envelope(200, [posicaoParcial], { total: 1 }),
      snapshots: envelope(200, [], { total: 0 }),
    });
    renderCarteira();
    expect((await screen.findAllByText("PETR4")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("AUSENTE").length).toBeGreaterThan(0);
    expect(screen.queryByText("R$ 0,00")).not.toBeInTheDocument();
  });

  it("erro da API mostra estado de erro", async () => {
    installApi({
      carteira: envelope(500, null, {}, "Erro interno do servidor."),
    });
    renderCarteira();
    expect(await screen.findByText("Falha ao carregar carteira")).toBeInTheDocument();
    expect(screen.getByText("Erro interno do servidor.")).toBeInTheDocument();
  });

  it("401 na carteira exibe nao autenticado", async () => {
    installApi({
      carteira: envelope(401, null, {}, "Não autenticado."),
    });
    renderCarteira();
    expect(await screen.findByText("Nao autenticado (401)")).toBeInTheDocument();
  });

  it("403 de carteira pessoal informa acesso negado", async () => {
    installApi({
      usuario: { ...usuarioA, papel: "ADMIN", nome: "Operador" },
      carteira: envelope(403, null, {}, "Acesso negado."),
    });
    renderCarteira();
    expect(await screen.findByText("Acesso negado (403)")).toBeInTheDocument();
    expect(screen.getByText("Carteira")).toBeInTheDocument();
    expect(sessionStorage.getItem("ef_session_token")).toBe("tok-alice");
    expect(screen.queryByText("HGLG11")).not.toBeInTheDocument();
  });

  it("isolamento: cada sessao envia o proprio X-Session-Token", async () => {
    const { seenTokens } = installApi({
      carteira: envelope(200, [posicaoAlice], { total: 1 }),
      snapshots: envelope(200, [snapshotHglg], { total: 1 }),
      freshness: freshnessOk(),
    });
    renderCarteira("tok-alice");
    await screen.findAllByText("HGLG11");
    expect(seenTokens.every((token) => token === "tok-alice" || token === "")).toBe(true);
    expect(seenTokens.some((token) => token === "tok-alice")).toBe(true);
    expect(seenTokens.some((token) => token === "tok-bob")).toBe(false);
    expect(usuarioB.email).toBe("bob@x.com");
  });
});
