"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Button } from "./Button";
import { EmptyState } from "./EmptyState";
import { ErrorState } from "./ErrorState";
import { Input } from "./Input";
import { Loading } from "./Loading";
import { Table } from "./Table";
import { AtivoRow } from "./AtivoRow";
import { isForbidden, isUnauthorized } from "@/lib/api";
import { loadAtivosList, normalizeTickerQuery, normalizeTipoQuery, type AtivosListData } from "@/lib/ativos";

const HEADERS = ["Ticker", "Tipo", "Preco", "Indicadores", "Coleta", "Vinculo"];

export function AtivosLoading() {
  return (
    <div className="space-y-4" role="status">
      <Loading label="Carregando ativos" />
      <div className="h-48 animate-pulse border border-olive/10 bg-white" />
    </div>
  );
}

export function AtivosView() {
  const [draftTicker, setDraftTicker] = useState("");
  const [draftTipo, setDraftTipo] = useState("");
  const [ticker, setTicker] = useState<string | undefined>(undefined);
  const [tipo, setTipo] = useState<string | undefined>(undefined);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<{ code: number; message: string } | null>(null);
  const [data, setData] = useState<AtivosListData | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await loadAtivosList({ ticker, tipo, page });
      setData(payload);
    } catch (err) {
      if (isUnauthorized(err)) {
        setError({ code: 401, message: "Sessao invalida ou expirada." });
        return;
      }
      if (isForbidden(err)) {
        setError({ code: 403, message: "Acesso negado aos ativos." });
        return;
      }
      setError({
        code: 0,
        message: err instanceof Error ? err.message : "Falha ao carregar ativos.",
      });
    } finally {
      setLoading(false);
    }
  }, [ticker, tipo, page]);

  useEffect(() => {
    void load();
  }, [load]);

  function onSearch(event: FormEvent) {
    event.preventDefault();
    setPage(1);
    setTicker(normalizeTickerQuery(draftTicker));
    setTipo(normalizeTipoQuery(draftTipo));
  }

  function onClear() {
    setDraftTicker("");
    setDraftTipo("");
    setTicker(undefined);
    setTipo(undefined);
    setPage(1);
  }

  if (loading && !data) {
    return <AtivosLoading />;
  }

  if (error?.code === 401) {
    return <ErrorState title="Nao autenticado (401)" detail={error.message} />;
  }
  if (error?.code === 403) {
    return <ErrorState title="Acesso negado (403)" detail={error.message} />;
  }
  if (error && !data) {
    return (
      <div className="space-y-4">
        <ErrorState title="Falha ao carregar ativos" detail={error.message} />
        <Button type="button" onClick={() => void load()}>
          Tentar novamente
        </Button>
      </div>
    );
  }

  const forbidden = data?.ativos.kind === "forbidden";
  const apiError = data?.ativos.kind === "error";
  const empty = data?.ativos.kind === "ok" && data.items.length === 0;
  const total = typeof data?.meta.total === "number" ? data.meta.total : data?.items.length || 0;
  const hasNext = Boolean(data?.meta.has_next);
  const currentPage = typeof data?.meta.page === "number" ? data.meta.page : page;

  return (
    <div className="space-y-8">
      <header className="flex flex-col gap-4 border-b border-olive/10 pb-6 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-[11px] uppercase tracking-[0.24em] text-gold">Estrategia Fardada</p>
          <h1 className="font-display text-3xl text-olive md:text-5xl">Ativos</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-olive/70">
            Catalogo autenticado. Pesquisa por ticker e igualdade exata da API. Ausencia permanece ausencia.
          </p>
        </div>
        <p className="text-[11px] uppercase tracking-[0.16em] text-olive/50">
          GET /ativos · {total} retornados
        </p>
      </header>

      <form onSubmit={onSearch} className="grid gap-4 border border-olive/10 bg-white p-4 md:grid-cols-[1fr_10rem_auto_auto] md:items-end">
        <Input
          label="Ticker"
          name="ticker"
          value={draftTicker}
          onChange={(event) => setDraftTicker(event.target.value)}
          placeholder="Igualdade exata, ex. PETR4"
          autoComplete="off"
        />
        <label className="block space-y-1.5" htmlFor="tipo">
          <span className="text-[11px] uppercase tracking-[0.18em] text-olive/70">Tipo</span>
          <select
            id="tipo"
            name="tipo"
            value={draftTipo}
            onChange={(event) => setDraftTipo(event.target.value)}
            className="w-full border border-olive/20 bg-white px-3 py-2 text-sm text-ink outline-none focus:border-gold"
          >
            <option value="">Todos</option>
            <option value="ACAO">ACAO</option>
            <option value="FII">FII</option>
          </select>
        </label>
        <Button type="submit">Pesquisar</Button>
        <Button type="button" variant="ghost" onClick={onClear}>
          Limpar
        </Button>
      </form>

      {loading ? <Loading label="Atualizando listagem" /> : null}

      {forbidden ? (
        <ErrorState title="Acesso negado (403)" detail={data?.ativos.kind === "forbidden" ? data.ativos.message : undefined} />
      ) : null}
      {apiError ? (
        <ErrorState title="Falha ao carregar ativos" detail={data?.ativos.kind === "error" ? data.ativos.message : undefined} />
      ) : null}
      {data?.snapshots.kind === "forbidden" ? (
        <ErrorState title="Acesso negado (403)" detail="GET /mercado/snapshots recusado. Precos nao inventados." />
      ) : null}
      {data?.carteira.kind === "forbidden" || data?.acompanhados.kind === "forbidden" ? (
        <ErrorState title="Acesso negado (403)" detail="Vinculo de carteira/acompanhamento pessoal indisponivel neste papel." />
      ) : null}
      {empty ? (
        <EmptyState
          title="Nenhum ativo retornado"
          detail={
            ticker
              ? `GET /ativos?ticker=${ticker} nao encontrou igualdade exata.`
              : "A API devolveu lista vazia. A tela nao inventa tickers."
          }
        />
      ) : null}

      {data && data.items.length > 0 ? (
        <div className="border border-olive/10 bg-white">
          <Table headers={HEADERS}>
            {data.items.map((item) => (
              <AtivoRow key={item.ativo.id} item={item} />
            ))}
          </Table>
        </div>
      ) : null}

      {data && data.ativos.kind === "ok" && total > 0 ? (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-[11px] uppercase tracking-[0.14em] text-olive/50">
            Pagina {currentPage} · page_size {data.meta.page_size ?? 20}
          </p>
          <div className="flex gap-2">
            <Button type="button" variant="ghost" disabled={currentPage <= 1} onClick={() => setPage(Math.max(1, currentPage - 1))}>
              Anterior
            </Button>
            <Button type="button" variant="ghost" disabled={!hasNext} onClick={() => setPage(currentPage + 1)}>
              Proxima
            </Button>
          </div>
        </div>
      ) : null}

      <p className="text-[11px] uppercase tracking-[0.18em] text-olive/40">
        Sem busca aproximada. Sem serie historica. Sem dados mockados.
      </p>
    </div>
  );
}
