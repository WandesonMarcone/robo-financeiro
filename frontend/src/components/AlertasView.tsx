"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertBadge } from "./AlertBadge";
import { Button } from "./Button";
import { Card } from "./Card";
import { DataBadge } from "./DataBadge";
import { EmptyState } from "./EmptyState";
import { ErrorState } from "./ErrorState";
import { KpiCard } from "./KpiCard";
import { Loading } from "./Loading";
import { isForbidden, isUnauthorized, marcarNotificacaoLida, marcarTodasNotificacoesLidas } from "@/lib/api";
import {
  alertaCritico,
  freshnessDaNotificacao,
  indicadorDaNotificacao,
  loadAlertas,
  notificacaoCritica,
  notificacaoLida,
  origemDaNotificacao,
  prioridadeExibida,
  type AlertasData,
} from "@/lib/alertas";
import { displayCount, formatDate } from "@/lib/format";
import type { AlertaEvento, Notificacao } from "@/lib/types";

export function AlertasLoading() {
  return (
    <div className="space-y-4" role="status">
      <Loading label="Carregando alertas" />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {["kpi-a", "kpi-b", "kpi-c"].map((key) => (
          <div key={key} className="h-32 animate-pulse border border-olive/10 bg-white" />
        ))}
      </div>
    </div>
  );
}

function NotificacaoItem({
  item,
  pending,
  onLer,
}: {
  item: Notificacao;
  pending: boolean;
  onLer: (id: number) => void;
}) {
  const lida = notificacaoLida(item);
  const prioridade = prioridadeExibida(item);
  const freshness = freshnessDaNotificacao(item);
  const indicador = indicadorDaNotificacao(item);
  const origem = origemDaNotificacao(item);
  const critico = notificacaoCritica(item);

  return (
    <li
      className={`border px-3 py-3 ${
        lida ? "border-olive/10 bg-white" : "border-gold/40 bg-sand"
      } ${critico ? "border-[#5c1f1f]/40" : ""}`}
    >
      <div className="flex flex-wrap items-center gap-2">
        {item.ticker ? (
          <span className="ticker text-sm text-olive">{item.ticker}</span>
        ) : (
          <DataBadge state="AUSENTE" />
        )}
        {item.tipo ? <AlertBadge label={item.tipo} priority={prioridade || item.tipo} /> : null}
        {prioridade ? <AlertBadge label={prioridade} priority={prioridade} /> : null}
        <BadgeLeitura lida={lida} />
        {freshness ? <DataBadge state={freshness} /> : null}
      </div>
      <p className="mt-2 text-sm text-olive">{item.titulo || "titulo AUSENTE"}</p>
      <p className="mt-1 text-sm text-olive/70">{item.mensagem || "mensagem AUSENTE"}</p>
      <p className="mt-2 text-[11px] uppercase tracking-[0.14em] text-olive/45">
        {formatDate(item.criado_em) || "data AUSENTE"}
        {indicador ? ` · ${indicador}` : ""}
        {origem ? ` · ${origem}` : ""}
        {item.status ? ` · ${item.status}` : ""}
      </p>
      {!lida ? (
        <div className="mt-3">
          <Button type="button" variant="ghost" disabled={pending} onClick={() => onLer(item.id)}>
            Marcar como lida
          </Button>
        </div>
      ) : null}
    </li>
  );
}

function BadgeLeitura({ lida }: { lida: boolean }) {
  return <AlertBadge label={lida ? "LIDA" : "NAO_LIDA"} priority={lida ? "ok" : "warning"} />;
}

function AlertaItem({ alerta }: { alerta: AlertaEvento }) {
  const critico = alertaCritico(alerta);
  return (
    <li className={`border px-3 py-3 ${critico ? "border-[#5c1f1f]/40 bg-white" : "border-olive/10 bg-white"}`}>
      <div className="flex flex-wrap items-center gap-2">
        {alerta.ticker ? (
          <span className="ticker text-sm text-olive">{alerta.ticker}</span>
        ) : (
          <DataBadge state="AUSENTE" />
        )}
        {alerta.tipo_alerta ? <AlertBadge label={alerta.tipo_alerta} priority={alerta.tipo_alerta} /> : null}
        {alerta.severidade ? <AlertBadge label={alerta.severidade} priority={alerta.severidade} /> : null}
      </div>
      <p className="mt-2 text-sm text-olive">{alerta.motivo || alerta.regra || "motivo AUSENTE"}</p>
      <p className="mt-1 text-sm text-olive/70">
        {alerta.indicador || "indicador AUSENTE"}
        {alerta.recomendacao ? ` · ${alerta.recomendacao}` : ""}
      </p>
      <p className="mt-2 text-[11px] uppercase tracking-[0.14em] text-olive/45">
        {formatDate(alerta.data_evento) || "data AUSENTE"}
        {alerta.origem ? ` · ${alerta.origem}` : ""}
        {alerta.tipo_ativo ? ` · ${alerta.tipo_ativo}` : ""}
      </p>
    </li>
  );
}

export function AlertasView() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<{ code: number; message: string } | null>(null);
  const [data, setData] = useState<AlertasData | null>(null);
  const [pendingId, setPendingId] = useState<number | "todas" | null>(null);
  const [acaoErro, setAcaoErro] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setAcaoErro(null);
    try {
      const payload = await loadAlertas();
      setData(payload);
    } catch (err) {
      if (isUnauthorized(err)) {
        setError({ code: 401, message: "Sessao invalida ou expirada." });
        return;
      }
      if (isForbidden(err)) {
        setError({ code: 403, message: "Acesso negado aos alertas." });
        return;
      }
      setError({
        code: 0,
        message: err instanceof Error ? err.message : "Falha ao carregar alertas.",
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function onLer(id: number) {
    setPendingId(id);
    setAcaoErro(null);
    try {
      const atualizada = await marcarNotificacaoLida(id);
      setData((atual) => {
        if (!atual || atual.notificacoes.kind !== "ok") {
          return atual;
        }
        return {
          ...atual,
          notificacoes: {
            ...atual.notificacoes,
            data: atual.notificacoes.data.map((item) => (item.id === atualizada.id ? atualizada : item)),
          },
          naoLidas:
            atual.naoLidas.kind === "ok"
              ? { ...atual.naoLidas, data: Math.max(0, atual.naoLidas.data - 1) }
              : atual.naoLidas,
        };
      });
    } catch (err) {
      if (isUnauthorized(err)) {
        setError({ code: 401, message: "Sessao invalida ou expirada." });
        return;
      }
      setAcaoErro(err instanceof Error ? err.message : "Falha ao marcar como lida.");
    } finally {
      setPendingId(null);
    }
  }

  async function onLerTodas() {
    setPendingId("todas");
    setAcaoErro(null);
    try {
      await marcarTodasNotificacoesLidas();
      await load();
    } catch (err) {
      if (isUnauthorized(err)) {
        setError({ code: 401, message: "Sessao invalida ou expirada." });
        return;
      }
      setAcaoErro(err instanceof Error ? err.message : "Falha ao marcar todas como lidas.");
      setPendingId(null);
    }
  }

  if (loading && !data) {
    return <AlertasLoading />;
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
        <ErrorState title="Falha ao carregar alertas" detail={error.message} />
        <Button type="button" onClick={() => void load()}>
          Tentar novamente
        </Button>
      </div>
    );
  }

  if (!data) {
    return <AlertasLoading />;
  }

  const inbox = data.notificacoes;
  const mercado = data.alertas;
  const inboxItems = inbox.kind === "ok" ? inbox.data : [];
  const mercadoItems = mercado.kind === "ok" ? mercado.data : [];
  const unreadCount = data.naoLidas.kind === "ok" ? data.naoLidas.data : null;
  const prefs = data.preferencias.kind === "ok" ? data.preferencias.data : null;
  const temNaoLidas = inboxItems.some((item) => !notificacaoLida(item));

  return (
    <div className="space-y-8">
      <header className="flex flex-col gap-4 border-b border-olive/10 pb-6 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-[11px] uppercase tracking-[0.24em] text-gold">Estrategia Fardada</p>
          <h1 className="font-display text-3xl text-olive md:text-5xl">Alertas</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-olive/70">
            Inbox pessoal em /notificacoes. Eventos de mercado em /alertas. Somente /api/v1.
          </p>
        </div>
        <p className="text-[11px] uppercase tracking-[0.16em] text-olive/50">GET /notificacoes · GET /alertas</p>
      </header>

      {loading ? <Loading label="Atualizando alertas" /> : null}

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <KpiCard
          eyebrow="Inbox"
          label="Notificacoes"
          value={displayCount(inbox.kind === "ok" ? (typeof inbox.meta?.total === "number" ? inbox.meta.total : inboxItems.length) : null)}
          hint={inbox.kind === "forbidden" ? "403 inbox" : "GET /notificacoes"}
        />
        <KpiCard
          eyebrow="Leitura"
          label="Nao lidas"
          value={displayCount(unreadCount)}
          hint={data.naoLidas.kind === "forbidden" ? "403 inbox" : "GET /notificacoes?nao_lidas=true"}
        />
        <KpiCard
          eyebrow="Mercado"
          label="Eventos"
          value={displayCount(mercado.kind === "ok" ? (typeof mercado.meta?.total === "number" ? mercado.meta.total : mercadoItems.length) : null)}
          hint={mercado.kind === "forbidden" ? "403 alertas" : "GET /alertas"}
        />
      </section>

      {prefs ? (
        <Card eyebrow="Preferencias" title="Canais informados pela API">
          <p className="text-sm text-olive/70">
            web={String(prefs.web_ativo)} · telegram={String(prefs.telegram_ativo)} · mestre=
            {String(prefs.notificacoes_ativas)} · frequencia={prefs.frequencia_notificacoes || "AUSENTE"}
          </p>
        </Card>
      ) : data.preferencias.kind === "forbidden" ? (
        <ErrorState title="Acesso negado (403)" detail={data.preferencias.message} />
      ) : data.preferencias.kind === "error" ? (
        <ErrorState title="Falha ao carregar preferencias" detail={data.preferencias.message} />
      ) : null}

      {acaoErro ? <ErrorState title="Falha na acao" detail={acaoErro} /> : null}

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="border border-olive/10 bg-white shadow-card">
          <header className="flex flex-col gap-3 border-b border-olive/10 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-[11px] uppercase tracking-[0.22em] text-gold">Inbox</p>
              <h2 className="font-display text-lg text-olive">Notificacoes do usuario</h2>
            </div>
            {temNaoLidas ? (
              <Button type="button" variant="ghost" disabled={pendingId === "todas"} onClick={() => void onLerTodas()}>
                Marcar todas como lidas
              </Button>
            ) : null}
          </header>
          <div className="px-5 py-4">
            {inbox.kind === "forbidden" ? <ErrorState title="Acesso negado (403)" detail={inbox.message} /> : null}
            {inbox.kind === "error" ? <ErrorState title="Falha ao carregar notificacoes" detail={inbox.message} /> : null}
            {inbox.kind === "ok" && inboxItems.length === 0 ? (
              <EmptyState title="Nenhuma notificacao" detail="A API nao retornou itens no inbox deste usuario." />
            ) : null}
            {inbox.kind === "ok" && inboxItems.length > 0 ? (
              <ul className="space-y-3">
                {inboxItems.map((item) => (
                  <NotificacaoItem
                    key={item.id}
                    item={item}
                    pending={pendingId === item.id || pendingId === "todas"}
                    onLer={(id) => void onLer(id)}
                  />
                ))}
              </ul>
            ) : null}
          </div>
        </section>

        <section className="border border-olive/10 bg-white shadow-card">
          <header className="border-b border-olive/10 px-5 py-4">
            <p className="text-[11px] uppercase tracking-[0.22em] text-gold">Mercado</p>
            <h2 className="font-display text-lg text-olive">Eventos GET /alertas</h2>
          </header>
          <div className="px-5 py-4">
            {mercado.kind === "forbidden" ? <ErrorState title="Acesso negado (403)" detail={mercado.message} /> : null}
            {mercado.kind === "error" ? <ErrorState title="Falha ao carregar alertas" detail={mercado.message} /> : null}
            {mercado.kind === "ok" && mercadoItems.length === 0 ? (
              <EmptyState title="Nenhum alerta de mercado" detail="GET /alertas nao retornou eventos." />
            ) : null}
            {mercado.kind === "ok" && mercadoItems.length > 0 ? (
              <ul className="space-y-3">
                {mercadoItems.map((alerta) => (
                  <AlertaItem key={alerta.id} alerta={alerta} />
                ))}
              </ul>
            ) : null}
          </div>
        </section>
      </div>
    </div>
  );
}
