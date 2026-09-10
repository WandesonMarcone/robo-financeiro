import { AlertBadge } from "./AlertBadge";
import { DataBadge } from "./DataBadge";
import { EmptyState } from "./EmptyState";
import { ErrorState } from "./ErrorState";
import { formatDate } from "@/lib/format";
import { filterAlertasDoUsuario, notificacaoPrioridade, type ResourceState } from "@/lib/dashboard";
import type { AlertaEvento, Notificacao } from "@/lib/types";

function severityTone(severidade: string | null): string {
  return (severidade || "AUSENTE").toUpperCase();
}

export function AlertsPanel({
  notificacoes,
  alertas,
  tickers,
}: {
  notificacoes: ResourceState<Notificacao[]>;
  alertas: ResourceState<AlertaEvento[]>;
  tickers: string[];
}) {
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <section className="border border-olive/10 bg-white shadow-card">
        <header className="border-b border-olive/10 px-5 py-4">
          <p className="text-[11px] uppercase tracking-[0.22em] text-gold">Inbox</p>
          <h2 className="font-display text-lg text-olive">Notificacoes do usuario</h2>
        </header>
        <div className="px-5 py-4">
          {notificacoes.kind === "forbidden" ? (
            <ErrorState title="Acesso negado (403)" detail={notificacoes.message} />
          ) : null}
          {notificacoes.kind === "error" ? (
            <ErrorState title="Falha ao carregar notificacoes" detail={notificacoes.message} />
          ) : null}
          {notificacoes.kind === "ok" && notificacoes.data.length === 0 ? (
            <EmptyState title="Nenhuma notificacao" detail="A API nao retornou itens no inbox deste usuario." />
          ) : null}
          {notificacoes.kind === "ok" && notificacoes.data.length > 0 ? (
            <ul className="space-y-3">
              {notificacoes.data.slice(0, 8).map((item) => {
                const prioridade = notificacaoPrioridade(item);
                return (
                  <li key={item.id} className="border border-olive/10 px-3 py-3">
                    <div className="flex flex-wrap items-center gap-2">
                      {item.ticker ? <span className="ticker text-sm text-olive">{item.ticker}</span> : <DataBadge state="AUSENTE" />}
                      {item.tipo ? <AlertBadge label={item.tipo} priority={prioridade || item.tipo} /> : null}
                      {prioridade ? <AlertBadge label={prioridade} priority={prioridade} /> : null}
                      <DataBadge state={item.lida_em ? "PRESENTE" : "AUSENTE"} />
                    </div>
                    <p className="mt-2 text-sm text-olive">{item.titulo || "titulo AUSENTE"}</p>
                    <p className="mt-1 text-sm text-olive/70">{item.mensagem || "mensagem AUSENTE"}</p>
                    <p className="mt-2 text-[11px] uppercase tracking-[0.14em] text-olive/45">
                      {formatDate(item.criado_em) || "data AUSENTE"}
                      {item.canal ? ` · ${item.canal}` : ""}
                      {item.status ? ` · ${item.status}` : ""}
                    </p>
                  </li>
                );
              })}
            </ul>
          ) : null}
        </div>
      </section>

      <section className="border border-olive/10 bg-white shadow-card">
        <header className="border-b border-olive/10 px-5 py-4">
          <p className="text-[11px] uppercase tracking-[0.22em] text-gold">Mercado</p>
          <h2 className="font-display text-lg text-olive">Alertas cruzados com seus ativos</h2>
        </header>
        <div className="px-5 py-4">
          {alertas.kind === "forbidden" ? (
            <ErrorState title="Acesso negado (403)" detail={alertas.message} />
          ) : null}
          {alertas.kind === "error" ? (
            <ErrorState title="Falha ao carregar alertas" detail={alertas.message} />
          ) : null}
          {alertas.kind === "ok" && tickers.length === 0 ? (
            <EmptyState
              title="Sem escopo de ativos"
              detail="GET /alertas e global. Sem ticker da carteira ou acompanhamento, o dashboard nao atribui eventos ao usuario."
            />
          ) : null}
          {alertas.kind === "ok" && tickers.length > 0 ? (
            (() => {
              const filtrados = filterAlertasDoUsuario(alertas.data, tickers);
              if (filtrados.length === 0) {
                return (
                  <EmptyState
                    title="Nenhum alerta dos seus ativos"
                    detail="A API retornou eventos, mas nenhum ticker coincide com a carteira ou o acompanhamento deste usuario."
                  />
                );
              }
              return (
                <ul className="space-y-3">
                  {filtrados.slice(0, 8).map((alerta) => (
                    <li key={alerta.id} className="border border-olive/10 px-3 py-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="ticker text-sm text-olive">{alerta.ticker || "AUSENTE"}</span>
                        {alerta.tipo_alerta ? <AlertBadge label={alerta.tipo_alerta} priority={alerta.tipo_alerta} /> : null}
                        <DataBadge state={severityTone(alerta.severidade)} />
                      </div>
                      <p className="mt-2 text-sm text-olive">{alerta.motivo || alerta.regra || "motivo AUSENTE"}</p>
                      <p className="mt-1 text-sm text-olive/70">
                        {alerta.indicador || "indicador AUSENTE"}
                        {alerta.recomendacao ? ` · ${alerta.recomendacao}` : ""}
                      </p>
                      <p className="mt-2 text-[11px] uppercase tracking-[0.14em] text-olive/45">
                        {formatDate(alerta.data_evento) || "data AUSENTE"}
                      </p>
                    </li>
                  ))}
                </ul>
              );
            })()
          ) : null}
        </div>
      </section>
    </div>
  );
}
