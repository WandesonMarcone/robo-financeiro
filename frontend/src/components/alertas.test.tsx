import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "./AuthProvider";
import { AlertasView } from "./AlertasView";
import { setSessionToken } from "@/lib/session";

const nav = vi.hoisted(() => ({
  pathname: "/alertas",
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

const notificacaoAlice = {
  id: 51,
  tipo: "ALERTA_MERCADO",
  titulo: "Movimento HGLG11",
  mensagem: "Variacao relevante",
  ativo_id: 101,
  ticker: "HGLG11",
  canal: "WEB",
  status: "PENDENTE",
  dados: { prioridade: "ALTO", indicador: "preco", freshness: "FRESH" },
  criado_em: "2026-09-10T10:00:00",
  lida_em: null,
  tentativas: 0,
  enviada_em: null,
};

const notificacaoLida = {
  ...notificacaoAlice,
  id: 52,
  titulo: "Dividendo HGLG11",
  tipo: "DIVIDENDO",
  dados: { prioridade: "BAIXA" },
  status: "LIDA",
  lida_em: "2026-09-11T10:00:00",
};

const notificacaoAusente = {
  id: 53,
  tipo: null,
  titulo: null,
  mensagem: null,
  ativo_id: null,
  ticker: null,
  canal: null,
  status: null,
  dados: null,
  criado_em: null,
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

const alertaCritico = {
  ...alertaHglg,
  id: 62,
  tipo_alerta: "CRITICO",
  severidade: "CRITICO",
  motivo: "Quebra de regra critica",
  ticker: "PETR4",
  tipo_ativo: "ACAO",
  ativo_id: 202,
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

type Scenario = {
  usuario?: typeof usuarioA;
  me?: ReturnType<typeof envelope>;
  notificacoes?: ReturnType<typeof envelope>;
  naoLidas?: ReturnType<typeof envelope>;
  alertas?: ReturnType<typeof envelope>;
  preferencias?: ReturnType<typeof envelope>;
  lida?: ReturnType<typeof envelope>;
  lerTodas?: ReturnType<typeof envelope>;
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
    const method = String(init?.method || "GET").toUpperCase();
    if (path.endsWith("/me") && !path.endsWith("/me/plano")) {
      return scenario.me || envelope(200, scenario.usuario || usuarioA);
    }
    if (path.endsWith("/notificacoes/ler-todas") && method === "POST") {
      return scenario.lerTodas || envelope(200, { marcadas: 1 }, { total: 1 });
    }
    if (path.match(/\/notificacoes\/\d+\/lida$/) && method === "POST") {
      return (
        scenario.lida ||
        envelope(200, { ...notificacaoAlice, lida_em: "2026-09-12T10:00:00", status: "LIDA" }, { lida: true })
      );
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
    return envelope(404, null, {}, "nao encontrado");
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, seenTokens, seenUrls };
}

function renderAlertas(token = "tok-alice") {
  setSessionToken(token);
  return render(
    <AuthProvider>
      <AlertasView />
    </AuthProvider>,
  );
}

describe("area de alertas 11.8", () => {
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
    renderAlertas();
    expect(await screen.findByText("Carregando alertas")).toBeInTheDocument();
    release();
    await waitFor(() => expect(screen.queryByText("Carregando alertas")).not.toBeInTheDocument());
  });

  it("lista vazia nao inventa alerta", async () => {
    installApi({
      notificacoes: envelope(200, [], { total: 0 }),
      naoLidas: envelope(200, [], { total: 0 }),
      alertas: envelope(200, [], { total: 0 }),
    });
    renderAlertas();
    expect(await screen.findByText("Nenhuma notificacao")).toBeInTheDocument();
    expect(screen.getByText("Nenhum alerta de mercado")).toBeInTheDocument();
    expect(screen.queryByText("HGLG11")).not.toBeInTheDocument();
    expect(screen.queryByText("Movimento HGLG11")).not.toBeInTheDocument();
  });

  it("renderiza alertas recentes com campos da API", async () => {
    const { seenUrls } = installApi({
      notificacoes: envelope(200, [notificacaoAlice, notificacaoLida], { total: 2 }),
      naoLidas: envelope(200, [notificacaoAlice], { total: 1 }),
      alertas: envelope(200, [alertaHglg, alertaCritico], { total: 2 }),
    });
    renderAlertas();
    expect((await screen.findAllByText("HGLG11")).length).toBeGreaterThan(0);
    expect(screen.getByText("Movimento HGLG11")).toBeInTheDocument();
    expect(screen.getByText("Variacao acima do limiar")).toBeInTheDocument();
    expect(screen.getByText("ALERTA_MERCADO")).toBeInTheDocument();
    expect(screen.getByText("ALTO")).toBeInTheDocument();
    expect(screen.getByText("NAO_LIDA")).toBeInTheDocument();
    expect(screen.getByText("LIDA")).toBeInTheDocument();
    expect(screen.getByText("FRESH")).toBeInTheDocument();
    expect(screen.getAllByText((text) => text.includes("motor")).length).toBeGreaterThan(0);
    expect(seenUrls.some((url) => url.includes("/notificacoes") && url.includes("nao_lidas=true"))).toBe(true);
    expect(seenUrls.some((url) => url.includes("/alertas"))).toBe(true);
    expect(seenUrls.some((url) => url.includes("/preferencias"))).toBe(true);
  });

  it("diferencia alerta critico e informativo", async () => {
    installApi({
      notificacoes: envelope(200, [notificacaoAlice, notificacaoLida], { total: 2 }),
      naoLidas: envelope(200, [notificacaoAlice], { total: 1 }),
      alertas: envelope(200, [alertaHglg, alertaCritico], { total: 2 }),
    });
    renderAlertas();
    expect(await screen.findByText("Quebra de regra critica")).toBeInTheDocument();
    expect(screen.getAllByText("CRITICO").length).toBeGreaterThan(0);
    expect(screen.getByText("WARNING")).toBeInTheDocument();
    expect(screen.getByText("MERCADO")).toBeInTheDocument();
  });

  it("mostra dados ausentes sem inventar ticker", async () => {
    installApi({
      notificacoes: envelope(200, [notificacaoAusente], { total: 1 }),
      naoLidas: envelope(200, [notificacaoAusente], { total: 1 }),
      alertas: envelope(200, [{ ...alertaHglg, ticker: null, indicador: null, origem: null, data_evento: null }], { total: 1 }),
    });
    renderAlertas();
    expect(await screen.findByText("titulo AUSENTE")).toBeInTheDocument();
    expect(screen.getByText("mensagem AUSENTE")).toBeInTheDocument();
    expect(screen.getByText("indicador AUSENTE")).toBeInTheDocument();
    expect(screen.getByText("data AUSENTE")).toBeInTheDocument();
    expect(screen.queryByText("HGLG11")).not.toBeInTheDocument();
  });

  it("erro da API exibe estado de falha", async () => {
    installApi({
      notificacoes: envelope(500, null, {}, "falha inbox"),
      naoLidas: envelope(500, null, {}, "falha inbox"),
      alertas: envelope(500, null, {}, "falha mercado"),
    });
    renderAlertas();
    expect(await screen.findByText("Falha ao carregar notificacoes")).toBeInTheDocument();
    expect(screen.getByText("Falha ao carregar alertas")).toBeInTheDocument();
  });

  it("sessao expirada mostra 401", async () => {
    installApi({
      notificacoes: envelope(401, null, {}, "Não autenticado."),
    });
    renderAlertas();
    expect(await screen.findByText("Nao autenticado (401)")).toBeInTheDocument();
    expect(screen.getByText("Sessao invalida ou expirada.")).toBeInTheDocument();
  });

  it("autenticacao envia token e isola usuarios", async () => {
    const first = installApi({
      usuario: usuarioA,
      notificacoes: envelope(200, [notificacaoAlice], { total: 1 }),
      naoLidas: envelope(200, [notificacaoAlice], { total: 1 }),
      alertas: envelope(200, [alertaHglg], { total: 1 }),
    });
    renderAlertas("tok-alice");
    expect(await screen.findByText("Movimento HGLG11")).toBeInTheDocument();
    expect(first.seenTokens.every((token) => token === "tok-alice" || token === "")).toBe(true);
    cleanup();
    const second = installApi({
      usuario: usuarioB,
      notificacoes: envelope(200, [], { total: 0 }),
      naoLidas: envelope(200, [], { total: 0 }),
      alertas: envelope(200, [], { total: 0 }),
    });
    renderAlertas("tok-bob");
    expect(await screen.findByText("Nenhuma notificacao")).toBeInTheDocument();
    expect(screen.queryByText("Movimento HGLG11")).not.toBeInTheDocument();
    expect(second.seenTokens.filter(Boolean).every((token) => token === "tok-bob")).toBe(true);
  });

  it("marca como lida pelo endpoint existente", async () => {
    const { seenUrls } = installApi({
      notificacoes: envelope(200, [notificacaoAlice], { total: 1 }),
      naoLidas: envelope(200, [notificacaoAlice], { total: 1 }),
      alertas: envelope(200, [], { total: 0 }),
    });
    renderAlertas();
    expect(await screen.findByText("NAO_LIDA")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Marcar como lida"));
    await waitFor(() => expect(screen.getByText("LIDA")).toBeInTheDocument());
    expect(seenUrls.some((url) => url.includes("/notificacoes/51/lida"))).toBe(true);
  });
});
