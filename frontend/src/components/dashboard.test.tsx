import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "./AuthProvider";
import { DashboardView } from "./DashboardView";
import { setSessionToken } from "@/lib/session";

const nav = vi.hoisted(() => ({
  pathname: "/dashboard",
  replace: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace, push: vi.fn() }),
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
    dy: { semantica: "PRESENTE", unidade: "%", escala: "fracao", aplicavel: true },
    pvp: { semantica: "PRESENTE", unidade: "x", escala: "multiplo", aplicavel: true },
    vpa: { semantica: "AUSENTE", unidade: "R$", escala: "monetario", aplicavel: true },
  },
};

const indicadorHglg = {
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
};

const notificacaoAlice = {
  id: 51,
  tipo: "ALERTA",
  titulo: "Movimento HGLG11",
  mensagem: "Variacao relevante",
  ativo_id: 101,
  ticker: "HGLG11",
  canal: "web",
  status: "PENDENTE",
  dados: { prioridade: "ALTO" },
  criado_em: "2026-09-10T10:00:00",
  lida_em: null,
  tentativas: 0,
  enviada_em: null,
};

const alertaHglg = {
  id: 61,
  tipo_alerta: "MERCADO",
  tipo_ativo: "FII",
  ativo_id: 101,
  ticker: "HGLG11",
  indicador: "preco",
  valor_anterior: 150,
  valor_atual: 160.5,
  variacao_percentual: 7,
  regra: "preco",
  motivo: "Variacao acima do limiar",
  severidade: "WARNING",
  recomendacao: null,
  origem: "motor",
  data_referencia: "2026-09-01",
  data_evento: "2026-09-10T10:00:00",
  telegram_enviado: false,
};

const alertaPetr = {
  ...alertaHglg,
  id: 62,
  ticker: "PETR4",
  tipo_ativo: "ACAO",
  ativo_id: 202,
  motivo: "Alerta de terceiro",
};

const planoFree = {
  plano: "FREE",
  entitlements: [],
  limites: { "limite.ativos_acompanhados": 10, "limite.posicoes_carteira": 5 },
};

const preferencias = {
  notificacoes_ativas: true,
  notificacoes_preco: true,
  notificacoes_dividendos: true,
  notificacoes_resultados: true,
  notificacoes_documentos: true,
  notificacoes_alertas: true,
  frequencia_notificacoes: "imediata",
  telegram_ativo: false,
  web_ativo: true,
  relatorios_ativos: false,
  frequencia_relatorios: "desativada",
  mercado_acoes: true,
  mercado_fiis: true,
  criado_em: null,
  atualizado_em: null,
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
  plano?: ReturnType<typeof envelope>;
  carteira?: ReturnType<typeof envelope>;
  acompanhados?: ReturnType<typeof envelope>;
  notificacoes?: ReturnType<typeof envelope>;
  naoLidas?: ReturnType<typeof envelope>;
  alertas?: ReturnType<typeof envelope>;
  preferencias?: ReturnType<typeof envelope>;
  snapshots?: ReturnType<typeof envelope>;
  indicadores?: ReturnType<typeof envelope>;
  freshness?: ReturnType<typeof envelope>;
};

function installApi(scenario: Scenario) {
  const seenTokens: string[] = [];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const headers = new Headers(init?.headers);
    seenTokens.push(headers.get("X-Session-Token") || "");
    const path = pathOf(url);
    const query = queryOf(url);
    if (path.endsWith("/me") && !path.endsWith("/me/plano")) {
      return scenario.me || envelope(200, scenario.usuario || usuarioA);
    }
    if (path.endsWith("/me/plano")) {
      return scenario.plano || envelope(200, planoFree);
    }
    if (path.endsWith("/carteira")) {
      return scenario.carteira || envelope(200, [], { total: 0 });
    }
    if (path.endsWith("/ativos-acompanhados")) {
      return scenario.acompanhados || envelope(200, [], { total: 0 });
    }
    if (path.endsWith("/notificacoes")) {
      if (query.get("nao_lidas") === "true") {
        return scenario.naoLidas || envelope(200, [], { total: 0 });
      }
      return scenario.notificacoes || envelope(200, [], { total: 0 });
    }
    if (path.endsWith("/alertas")) {
      return scenario.alertas || envelope(200, [], { total: 0 });
    }
    if (path.endsWith("/preferencias")) {
      return scenario.preferencias || envelope(200, preferencias);
    }
    if (path.endsWith("/mercado/snapshots")) {
      return scenario.snapshots || envelope(200, [], { total: 0 });
    }
    if (path.endsWith("/indicadores")) {
      return scenario.indicadores || envelope(200, [], { total: 0 });
    }
    if (path.endsWith("/mercado/freshness")) {
      return scenario.freshness || envelope(404, null, {}, "Ativo não encontrado para freshness.");
    }
    return envelope(404, null, {}, "nao encontrado");
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, seenTokens };
}

function renderDashboard(token = "tok-alice") {
  setSessionToken(token);
  return render(
    <AuthProvider>
      <DashboardView />
    </AuthProvider>,
  );
}

describe("dashboard autenticado", () => {
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
        if (path.endsWith("/me/plano")) {
          return envelope(200, planoFree);
        }
        if (path.endsWith("/preferencias")) {
          return envelope(200, preferencias);
        }
        return envelope(200, [], { total: 0 });
      }),
    );
    renderDashboard();
    expect(await screen.findByText("Carregando dashboard")).toBeInTheDocument();
    release();
    await waitFor(() => expect(screen.queryByText("Carregando dashboard")).not.toBeInTheDocument());
  });

  it("usuario sem ativos mostra empty e nao inventa ticker", async () => {
    installApi({
      carteira: envelope(200, [], { total: 0 }),
      acompanhados: envelope(200, [], { total: 0 }),
      notificacoes: envelope(200, [], { total: 0 }),
      naoLidas: envelope(200, [], { total: 0 }),
      alertas: envelope(200, [alertaPetr], { total: 1 }),
    });
    renderDashboard();
    expect(await screen.findByText("Nenhum ativo neste usuario")).toBeInTheDocument();
    expect(screen.queryByText("HGLG11")).not.toBeInTheDocument();
    expect(screen.queryByText("PETR4")).not.toBeInTheDocument();
    expect(screen.getByText("Sem escopo de ativos")).toBeInTheDocument();
    expect(screen.getAllByText("0").length).toBeGreaterThan(0);
    expect(screen.queryByText("R$ 0,00")).not.toBeInTheDocument();
  });

  it("usuario com ativos consome dados reais da API", async () => {
    const { fetchMock } = installApi({
      carteira: envelope(200, [posicaoAlice], { total: 1 }),
      acompanhados: envelope(200, [acompanhamentoAlice], { total: 1 }),
      notificacoes: envelope(200, [notificacaoAlice], { total: 1 }),
      naoLidas: envelope(200, [notificacaoAlice], { total: 1 }),
      alertas: envelope(200, [alertaHglg, alertaPetr], { total: 2 }),
      snapshots: envelope(200, [snapshotHglg], { total: 1 }),
      indicadores: envelope(200, [indicadorHglg], { total: 1 }),
      freshness: freshnessOk(),
    });
    renderDashboard();
    expect((await screen.findAllByText("HGLG11")).length).toBeGreaterThan(0);
    expect(await screen.findByText("Movimento HGLG11")).toBeInTheDocument();
    expect(screen.getByText("Variacao acima do limiar")).toBeInTheDocument();
    expect(screen.queryByText("Alerta de terceiro")).not.toBeInTheDocument();
    expect(screen.getByText("vacancia_fisica")).toBeInTheDocument();
    expect(screen.getAllByText("AUSENTE").length).toBeGreaterThan(0);
    const urls = fetchMock.mock.calls.map((call) => String(call[0]));
    expect(urls.some((url) => url.startsWith("/api/v1/carteira"))).toBe(true);
    expect(urls.some((url) => url.startsWith("/api/v1/ativos-acompanhados"))).toBe(true);
    expect(urls.some((url) => url.startsWith("/api/v1/notificacoes"))).toBe(true);
    expect(urls.some((url) => url.startsWith("/api/v1/alertas"))).toBe(true);
    expect(urls.some((url) => url.startsWith("/api/v1/mercado/snapshots"))).toBe(true);
    expect(urls.every((url) => !url.toLowerCase().includes("token="))).toBe(true);
  });

  it("erro da API mostra estado de erro", async () => {
    installApi({
      carteira: envelope(500, null, {}, "Erro interno do servidor."),
      acompanhados: envelope(200, [], { total: 0 }),
    });
    renderDashboard();
    expect(await screen.findByText("Falha na carteira")).toBeInTheDocument();
    expect(screen.getByText("Erro interno do servidor.")).toBeInTheDocument();
  });

  it("401 no dashboard exibe nao autenticado", async () => {
    installApi({
      carteira: envelope(401, null, {}, "Não autenticado."),
    });
    renderDashboard();
    expect(await screen.findByText("Nao autenticado (401)")).toBeInTheDocument();
  });

  it("403 de recursos pessoais preserva a tela e informa acesso negado", async () => {
    installApi({
      usuario: { ...usuarioA, papel: "ADMIN", nome: "Operador" },
      carteira: envelope(403, null, {}, "Acesso negado."),
      acompanhados: envelope(403, null, {}, "Acesso negado."),
      notificacoes: envelope(403, null, {}, "Acesso negado."),
      naoLidas: envelope(403, null, {}, "Acesso negado."),
      preferencias: envelope(403, null, {}, "Acesso negado."),
      alertas: envelope(200, [alertaPetr], { total: 1 }),
    });
    renderDashboard();
    expect((await screen.findAllByText("Acesso negado (403)")).length).toBeGreaterThan(0);
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(sessionStorage.getItem("ef_session_token")).toBe("tok-alice");
  });

  it("isolamento: cada sessao envia o proprio X-Session-Token", async () => {
    const { seenTokens } = installApi({
      carteira: envelope(200, [posicaoAlice], { total: 1 }),
      acompanhados: envelope(200, [], { total: 0 }),
      snapshots: envelope(200, [snapshotHglg], { total: 1 }),
      indicadores: envelope(200, [], { total: 0 }),
      freshness: freshnessOk(),
    });
    renderDashboard("tok-alice");
    await screen.findAllByText("HGLG11");
    expect(seenTokens.every((token) => token === "tok-alice" || token === "")).toBe(true);
    expect(seenTokens.some((token) => token === "tok-alice")).toBe(true);
    expect(seenTokens.some((token) => token === "tok-bob")).toBe(false);
    expect(usuarioB.email).toBe("bob@x.com");
  });

  it("ausencia de indicadores nao vira zero", async () => {
    installApi({
      carteira: envelope(200, [posicaoAlice], { total: 1 }),
      acompanhados: envelope(200, [], { total: 0 }),
      snapshots: envelope(200, [{ ...snapshotHglg, preco: null, dy: null, pvp: null, vpa: null, campos: {
        preco: { semantica: "AUSENTE", unidade: "R$", escala: "monetario", aplicavel: true },
        dy: { semantica: "AUSENTE", unidade: "%", escala: "fracao", aplicavel: true },
        pvp: { semantica: "AUSENTE", unidade: "x", escala: "multiplo", aplicavel: true },
        vpa: { semantica: "AUSENTE", unidade: "R$", escala: "monetario", aplicavel: true },
      } }], { total: 1 }),
      indicadores: envelope(200, [], { total: 0 }),
      freshness: envelope(200, {
        ticker: "HGLG11",
        tipo: "FII",
        categorias: {},
      }),
    });
    renderDashboard();
    expect((await screen.findAllByText("HGLG11")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("AUSENTE").length).toBeGreaterThan(0);
    expect(screen.queryByText("R$ 0,00")).not.toBeInTheDocument();
  });
});
