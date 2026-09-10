"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Badge } from "./Badge";
import { Button } from "./Button";
import { Card } from "./Card";
import { DataBadge } from "./DataBadge";
import { EmptyState } from "./EmptyState";
import { ErrorState } from "./ErrorState";
import { Loading } from "./Loading";
import { isForbidden, isUnauthorized } from "@/lib/api";
import {
  campoDoSnapshot,
  freshnessSummary,
  isMoneySnapshotField,
  loadAtivoDetalhe,
  snapshotFieldKeys,
  type AtivoDetailData,
} from "@/lib/ativos";
import { displayField, formatDate } from "@/lib/format";
import type { SnapshotMercado } from "@/lib/types";

export function AtivoDetalheLoading() {
  return (
    <div className="space-y-4" role="status">
      <Loading label="Carregando ativo" />
      <div className="h-64 animate-pulse border border-olive/10 bg-white" />
    </div>
  );
}

function ProvenienciaBlock({ snapshot }: { snapshot: SnapshotMercado }) {
  const proveniencia = snapshot.proveniencia;
  if (!proveniencia || Object.keys(proveniencia).length === 0) {
    return <p className="text-sm text-olive/60">Proveniencia AUSENTE neste snapshot.</p>;
  }
  return (
    <ul className="space-y-2">
      {Object.entries(proveniencia).map(([campo, origem]) => (
        <li key={campo} className="text-sm text-olive/80">
          <span className="ticker text-xs text-olive">{campo}</span>
          <span className="ml-2">{origem}</span>
        </li>
      ))}
    </ul>
  );
}

export function AtivoDetalheView({ ticker }: { ticker: string }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<{ code: number; message: string } | null>(null);
  const [data, setData] = useState<AtivoDetailData | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await loadAtivoDetalhe(ticker);
      setData(payload);
    } catch (err) {
      if (isUnauthorized(err)) {
        setError({ code: 401, message: "Sessao invalida ou expirada." });
        return;
      }
      if (isForbidden(err)) {
        setError({ code: 403, message: "Acesso negado ao detalhe do ativo." });
        return;
      }
      setError({
        code: 0,
        message: err instanceof Error ? err.message : "Falha ao carregar o ativo.",
      });
    } finally {
      setLoading(false);
    }
  }, [ticker]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return <AtivoDetalheLoading />;
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
        <ErrorState title="Falha ao carregar ativo" detail={error?.message} />
        <Button type="button" onClick={() => void load()}>
          Tentar novamente
        </Button>
      </div>
    );
  }

  if (data.ativo.kind === "forbidden") {
    return <ErrorState title="Acesso negado (403)" detail={data.ativo.message} />;
  }
  if (data.ativo.kind === "error") {
    return (
      <div className="space-y-4">
        <ErrorState title="Falha ao carregar ativo" detail={data.ativo.message} />
        <Button type="button" onClick={() => void load()}>
          Tentar novamente
        </Button>
      </div>
    );
  }
  if (data.ativo.kind === "absent" || !data.ativo.data) {
    return (
      <div className="space-y-4">
        <EmptyState
          title="Ativo inexistente"
          detail={`GET /ativos?ticker=${data.ticker || ticker} nao retornou cadastro.`}
        />
        <Link href="/ativos" className="inline-flex border border-olive/20 px-4 py-2 text-sm text-olive">
          Voltar aos ativos
        </Link>
      </div>
    );
  }

  const ativo = data.ativo.data;
  const snapshot = data.snapshot.kind === "ok" ? data.snapshot.data : null;
  const freshness = freshnessSummary(data.freshness);
  const snapshotKeys = snapshotFieldKeys(snapshot);
  const indicadores = data.indicadores.kind === "ok" ? data.indicadores.data : [];

  return (
    <div className="space-y-8">
      <header className="flex flex-col gap-4 border-b border-olive/10 pb-6 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-[11px] uppercase tracking-[0.24em] text-gold">Estrategia Fardada</p>
          <p className="mt-2 text-sm">
            <Link href="/ativos" className="text-olive/60 hover:text-gold">
              Ativos
            </Link>
            <span className="mx-2 text-olive/30">/</span>
            <span className="text-olive">{ativo.ticker}</span>
          </p>
          <h1 className="ticker mt-2 text-4xl text-olive md:text-6xl">{ativo.ticker || "AUSENTE"}</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-olive/70">
            Detalhe montado com GET /ativos, /mercado/snapshots/mais-recente, /indicadores e /mercado/freshness.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          {ativo.tipo ? <Badge tone="olive">{ativo.tipo}</Badge> : <DataBadge state="AUSENTE" />}
          <DataBadge state={freshness.state} />
          {data.naCarteira ? <Badge tone="gold">Carteira</Badge> : null}
          {data.acompanhado ? <Badge tone="olive">Acompanhado</Badge> : null}
        </div>
      </header>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card eyebrow="Cadastro" title="Identidade">
          <dl className="space-y-3 text-sm text-olive/80">
            <div>
              <dt className="text-[11px] uppercase tracking-[0.16em] text-olive/45">Ticker</dt>
              <dd className="ticker text-xl text-olive">{ativo.ticker || "AUSENTE"}</dd>
            </div>
            <div>
              <dt className="text-[11px] uppercase tracking-[0.16em] text-olive/45">Tipo</dt>
              <dd>{ativo.tipo || "AUSENTE"}</dd>
            </div>
            <div>
              <dt className="text-[11px] uppercase tracking-[0.16em] text-olive/45">CNPJ</dt>
              <dd>{ativo.cnpj || "AUSENTE"}</dd>
            </div>
            <div>
              <dt className="text-[11px] uppercase tracking-[0.16em] text-olive/45">Setor</dt>
              <dd>{ativo.setor || "AUSENTE"}</dd>
            </div>
            <div>
              <dt className="text-[11px] uppercase tracking-[0.16em] text-olive/45">Tipo FII</dt>
              <dd>{ativo.tipo_fii || "AUSENTE"}</dd>
            </div>
          </dl>
        </Card>
        <Card eyebrow="Mercado" title="Preco">
          {data.snapshot.kind === "forbidden" ? (
            <ErrorState title="Acesso negado (403)" detail={data.snapshot.message} />
          ) : data.snapshot.kind === "error" ? (
            <ErrorState title="Falha no snapshot" detail={data.snapshot.message} />
          ) : data.snapshot.kind === "absent" || !snapshot ? (
            <EmptyState title="Snapshot ausente" detail="GET /mercado/snapshots/mais-recente nao retornou cotacao." />
          ) : (
            (() => {
              const preco = displayField(snapshot.preco, campoDoSnapshot(snapshot, "preco"), true);
              return (
                <div className="space-y-3">
                  <p className="ticker text-3xl text-olive">{preco.text}</p>
                  <DataBadge state={preco.kind} />
                  <p className="text-sm text-olive/70">Referencia {formatDate(snapshot.data_referencia) || "AUSENTE"}</p>
                  <p className="text-sm text-olive/70">Coleta {formatDate(snapshot.data_coleta) || "AUSENTE"}</p>
                  <p className="text-sm text-olive/70">Fonte {snapshot.fonte || "AUSENTE"}</p>
                </div>
              );
            })()
          )}
        </Card>
        <Card eyebrow="Dados" title="Freshness">
          {data.freshness.kind === "forbidden" ? (
            <ErrorState title="Acesso negado (403)" detail={data.freshness.message} />
          ) : data.freshness.kind === "error" ? (
            <ErrorState title="Falha no freshness" detail={data.freshness.message} />
          ) : data.freshness.kind === "absent" || !data.freshness.data ? (
            <EmptyState title="Freshness ausente" detail="GET /mercado/freshness nao retornou categorias." />
          ) : (
            <div className="space-y-3">
              <DataBadge state={freshness.state} />
              <ul className="space-y-2">
                {Object.entries(data.freshness.data.categorias || {}).map(([nome, categoria]) => (
                  <li key={nome} className="flex items-center justify-between gap-2 border border-olive/10 px-3 py-2">
                    <span className="text-sm text-olive/70">{categoria?.categoria || nome}</span>
                    <span className="flex items-center gap-2">
                      <span className="text-[11px] uppercase tracking-[0.12em] text-olive/45">
                        {formatDate(categoria?.data_coleta) || "AUSENTE"}
                      </span>
                      <DataBadge state={categoria?.status || "AUSENTE"} />
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Card>
        <Card eyebrow="Usuario" title="Vinculo">
          {data.carteira.kind === "forbidden" && data.acompanhados.kind === "forbidden" ? (
            <ErrorState title="Acesso negado (403)" detail="Carteira e acompanhamento pessoais indisponiveis neste papel." />
          ) : (
            <div className="space-y-3">
              <p className="text-sm text-olive/80">
                Carteira: {data.naCarteira ? "sim" : data.carteira.kind === "forbidden" ? "403" : "nao informado neste usuario"}
              </p>
              <p className="text-sm text-olive/80">
                Acompanhado: {data.acompanhado ? "sim" : data.acompanhados.kind === "forbidden" ? "403" : "nao informado neste usuario"}
              </p>
              {data.posicao ? (
                <p className="text-sm text-olive/70">
                  Quantidade {displayField(data.posicao.quantidade).text} · investido{" "}
                  {displayField(data.posicao.valor_investido, null, true).text}
                </p>
              ) : null}
            </div>
          )}
        </Card>
      </section>

      <Card eyebrow="Mercado" title="Indicadores do snapshot">
        {data.snapshot.kind === "forbidden" ? (
          <ErrorState title="Acesso negado (403)" detail={data.snapshot.message} />
        ) : data.snapshot.kind === "error" ? (
          <ErrorState title="Falha no snapshot" detail={data.snapshot.message} />
        ) : !snapshot || snapshotKeys.length === 0 ? (
          <EmptyState title="Nenhum indicador de mercado" detail="O snapshot nao trouxe campos numericos para este ticker." />
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {snapshotKeys.map((key) => {
              const campo = campoDoSnapshot(snapshot, key);
              const shown = displayField(snapshot[key], campo, isMoneySnapshotField(key, campo));
              return (
                <li key={key} className="flex items-center justify-between gap-2 border border-olive/10 px-3 py-2">
                  <span className="text-sm text-olive/70">{key}</span>
                  <span className="flex items-center gap-2">
                    <span className="ticker text-sm text-olive">{shown.text}</span>
                    <DataBadge state={shown.kind} />
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      <Card eyebrow="Estado atual" title="Indicadores persistidos">
        {data.indicadores.kind === "forbidden" ? (
          <ErrorState title="Acesso negado (403)" detail={data.indicadores.message} />
        ) : data.indicadores.kind === "error" ? (
          <ErrorState title="Falha nos indicadores" detail={data.indicadores.message} />
        ) : indicadores.length === 0 ? (
          <EmptyState title="Nenhum indicador persistido" detail="GET /indicadores?ticker= devolveu lista vazia." />
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2">
            {indicadores.map((indicador) => {
              const shown = displayField(indicador.valor_atual, {
                semantica: indicador.semantica,
                unidade: indicador.unidade,
                escala: indicador.escala,
                aplicavel: indicador.aplicavel,
              });
              return (
                <li key={`${indicador.id}-${indicador.indicador}`} className="border border-olive/10 px-4 py-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm text-olive/70">{indicador.indicador}</span>
                    <DataBadge state={shown.kind} />
                  </div>
                  <p className="ticker mt-2 text-xl text-olive">{shown.text}</p>
                  <p className="mt-2 text-[11px] uppercase tracking-[0.12em] text-olive/45">
                    ref {formatDate(indicador.data_referencia) || "AUSENTE"} · coleta{" "}
                    {formatDate(indicador.ultima_coleta) || "AUSENTE"}
                    {indicador.origem ? ` · ${indicador.origem}` : ""}
                  </p>
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      <Card eyebrow="Origem" title="Proveniencia">
        {snapshot ? <ProvenienciaBlock snapshot={snapshot} /> : <p className="text-sm text-olive/60">Sem snapshot para provenance.</p>}
        {snapshot?.fonte_primaria ? (
          <p className="mt-3 text-sm text-olive/70">Fonte primaria {snapshot.fonte_primaria}</p>
        ) : null}
        {snapshot?.fonte_intermediaria ? (
          <p className="mt-1 text-sm text-olive/70">Fonte intermediaria {snapshot.fonte_intermediaria}</p>
        ) : null}
      </Card>

      <p className="text-[11px] uppercase tracking-[0.18em] text-olive/40">
        Sem grafico historico. Sem recalculo de indicadores. Sem dados mockados.
      </p>
    </div>
  );
}
