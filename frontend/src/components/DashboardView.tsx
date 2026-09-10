"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "./AuthProvider";
import { AlertsPanel } from "./AlertsPanel";
import { AssetCard } from "./AssetCard";
import { Button } from "./Button";
import { Card } from "./Card";
import { DashboardLoading } from "./SectionState";
import { EmptyState } from "./EmptyState";
import { ErrorState } from "./ErrorState";
import { KpiCard } from "./KpiCard";
import { DataBadge } from "./DataBadge";
import { isUnauthorized, isForbidden } from "@/lib/api";
import { countFromList, loadDashboard, uniqueTickers, type DashboardData } from "@/lib/dashboard";
import { displayCount, displayField, sumPresent } from "@/lib/format";
import { exibirPapel } from "@/lib/rbac";

function freshnessOverview(data: DashboardData): { state: string; hint: string } {
  const statuses: string[] = [];
  for (const asset of data.assets) {
    const categorias = asset.freshness?.categorias || {};
    for (const item of Object.values(categorias)) {
      if (item?.status) {
        statuses.push(item.status.toUpperCase());
      }
    }
  }
  if (data.assets.length === 0) {
    return { state: "AUSENTE", hint: "Sem ativos do usuario para freshness" };
  }
  if (statuses.length === 0) {
    return { state: "AUSENTE", hint: "Freshness nao retornado para os tickers" };
  }
  if (statuses.includes("MISSING")) {
    return { state: "MISSING", hint: "Ao menos uma categoria MISSING" };
  }
  if (statuses.includes("STALE")) {
    return { state: "STALE", hint: "Ao menos uma categoria STALE" };
  }
  if (statuses.every((item) => item === "FRESH")) {
    return { state: "FRESH", hint: "Categorias retornadas como FRESH" };
  }
  return { state: statuses[0], hint: "Estado informado pela API" };
}

export function DashboardView() {
  const { usuario } = useAuth();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<{ code: number; message: string } | null>(null);
  const [data, setData] = useState<DashboardData | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await loadDashboard();
      setData(payload);
    } catch (err) {
      if (isUnauthorized(err)) {
        setError({ code: 401, message: "Sessao invalida ou expirada." });
        return;
      }
      if (isForbidden(err)) {
        setError({ code: 403, message: "Acesso negado ao dashboard." });
        return;
      }
      setError({
        code: 0,
        message: err instanceof Error ? err.message : "Falha ao carregar o dashboard.",
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return <DashboardLoading />;
  }

  if (error?.code === 401) {
    return <ErrorState title="Nao autenticado (401)" detail={error.message} />;
  }
  if (error?.code === 403) {
    return <ErrorState title="Acesso negado (403)" detail={error.message} />;
  }
  if (error || !data) {
    return (
      <div className="space-y-4">
        <ErrorState title="Falha ao carregar dashboard" detail={error?.message} />
        <Button type="button" onClick={() => void load()}>
          Tentar novamente
        </Button>
      </div>
    );
  }

  const acompanhadosCount = countFromList(data.acompanhados, data.acompanhados.kind === "ok" ? data.acompanhados.meta : undefined);
  const carteiraCount = countFromList(data.carteira, data.carteira.kind === "ok" ? data.carteira.meta : undefined);
  const alertasCount =
    data.notificacoesNaoLidas.kind === "ok" ? data.notificacoesNaoLidas.data : null;
  const investidos =
    data.carteira.kind === "ok"
      ? sumPresent(data.carteira.data.map((item) => item.valor_investido))
      : { total: null, used: 0, skipped: 0 };
  const freshness = freshnessOverview(data);
  const tickers = uniqueTickers(data.assets);
  const emptyAssets = data.assets.length === 0;
  const personalForbidden =
    data.carteira.kind === "forbidden" && data.acompanhados.kind === "forbidden";

  return (
    <div className="space-y-8">
      <header className="flex flex-col gap-4 border-b border-olive/10 pb-6 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-[11px] uppercase tracking-[0.24em] text-gold">Estrategia Fardada</p>
          <h1 className="font-display text-3xl text-olive md:text-5xl">Dashboard</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-olive/70">
            Terminal autenticado. Dados exclusivos de /api/v1. Ausencia permanece ausencia.
          </p>
        </div>
        <div className="text-left md:text-right">
          <p className="text-sm text-olive">{usuario?.nome}</p>
          <p className="text-[11px] uppercase tracking-[0.16em] text-olive/50">{usuario?.email}</p>
          <p className="mt-1 text-[11px] uppercase tracking-[0.16em] text-gold">
            {exibirPapel(usuario?.papel || "")}
            {data.plano.kind === "ok" && data.plano.data.plano ? ` · ${data.plano.data.plano}` : ""}
          </p>
        </div>
      </header>

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          eyebrow="Watchlist"
          label="Ativos acompanhados"
          value={displayCount(acompanhadosCount)}
          hint={data.acompanhados.kind === "forbidden" ? "403 carteira pessoal" : "GET /ativos-acompanhados"}
        />
        <KpiCard
          eyebrow="Carteira"
          label="Ativos na carteira"
          value={displayCount(carteiraCount)}
          hint={data.carteira.kind === "forbidden" ? "403 carteira pessoal" : "GET /carteira"}
        />
        <KpiCard
          eyebrow="Inbox"
          label="Notificacoes nao lidas"
          value={displayCount(alertasCount)}
          hint={data.notificacoesNaoLidas.kind === "forbidden" ? "403 inbox" : "GET /notificacoes?nao_lidas=true"}
        />
        <KpiCard
          eyebrow="Capital"
          label="Valor investido"
          value={displayField(investidos.total, null, true)}
          hint={
            data.carteira.kind === "ok"
              ? investidos.skipped
                ? `${investidos.used} posicoes somadas; ${investidos.skipped} AUSENTE`
                : "Soma de valor_investido da API"
              : "Carteira indisponivel"
          }
        />
      </section>

      <section className="grid gap-4 lg:grid-cols-3">
        <Card eyebrow="Dados" title="Freshness" className="lg:col-span-2">
          <div className="flex flex-wrap items-center gap-3">
            <DataBadge state={freshness.state} />
            <p className="text-sm text-olive/70">{freshness.hint}</p>
          </div>
          {data.assets.length > 0 ? (
            <ul className="mt-4 grid gap-2 sm:grid-cols-2">
              {data.assets.slice(0, 8).map((asset) => {
                const categorias = Object.values(asset.freshness?.categorias || {});
                const status = categorias.find((item) => item?.status)?.status || "AUSENTE";
                return (
                  <li key={asset.key} className="flex items-center justify-between border border-olive/10 px-3 py-2">
                    <span className="ticker text-sm text-olive">{asset.ticker || "AUSENTE"}</span>
                    <DataBadge state={status} />
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="mt-4 text-sm text-olive/60">Nenhum ticker do usuario para consultar GET /mercado/freshness.</p>
          )}
        </Card>
        <Card eyebrow="Conta" title="Plano efetivo">
          {data.plano.kind === "ok" ? (
            <div className="space-y-3">
              <p className="ticker text-2xl text-olive">{data.plano.data.plano || "AUSENTE"}</p>
              <p className="text-sm text-olive/70">
                Limite acompanhados:{" "}
                {data.plano.data.limites?.["limite.ativos_acompanhados"] === null
                  ? "ilimitado"
                  : data.plano.data.limites?.["limite.ativos_acompanhados"] ?? "AUSENTE"}
              </p>
              <p className="text-sm text-olive/70">
                Limite carteira:{" "}
                {data.plano.data.limites?.["limite.posicoes_carteira"] === null
                  ? "ilimitado"
                  : data.plano.data.limites?.["limite.posicoes_carteira"] ?? "AUSENTE"}
              </p>
            </div>
          ) : (
            <ErrorState
              title={data.plano.kind === "forbidden" ? "Acesso negado (403)" : "Plano indisponivel"}
              detail={data.plano.message}
            />
          )}
        </Card>
      </section>

      <section className="space-y-4">
        <div>
          <p className="text-[11px] uppercase tracking-[0.22em] text-gold">Posicoes</p>
          <h2 className="font-display text-2xl text-olive">Ativos acompanhados e carteira</h2>
        </div>
        {personalForbidden ? (
          <ErrorState
            title="Acesso negado (403)"
            detail="Este papel nao possui carteira nem watchlist pessoal. O backend permanece a autoridade."
          />
        ) : null}
        {data.carteira.kind === "error" ? (
          <ErrorState title="Falha na carteira" detail={data.carteira.message} />
        ) : null}
        {data.acompanhados.kind === "error" ? (
          <ErrorState title="Falha nos acompanhados" detail={data.acompanhados.message} />
        ) : null}
        {!personalForbidden && emptyAssets ? (
          <EmptyState
            title="Nenhum ativo neste usuario"
            detail="A carteira e o acompanhamento voltaram vazios. O dashboard nao inventa tickers."
          />
        ) : null}
        {data.assets.length > 0 ? (
          <div className="grid gap-4 lg:grid-cols-2">
            {data.assets.map((asset) => (
              <AssetCard key={asset.key} asset={asset} />
            ))}
          </div>
        ) : null}
      </section>

      <AlertsPanel notificacoes={data.notificacoes} alertas={data.alertas} tickers={tickers} />

      <p className="text-[11px] uppercase tracking-[0.18em] text-olive/40">
        Sem serie historica. Sem graficos artificiais. Sem dados mockados.
      </p>
    </div>
  );
}
