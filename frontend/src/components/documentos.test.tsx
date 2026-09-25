import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "./AuthProvider";
import { DocumentosView } from "./DocumentosView";
import { setSessionToken } from "@/lib/session";

const nav = vi.hoisted(() => ({
  pathname: "/documentos",
  replace: vi.fn(),
  push: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace, push: nav.push }),
  usePathname: () => nav.pathname,
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

function queryOf(url: string): URLSearchParams {
  const raw = String(url);
  const idx = raw.indexOf("?");
  return new URLSearchParams(idx >= 0 ? raw.slice(idx + 1) : "");
}

const documentoHglg = {
  id: 11,
  ativo_id: 101,
  ticker: "HGLG11",
  data_publicacao: "2026-09-01",
  tipo_documento: "Relatorio Gerencial",
  url_pdf: "https://drive.example/hglg11.pdf",
  assunto: "Relatorio mensal HGLG11",
  id_b3: "B3-123",
  status_processamento: "SALVO",
  data_atualizacao: "2026-09-02T10:00:00",
};

const documentoSemAtivo = {
  id: 12,
  ativo_id: null,
  ticker: null,
  data_publicacao: "2026-08-01",
  tipo_documento: "Fato Relevante",
  url_pdf: "https://fnet.example/fato.pdf",
  assunto: "Fato sem ticker",
  id_b3: null,
  status_processamento: "SALVO",
  data_atualizacao: null,
};

const documentoAusente = {
  id: 13,
  ativo_id: null,
  ticker: null,
  data_publicacao: null,
  tipo_documento: null,
  url_pdf: null,
  assunto: null,
  id_b3: null,
  status_processamento: null,
  data_atualizacao: null,
};

type Scenario = {
  usuario?: typeof usuarioA;
  me?: ReturnType<typeof envelope>;
  documentos?: ReturnType<typeof envelope> | ((query: URLSearchParams) => ReturnType<typeof envelope>);
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
    if (path.endsWith("/documentos")) {
      if (typeof scenario.documentos === "function") {
        return scenario.documentos(query);
      }
      return scenario.documentos || envelope(200, [], { total: 0, page: 1, page_size: 20, has_next: false });
    }
    return envelope(404, null, {}, "nao encontrado");
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, seenTokens, seenUrls };
}

function renderDocumentos(token = "tok-alice") {
  setSessionToken(token);
  return render(
    <AuthProvider>
      <DocumentosView />
    </AuthProvider>,
  );
}

describe("area de documentos 11.9", () => {
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
    renderDocumentos();
    expect(await screen.findByText("Carregando documentos")).toBeInTheDocument();
    release();
    await waitFor(() => expect(screen.queryByText("Carregando documentos")).not.toBeInTheDocument());
  });

  it("lista vazia nao inventa documento", async () => {
    installApi({
      documentos: envelope(200, [], { total: 0, page: 1, page_size: 20, has_next: false }),
    });
    renderDocumentos();
    expect(await screen.findByText("Nenhum documento retornado")).toBeInTheDocument();
    expect(screen.queryByText("HGLG11")).not.toBeInTheDocument();
    expect(screen.queryByText("Relatorio mensal HGLG11")).not.toBeInTheDocument();
  });

  it("renderiza documentos carregados com campos da API", async () => {
    const { seenUrls } = installApi({
      documentos: envelope(200, [documentoHglg, documentoSemAtivo], {
        total: 2,
        page: 1,
        page_size: 20,
        has_next: false,
      }),
    });
    renderDocumentos();
    expect((await screen.findAllByText("HGLG11")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Relatorio Gerencial").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Relatorio mensal HGLG11").length).toBeGreaterThan(0);
    expect(screen.getAllByText("SALVO").length).toBeGreaterThan(0);
    expect(seenUrls.some((url) => url.includes("/documentos"))).toBe(true);
  });

  it("documento com ativo exibe ticker", async () => {
    installApi({
      documentos: envelope(200, [documentoHglg], { total: 1, page: 1, page_size: 20 }),
    });
    renderDocumentos();
    expect((await screen.findAllByText("HGLG11")).length).toBeGreaterThan(0);
  });

  it("documento sem ativo nao inventa ticker", async () => {
    installApi({
      documentos: envelope(200, [documentoSemAtivo], { total: 1, page: 1, page_size: 20 }),
    });
    renderDocumentos();
    expect((await screen.findAllByText("Fato sem ticker")).length).toBeGreaterThan(0);
    expect(screen.queryByText("HGLG11")).not.toBeInTheDocument();
    expect(screen.getAllByText("origem AUSENTE").length).toBeGreaterThan(0);
  });

  it("documento com campos opcionais ausentes nao inventa metadados", async () => {
    installApi({
      documentos: envelope(200, [documentoAusente], { total: 1, page: 1, page_size: 20 }),
    });
    renderDocumentos();
    expect(await screen.findByText("assunto AUSENTE")).toBeInTheDocument();
    expect(screen.getAllByText("AUSENTE").length).toBeGreaterThan(0);
    expect(screen.queryByText("Abrir PDF")).not.toBeInTheDocument();
    expect(screen.queryByText("HGLG11")).not.toBeInTheDocument();
  });

  it("abre url_pdf retornada pela API sem construir caminho", async () => {
    installApi({
      documentos: envelope(200, [documentoHglg], { total: 1, page: 1, page_size: 20 }),
    });
    renderDocumentos();
    const links = await screen.findAllByRole("link", { name: "Abrir PDF" });
    expect(links.length).toBeGreaterThan(0);
    expect(links.every((link) => link.getAttribute("href") === "https://drive.example/hglg11.pdf")).toBe(true);
    expect(links.every((link) => link.getAttribute("target") === "_blank")).toBe(true);
  });

  it("erro da API exibe estado de falha", async () => {
    installApi({
      documentos: envelope(500, null, {}, "falha documentos"),
    });
    renderDocumentos();
    expect(await screen.findByText("Falha ao carregar documentos")).toBeInTheDocument();
    expect(screen.getByText("falha documentos")).toBeInTheDocument();
  });

  it("sessao expirada mostra 401", async () => {
    installApi({
      documentos: envelope(401, null, {}, "Nao autenticado."),
    });
    renderDocumentos();
    expect(await screen.findByText("Nao autenticado (401)")).toBeInTheDocument();
    expect(screen.getByText("Sessao invalida ou expirada.")).toBeInTheDocument();
  });

  it("autenticacao envia token e isola usuarios", async () => {
    const first = installApi({
      usuario: usuarioA,
      documentos: envelope(200, [documentoHglg], { total: 1, page: 1, page_size: 20 }),
    });
    renderDocumentos("tok-alice");
    expect((await screen.findAllByText("Relatorio mensal HGLG11")).length).toBeGreaterThan(0);
    expect(first.seenTokens.every((token) => token === "tok-alice" || token === "")).toBe(true);
    cleanup();
    const second = installApi({
      usuario: usuarioB,
      documentos: envelope(200, [], { total: 0, page: 1, page_size: 20 }),
    });
    renderDocumentos("tok-bob");
    expect(await screen.findByText("Nenhum documento retornado")).toBeInTheDocument();
    expect(screen.queryByText("Relatorio mensal HGLG11")).not.toBeInTheDocument();
    expect(second.seenTokens.filter(Boolean).every((token) => token === "tok-bob")).toBe(true);
  });

  it("filtros existentes vao para a API sem logica extra", async () => {
    const { seenUrls } = installApi({
      documentos: (query) => {
        if (query.get("ticker") === "HGLG11") {
          return envelope(200, [documentoHglg], { total: 1, page: 1, page_size: 20 });
        }
        return envelope(200, [documentoHglg, documentoSemAtivo], { total: 2, page: 1, page_size: 20 });
      },
    });
    renderDocumentos();
    expect((await screen.findAllByText("Fato sem ticker")).length).toBeGreaterThan(0);
    fireEvent.change(screen.getByLabelText("Ticker"), { target: { value: "hglg11" } });
    fireEvent.change(screen.getByLabelText("Tipo"), { target: { value: "Relatorio Gerencial" } });
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "salvo" } });
    fireEvent.click(screen.getByText("Filtrar"));
    await waitFor(() =>
      expect(
        seenUrls.some(
          (url) =>
            url.includes("/documentos") &&
            url.includes("ticker=HGLG11") &&
            url.includes("tipo_documento=Relatorio") &&
            url.includes("status=SALVO"),
        ),
      ).toBe(true),
    );
  });
});
