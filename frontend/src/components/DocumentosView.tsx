"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Badge } from "./Badge";
import { Button } from "./Button";
import { DataBadge } from "./DataBadge";
import { EmptyState } from "./EmptyState";
import { ErrorState } from "./ErrorState";
import { Input } from "./Input";
import { KpiCard } from "./KpiCard";
import { Loading } from "./Loading";
import { Table } from "./Table";
import { isForbidden, isUnauthorized } from "@/lib/api";
import {
  loadDocumentos,
  normalizeStatusQuery,
  normalizeTextoQuery,
  normalizeTickerQuery,
  urlPdfValida,
  type DocumentosData,
} from "@/lib/documentos";
import { displayCount, formatDate } from "@/lib/format";
import type { Documento } from "@/lib/types";

const HEADERS = ["Ativo", "Tipo", "Assunto", "Publicacao", "Origem / Status", "Arquivo"];

export function DocumentosLoading() {
  return (
    <div className="space-y-4" role="status">
      <Loading label="Carregando documentos" />
      <div className="h-48 animate-pulse border border-olive/10 bg-white" />
    </div>
  );
}

function CampoTexto({ valor }: { valor: string | null | undefined }) {
  if (!valor) {
    return <DataBadge state="AUSENTE" />;
  }
  return <span className="text-sm text-olive">{valor}</span>;
}

function DocumentoRow({ item }: { item: Documento }) {
  const pdf = urlPdfValida(item.url_pdf);
  return (
    <tr className="border-b border-olive/10">
      <td className="px-3 py-3">
        {item.ticker ? (
          <span className="ticker text-sm text-olive">{item.ticker}</span>
        ) : (
          <DataBadge state="AUSENTE" />
        )}
      </td>
      <td className="px-3 py-3">
        {item.tipo_documento ? <Badge tone="olive">{item.tipo_documento}</Badge> : <DataBadge state="AUSENTE" />}
      </td>
      <td className="px-3 py-3">
        <CampoTexto valor={item.assunto} />
      </td>
      <td className="px-3 py-3">
        <p className="text-xs text-olive/70">{formatDate(item.data_publicacao) || "AUSENTE"}</p>
        <p className="mt-1 text-[11px] uppercase tracking-[0.12em] text-olive/45">
          atualizado {formatDate(item.data_atualizacao) || "AUSENTE"}
        </p>
      </td>
      <td className="px-3 py-3">
        <p className="text-[11px] uppercase tracking-[0.12em] text-olive/50">
          {item.id_b3 ? `B3 ${item.id_b3}` : "origem AUSENTE"}
        </p>
        <div className="mt-1">
          {item.status_processamento ? (
            <Badge tone="gold">{item.status_processamento}</Badge>
          ) : (
            <DataBadge state="AUSENTE" />
          )}
        </div>
      </td>
      <td className="px-3 py-3">
        {pdf ? (
          <a
            href={pdf}
            target="_blank"
            rel="noreferrer"
            className="text-sm text-olive underline decoration-gold/60 underline-offset-4 hover:text-gold"
          >
            Abrir PDF
          </a>
        ) : (
          <DataBadge state="AUSENTE" />
        )}
      </td>
    </tr>
  );
}

function DocumentoCard({ item }: { item: Documento }) {
  const pdf = urlPdfValida(item.url_pdf);
  return (
    <article className="border border-olive/10 bg-white px-4 py-4 shadow-card">
      <div className="flex flex-wrap items-center gap-2">
        {item.ticker ? <span className="ticker text-sm text-olive">{item.ticker}</span> : <DataBadge state="AUSENTE" />}
        {item.tipo_documento ? <Badge tone="olive">{item.tipo_documento}</Badge> : null}
        {item.status_processamento ? <Badge tone="gold">{item.status_processamento}</Badge> : null}
      </div>
      <p className="mt-2 text-sm text-olive">{item.assunto || "assunto AUSENTE"}</p>
      <p className="mt-2 text-[11px] uppercase tracking-[0.14em] text-olive/45">
        {formatDate(item.data_publicacao) || "data AUSENTE"}
        {item.id_b3 ? ` · B3 ${item.id_b3}` : " · origem AUSENTE"}
      </p>
      <div className="mt-3">
        {pdf ? (
          <a
            href={pdf}
            target="_blank"
            rel="noreferrer"
            className="text-sm text-olive underline decoration-gold/60 underline-offset-4 hover:text-gold"
          >
            Abrir PDF
          </a>
        ) : (
          <DataBadge state="AUSENTE" />
        )}
      </div>
    </article>
  );
}

export function DocumentosView() {
  const [draftTicker, setDraftTicker] = useState("");
  const [draftTipo, setDraftTipo] = useState("");
  const [draftStatus, setDraftStatus] = useState("");
  const [ticker, setTicker] = useState<string | undefined>(undefined);
  const [tipoDocumento, setTipoDocumento] = useState<string | undefined>(undefined);
  const [status, setStatus] = useState<string | undefined>(undefined);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<{ code: number; message: string } | null>(null);
  const [data, setData] = useState<DocumentosData | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await loadDocumentos({
        ticker,
        tipo_documento: tipoDocumento,
        status,
        page,
      });
      setData(payload);
    } catch (err) {
      if (isUnauthorized(err)) {
        setError({ code: 401, message: "Sessao invalida ou expirada." });
        return;
      }
      if (isForbidden(err)) {
        setError({ code: 403, message: "Acesso negado aos documentos." });
        return;
      }
      setError({
        code: 0,
        message: err instanceof Error ? err.message : "Falha ao carregar documentos.",
      });
    } finally {
      setLoading(false);
    }
  }, [ticker, tipoDocumento, status, page]);

  useEffect(() => {
    void load();
  }, [load]);

  function onSearch(event: FormEvent) {
    event.preventDefault();
    setPage(1);
    setTicker(normalizeTickerQuery(draftTicker));
    setTipoDocumento(normalizeTextoQuery(draftTipo));
    setStatus(normalizeStatusQuery(draftStatus));
  }

  function onClear() {
    setDraftTicker("");
    setDraftTipo("");
    setDraftStatus("");
    setTicker(undefined);
    setTipoDocumento(undefined);
    setStatus(undefined);
    setPage(1);
  }

  if (loading && !data) {
    return <DocumentosLoading />;
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
        <ErrorState title="Falha ao carregar documentos" detail={error.message} />
        <Button type="button" onClick={() => void load()}>
          Tentar novamente
        </Button>
      </div>
    );
  }

  const forbidden = data?.documentos.kind === "forbidden";
  const apiError = data?.documentos.kind === "error";
  const empty = data?.documentos.kind === "ok" && data.items.length === 0;
  const total = typeof data?.meta.total === "number" ? data.meta.total : data?.items.length || 0;
  const hasNext = Boolean(data?.meta.has_next);
  const currentPage = typeof data?.meta.page === "number" ? data.meta.page : page;

  return (
    <div className="space-y-8">
      <header className="flex flex-col gap-4 border-b border-olive/10 pb-6 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-[11px] uppercase tracking-[0.24em] text-gold">Estrategia Fardada</p>
          <h1 className="font-display text-3xl text-olive md:text-5xl">Documentos</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-olive/70">
            Metadados de GET /documentos. url_pdf na origem oficial. Sem texto extraido, resumo IA ou log de erro.
          </p>
        </div>
        <p className="text-[11px] uppercase tracking-[0.16em] text-olive/50">GET /documentos · {total} retornados</p>
      </header>

      <form
        onSubmit={onSearch}
        className="grid gap-4 border border-olive/10 bg-white p-4 md:grid-cols-[1fr_1fr_10rem_auto_auto] md:items-end"
      >
        <Input
          label="Ticker"
          name="ticker"
          value={draftTicker}
          onChange={(event) => setDraftTicker(event.target.value)}
          placeholder="Igualdade exata, ex. HGLG11"
          autoComplete="off"
        />
        <Input
          label="Tipo"
          name="tipo_documento"
          value={draftTipo}
          onChange={(event) => setDraftTipo(event.target.value)}
          placeholder="tipo_documento da API"
          autoComplete="off"
        />
        <Input
          label="Status"
          name="status"
          value={draftStatus}
          onChange={(event) => setDraftStatus(event.target.value)}
          placeholder="ex. SALVO"
          autoComplete="off"
        />
        <Button type="submit">Filtrar</Button>
        <Button type="button" variant="ghost" onClick={onClear}>
          Limpar
        </Button>
      </form>

      {loading ? <Loading label="Atualizando documentos" /> : null}

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <KpiCard
          eyebrow="Catalogo"
          label="Documentos"
          value={displayCount(data?.documentos.kind === "ok" ? total : null)}
          hint={forbidden ? "403 documentos" : "GET /documentos"}
        />
      </section>

      {forbidden ? (
        <ErrorState
          title="Acesso negado (403)"
          detail={data?.documentos.kind === "forbidden" ? data.documentos.message : undefined}
        />
      ) : null}
      {apiError ? (
        <ErrorState
          title="Falha ao carregar documentos"
          detail={data?.documentos.kind === "error" ? data.documentos.message : undefined}
        />
      ) : null}
      {empty ? (
        <EmptyState
          title="Nenhum documento retornado"
          detail={
            ticker
              ? `GET /documentos?ticker=${ticker} nao encontrou igualdade exata.`
              : "A API devolveu lista vazia. A tela nao inventa documentos."
          }
        />
      ) : null}

      {data && data.items.length > 0 ? (
        <>
          <div className="hidden border border-olive/10 bg-white md:block">
            <Table headers={HEADERS}>
              {data.items.map((item) => (
                <DocumentoRow key={item.id} item={item} />
              ))}
            </Table>
          </div>
          <div className="grid gap-3 md:hidden">
            {data.items.map((item) => (
              <DocumentoCard key={item.id} item={item} />
            ))}
          </div>
        </>
      ) : null}

      {data && data.documentos.kind === "ok" && total > 0 ? (
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
        Sem upload. Sem classificacao. Sem texto extraido. Sem GET /documentos/id.
      </p>
    </div>
  );
}
