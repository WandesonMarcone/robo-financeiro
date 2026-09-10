"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "./Button";
import { CarteiraResumo } from "./CarteiraResumo";
import { EmptyState } from "./EmptyState";
import { ErrorState } from "./ErrorState";
import { Loading } from "./Loading";
import { PosicaoCard } from "./PosicaoCard";
import { PosicaoRow } from "./PosicaoRow";
import { Table } from "./Table";
import { isForbidden, isUnauthorized } from "@/lib/api";
import { loadCarteira, type CarteiraData } from "@/lib/carteira";

const HEADERS = ["Ticker", "Nome", "Quantidade", "Preco medio", "Valor investido", "Mercado / Freshness"];

export function CarteiraLoading() {
  return (
    <div className="space-y-4" role="status">
      <Loading label="Carregando carteira" />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {["kpi-a", "kpi-b", "kpi-c", "kpi-d"].map((key) => (
          <div key={key} className="h-32 animate-pulse border border-olive/10 bg-white" />
        ))}
      </div>
    </div>
  );
}

export function CarteiraView() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<{ code: number; message: string } | null>(null);
  const [data, setData] = useState<CarteiraData | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await loadCarteira();
      setData(payload);
    } catch (err) {
      if (isUnauthorized(err)) {
        setError({ code: 401, message: "Sessao invalida ou expirada." });
        return;
      }
      if (isForbidden(err)) {
        setError({ code: 403, message: "Acesso negado a carteira." });
        return;
      }
      setError({
        code: 0,
        message: err instanceof Error ? err.message : "Falha ao carregar a carteira.",
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading && !data) {
    return <CarteiraLoading />;
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
        <ErrorState title="Falha ao carregar carteira" detail={error.message} />
        <Button type="button" onClick={() => void load()}>
          Tentar novamente
        </Button>
      </div>
    );
  }

  if (!data) {
    return <CarteiraLoading />;
  }

  const forbidden = data.carteira.kind === "forbidden";
  const apiError = data.carteira.kind === "error";
  const empty = data.carteira.kind === "ok" && data.items.length === 0;
  const total = typeof data.meta.total === "number" ? data.meta.total : data.items.length;

  return (
    <div className="space-y-8">
      <header className="flex flex-col gap-4 border-b border-olive/10 pb-6 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-[11px] uppercase tracking-[0.24em] text-gold">Estrategia Fardada</p>
          <h1 className="font-display text-3xl text-olive md:text-5xl">Carteira</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-olive/70">
            Posicoes do usuario autenticado. Valor investido e custo da API, nao patrimonio.
          </p>
        </div>
        <p className="text-[11px] uppercase tracking-[0.16em] text-olive/50">
          GET /carteira · {total} posicoes
        </p>
      </header>

      {loading ? <Loading label="Atualizando carteira" /> : null}

      {forbidden ? (
        <ErrorState
          title="Acesso negado (403)"
          detail={data.carteira.kind === "forbidden" ? data.carteira.message : undefined}
        />
      ) : null}
      {apiError ? (
        <ErrorState
          title="Falha ao carregar carteira"
          detail={data.carteira.kind === "error" ? data.carteira.message : undefined}
        />
      ) : null}
      {data.snapshots.kind === "forbidden" ? (
        <ErrorState title="Acesso negado (403)" detail="GET /mercado/snapshots recusado. Precos nao inventados." />
      ) : null}
      {data.snapshots.kind === "error" ? (
        <ErrorState title="Falha ao carregar mercado" detail={data.snapshots.message} />
      ) : null}

      {data.carteira.kind === "ok" ? <CarteiraResumo data={data} /> : null}

      {empty ? (
        <EmptyState
          title="Carteira vazia"
          detail="GET /carteira nao devolveu posicoes. A tela nao inventa ativos."
        />
      ) : null}

      {data.items.length > 0 ? (
        <>
          <div className="hidden border border-olive/10 bg-white md:block">
            <Table headers={HEADERS}>
              {data.items.map((item) => (
                <PosicaoRow key={item.posicao.id} item={item} />
              ))}
            </Table>
          </div>
          <div className="grid gap-4 md:hidden">
            {data.items.map((item) => (
              <PosicaoCard key={item.posicao.id} item={item} />
            ))}
          </div>
        </>
      ) : null}
    </div>
  );
}
