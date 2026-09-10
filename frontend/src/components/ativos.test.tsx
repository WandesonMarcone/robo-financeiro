import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "./AuthProvider";
import { AtivoDetalheView } from "./AtivoDetalheView";
import { AtivosView } from "./AtivosView";
import { setSessionToken } from "@/lib/session";

const nav = vi.hoisted(() => ({
  pathname: "/ativos",
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

function queryOf(url: string): URLSearchParams {
  const raw = String(url);
  const idx = raw.indexOf("?");
  return new URLSearchParams(idx >= 0 ? raw.slice(idx + 1) : "");
}

const ativoHglg = {
  id: 101,
  ticker: "HGLG11",
  cnpj: "00.000.000/0001-00",
  tipo: "FII",
  setor: "Logistica",
  tipo_fii: "Tijolo",
};

const ativoPetr = {
  id: 202,
  ticker: "PETR4",
  cnpj: null,
  tipo: "ACAO",
  setor: "Petroleo",
  tipo_fii: null,
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
  fonte_primaria: "b3",
  fonte_intermediaria: null,
  url_origem: null,
  preco: 160.5,
  dy: 0.08,
  pvp: 0.95,
  vpa: 0,
  proveniencia: { dy: "snapshots_fiis.dy (fracao 0-1)" },
  campos: {
    preco: { semantica: "PRESENTE", unidade: "R$", escala: "monetario", aplicavel: true },
    dy: { semantica: "PRESENTE", unidade: "%", escala: "fracao", aplicavel: true },
    pvp: { semantica: "PRESENTE", unidade: "x", escala: "multiplo", aplicavel: true },
    vpa: { semantica: "ZERO", unidade: "R$", escala: "monetario", aplicavel: true },
  },
};

const indicadoresDetalhe = [
  {
    id: 41,
    ativo_id: 101,
    ticker: "HGLG11",
    tipo_ativo: "FII",
    indicador: "vacancia_fisica",
    valor_atual: null,
    valor_anterior: null,
    variacao_percentual: null,
    data_referencia: "2026-09-01",
    data_ultima_alteracao: null,
    ultima_coleta: null,
    origem: "cvm",
    semantica: "AUSENTE",
    unidade: "%",
    escala: "fracao",
    aplicavel: true,
  },
  {
    id: 42,
    ativo_id: 101,
    ticker: "HGLG11",
    tipo_ativo: "FII",
    indicador: "qtd_imoveis",
    valor_atual: 0,
    valor_anterior: null,
    variacao_percentual: null,
    data_referencia: "2026-09-01",
    data_ultima_alteracao: null,
    ultima_coleta: "2026-09-01T12:00:00",
    origem: "mercado",
    semantica: "ZERO",
    unidade: "un.",
    escala: "quantidade",
    aplicavel: true,
  },
  {
    id: 43,
    ativo_id: 101,
    ticker: "HGLG11",
    tipo_ativo: "FII",
    indicador: "pl",
    valor_atual: null,
    valor_anterior: null,
    variacao_percentual: null,
    data_referencia: null,
    data_ultima_alteracao: null,
    ultima_coleta: null,
    origem: null,
    semantica: "NAO_APLICAVEL",
    unidade: null,
    escala: null,
    aplicavel: false,
  },
  {
    id: 44,
    ativo_id: 101,
    ticker: "HGLG11",
    tipo_ativo: "FII",
    indicador: "pvp",
    valor_atual: 0.95,
    valor_anterior: 1,
    variacao_percentual: -5,
    data_referencia: "2026-09-01",
    data_ultima_alteracao: null,
    ultima_coleta: "2026-09-01T12:00:00",
    origem: "mercado",
    semantica: "PRESENTE",
    unidade: "x",
    escala: "multiplo",
    aplicavel: true,
  },
  {
    id: 45,
    ativo_id: 101,
    ticker: "HGLG11",
    tipo_ativo: "FII",
    indicador: "alavancagem",
    valor_atual: 1,
    valor_anterior: null,
    variacao_percentual: null,
    data_referencia: "2026-09-01",
    data_ultima_alteracao: null,
    ultima_coleta: null,
    origem: "mercado",
    semantica: "INVALIDO",
    unidade: null,
    escala: null,
    aplicavel: true,
  },
];

const posicaoAlice = {
  id: 11,
  ativo_id: 101,
  ticker: "HGLG11",
  tipo: "FII",
  quantidade: 10,
  preco_medio: 150,
  valor_investido: 1500,
  criado_em: "2026-01-01T00:00:00",
  atualizado_em: "2026-01-01T00:00:00",
};

const acompanhamentoAlice = {
  id: 21,
  ativo_id: 101,
  ticker: "HGLG11",
  tipo: "FII",
  criado_em: "2026-01-01T00:00:00",
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
  token?: string;
  usuario?: typeof usuarioA;
  me?: ReturnType<typeof envelope>;
  ativos?: ReturnType<typeof envelope> | ((query: URLSearchParams) => ReturnType<typeof envelope>);
  carteira?: ReturnType<typeof envelope>;
  acompanhados?: ReturnType<typeof envelope>;
  snapshots?: ReturnType<typeof envelope>;
  snapshotRecente?: ReturnType<typeof envelope>;
  indicadores?: ReturnType<typeof envelope>;
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
    const query = queryOf(url);
    if (path.endsWith("/me") && !path.endsWith("/me/plano")) {
      return scenario.me || envelope(200, scenario.usuario || usuarioA);
    }
    if (path.endsWith("/ativos") && !path.includes("ativos-acompanhados")) {
      if (typeof scenario.ativos === "function") {
        return scenario.ativos(query);
      }
      return scenario.ativos || envelope(200, [ativoHglg, ativoPetr], { total: 2, page: 1, page_size: 20, has_next: false });
    }
    if (path.endsWith("/carteira")) {
      return scenario.carteira || envelope(200, [], { total: 0 });
    }
    if (path.endsWith("/ativos-acompanhados")) {
      return scenario.acompanhados || envelope(200, [], { total: 0 });
    }
    if (path.endsWith("/mercado/snapshots/mais-recente")) {
      return scenario.snapshotRecente || envelope(200, snapshotHglg);
    }
    if (path.endsWith("/mercado/snapshots")) {
      return scenario.snapshots || envelope(200, [snapshotHglg], { total: 1 });
    }
    if (path.endsWith("/indicadores")) {
      return scenario.indicadores || envelope(200, [], { total: 0 });
    }
    if (path.endsWith("/mercado/freshness")) {
      return scenario.freshness || freshnessOk();
    }
    return envelope(404, null, {}, "nao encontrado");
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, seenTokens, seenUrls };
}

function renderList(token = "tok-alice") {
  setSessionToken(token);
  return render(
    <AuthProvider>
      <AtivosView />
    </AuthProvider>,
  );
}

function renderDetail(ticker = "HGLG11", token = "tok-alice") {
  setSessionToken(token);
  return render(
    <AuthProvider>
      <AtivoDetalheView ticker={ticker} />
    </AuthProvider>,
  );
}

describe("listagem de ativos", () => {
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
        if (path.endsWith("/ativos") && !path.includes("ativos-acompanhados")) {
          return envelope(200, [], { total: 0 });
        }
        return envelope(200, [], { total: 0 });
      }),
    );
    renderList();
    expect(await screen.findByText("Carregando ativos")).toBeInTheDocument();
    release();
    await waitFor(() => expect(screen.queryByText("Carregando ativos")).not.toBeInTheDocument());
  });

  it("lista ativos reais da API", async () => {
    const { fetchMock } = installApi({
      carteira: envelope(200, [posicaoAlice], { total: 1 }),
      acompanhados: envelope(200, [acompanhamentoAlice], { total: 1 }),
    });
    renderList();
    expect(await screen.findByText("HGLG11")).toBeInTheDocument();
    expect(screen.getByText("PETR4")).toBeInTheDocument();
    expect(screen.getByText("Carteira")).toBeInTheDocument();
    expect(screen.getByText("Acompanhado")).toBeInTheDocument();
    const urls = fetchMock.mock.calls.map((call) => String(call[0]));
    expect(urls.some((url) => url.startsWith("/api/v1/ativos"))).toBe(true);
    expect(urls.some((url) => url.startsWith("/api/v1/mercado/snapshots"))).toBe(true);
    expect(urls.every((url) => !url.toLowerCase().includes("token="))).toBe(true);
    expect(screen.getByRole("link", { name: "HGLG11" })).toHaveAttribute("href", "/ativos/HGLG11");
  });

  it("pesquisa por ticker envia igualdade exata e nao filtra no cliente", async () => {
    const { seenUrls } = installApi({
      ativos: (query) => {
        const ticker = query.get("ticker");
        if (ticker === "PETR4") {
          return envelope(200, [ativoPetr], { total: 1, page: 1, page_size: 20, has_next: false });
        }
        if (ticker === "PETR") {
          return envelope(200, [], { total: 0, page: 1, page_size: 20, has_next: false });
        }
        return envelope(200, [ativoHglg, ativoPetr], { total: 2, page: 1, page_size: 20, has_next: false });
      },
    });
    renderList();
    expect(await screen.findByText("HGLG11")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Ticker"), { target: { value: " petr4 " } });
    fireEvent.submit(screen.getByLabelText("Ticker").closest("form") as HTMLFormElement);
    await waitFor(() => expect(screen.queryByText("HGLG11")).not.toBeInTheDocument());
    expect(screen.getByText("PETR4")).toBeInTheDocument();
    expect(seenUrls.some((url) => url.includes("ticker=PETR4"))).toBe(true);

    fireEvent.change(screen.getByLabelText("Ticker"), { target: { value: "PETR" } });
    fireEvent.submit(screen.getByLabelText("Ticker").closest("form") as HTMLFormElement);
    expect(await screen.findByText("Nenhum ativo retornado")).toBeInTheDocument();
    expect(screen.queryByText("PETR4")).not.toBeInTheDocument();
    expect(seenUrls.some((url) => url.includes("ticker=PETR") && !url.includes("ticker=PETR4"))).toBe(true);
  });

  it("empty nao inventa ticker", async () => {
    installApi({
      ativos: envelope(200, [], { total: 0, page: 1, page_size: 20, has_next: false }),
    });
    renderList();
    expect(await screen.findByText("Nenhum ativo retornado")).toBeInTheDocument();
    expect(screen.queryByText("HGLG11")).not.toBeInTheDocument();
    expect(screen.queryByText("PETR4")).not.toBeInTheDocument();
  });

  it("erro da API mostra estado de erro", async () => {
    installApi({
      ativos: envelope(500, null, {}, "Erro interno do servidor."),
    });
    renderList();
    expect(await screen.findByText("Falha ao carregar ativos")).toBeInTheDocument();
    expect(screen.getByText("Erro interno do servidor.")).toBeInTheDocument();
  });

  it("401 na listagem exibe nao autenticado", async () => {
    installApi({
      ativos: envelope(401, null, {}, "Não autenticado."),
    });
    renderList();
    expect(await screen.findByText("Nao autenticado (401)")).toBeInTheDocument();
  });

  it("403 na listagem nao inventa dados", async () => {
    installApi({
      usuario: { ...usuarioA, papel: "ADMIN", nome: "Operador" },
      ativos: envelope(403, null, {}, "Acesso negado."),
    });
    renderList();
    expect(await screen.findByText("Acesso negado (403)")).toBeInTheDocument();
    expect(screen.queryByText("HGLG11")).not.toBeInTheDocument();
    expect(sessionStorage.getItem("ef_session_token")).toBe("tok-alice");
  });

  it("isolamento: cada sessao envia o proprio X-Session-Token", async () => {
    const { seenTokens } = installApi({});
    renderList("tok-alice");
    await screen.findByText("HGLG11");
    expect(seenTokens.some((token) => token === "tok-alice")).toBe(true);
    expect(seenTokens.some((token) => token === "tok-bob")).toBe(false);
  });

  it("layout de listagem permanece utilizavel em viewport estreita", async () => {
    installApi({});
    const { container } = renderList();
    await screen.findByText("HGLG11");
    expect(container.querySelector(".overflow-x-auto")).toBeTruthy();
    expect(screen.getByLabelText("Ticker")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pesquisar" })).toBeInTheDocument();
  });
});

describe("detalhamento do ativo", () => {
  afterEach(() => {
    cleanup();
    sessionStorage.clear();
    localStorage.clear();
    nav.replace.mockReset();
    vi.unstubAllGlobals();
  });

  it("exibe loading enquanto busca o detalhe", async () => {
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
    renderDetail("HGLG11");
    expect(await screen.findByText("Carregando ativo")).toBeInTheDocument();
    release();
    await waitFor(() => expect(screen.queryByText("Carregando ativo")).not.toBeInTheDocument());
  });

  it("monta o detalhe com dados reais da API", async () => {
    const { fetchMock } = installApi({
      ativos: envelope(200, [ativoHglg], { total: 1 }),
      snapshotRecente: envelope(200, snapshotHglg),
      indicadores: envelope(200, indicadoresDetalhe, { total: indicadoresDetalhe.length }),
      freshness: freshnessOk(),
      carteira: envelope(200, [posicaoAlice], { total: 1 }),
      acompanhados: envelope(200, [acompanhamentoAlice], { total: 1 }),
    });
    renderDetail("HGLG11");
    expect((await screen.findAllByText("HGLG11")).length).toBeGreaterThan(0);
    expect(screen.getByText("vacancia_fisica")).toBeInTheDocument();
    expect(screen.getByText("Carteira")).toBeInTheDocument();
    expect(screen.getByText("Acompanhado")).toBeInTheDocument();
    expect(screen.getByText("Logistica")).toBeInTheDocument();
    expect(screen.getByText("snapshots_fiis.dy (fracao 0-1)")).toBeInTheDocument();
    const urls = fetchMock.mock.calls.map((call) => String(call[0]));
    expect(urls.some((url) => url.startsWith("/api/v1/ativos") && url.includes("ticker=HGLG11"))).toBe(true);
    expect(urls.some((url) => url.startsWith("/api/v1/mercado/snapshots/mais-recente"))).toBe(true);
    expect(urls.some((url) => url.startsWith("/api/v1/indicadores") && url.includes("ticker=HGLG11"))).toBe(true);
    expect(urls.some((url) => url.startsWith("/api/v1/mercado/freshness") && url.includes("ticker=HGLG11"))).toBe(true);
  });

  it("ativo inexistente nao inventa cadastro", async () => {
    installApi({
      ativos: envelope(200, [], { total: 0 }),
      snapshotRecente: envelope(404, null, {}, "Nenhum snapshot de mercado encontrado."),
      freshness: envelope(404, null, {}, "Ativo não encontrado para freshness."),
    });
    renderDetail("XXXX11");
    expect(await screen.findByText("Ativo inexistente")).toBeInTheDocument();
    expect(screen.queryByText("R$ 0,00")).not.toBeInTheDocument();
  });

  it("respeita estados semanticos dos indicadores", async () => {
    installApi({
      ativos: envelope(200, [ativoHglg], { total: 1 }),
      indicadores: envelope(200, indicadoresDetalhe, { total: indicadoresDetalhe.length }),
    });
    renderDetail("HGLG11");
    expect(await screen.findByText("vacancia_fisica")).toBeInTheDocument();
    expect(screen.getByText("qtd_imoveis")).toBeInTheDocument();
    expect(screen.getByText("pl")).toBeInTheDocument();
    expect(screen.getByText("alavancagem")).toBeInTheDocument();
    expect(screen.getAllByText("AUSENTE").length).toBeGreaterThan(0);
    expect(screen.getAllByText("ZERO").length).toBeGreaterThan(0);
    expect(screen.getAllByText("NAO_APLICAVEL").length).toBeGreaterThan(0);
    expect(screen.getAllByText("INVALIDO").length).toBeGreaterThan(0);
    expect(screen.getAllByText("PRESENTE").length).toBeGreaterThan(0);
  });

  it("exibe freshness FRESH da API", async () => {
    installApi({
      ativos: envelope(200, [ativoHglg], { total: 1 }),
      freshness: freshnessOk(),
    });
    renderDetail("HGLG11");
    expect((await screen.findAllByText("FRESH")).length).toBeGreaterThan(0);
  });

  it("401 no detalhe exibe nao autenticado", async () => {
    installApi({
      ativos: envelope(401, null, {}, "Não autenticado."),
    });
    renderDetail("HGLG11");
    expect(await screen.findByText("Nao autenticado (401)")).toBeInTheDocument();
  });

  it("403 no detalhe nao inventa dados", async () => {
    installApi({
      usuario: { ...usuarioA, papel: "ADMIN" },
      ativos: envelope(403, null, {}, "Acesso negado."),
    });
    renderDetail("HGLG11");
    expect(await screen.findByText("Acesso negado (403)")).toBeInTheDocument();
    expect(screen.queryByText("vacancia_fisica")).not.toBeInTheDocument();
  });

  it("erro no detalhe permanece visivel", async () => {
    installApi({
      ativos: envelope(500, null, {}, "Erro interno do servidor."),
    });
    renderDetail("HGLG11");
    expect(await screen.findByText("Falha ao carregar ativo")).toBeInTheDocument();
    expect(screen.getByText("Erro interno do servidor.")).toBeInTheDocument();
  });
});
