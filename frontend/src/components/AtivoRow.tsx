import Link from "next/link";
import { Badge } from "./Badge";
import { DataBadge } from "./DataBadge";
import { campoDoSnapshot, listIndicatorKeys } from "@/lib/ativos";
import { displayField, formatDate } from "@/lib/format";
import type { AtivoListItem } from "@/lib/ativos";

export function AtivoRow({ item }: { item: AtivoListItem }) {
  const ticker = item.ativo.ticker || "AUSENTE";
  const href = item.ativo.ticker ? `/ativos/${encodeURIComponent(item.ativo.ticker)}` : "/ativos";
  const preco = displayField(item.snapshot?.preco ?? null, campoDoSnapshot(item.snapshot, "preco"), true);

  return (
    <tr className="border-b border-olive/10">
      <td className="px-3 py-3">
        <Link href={href} className="ticker text-olive hover:text-gold">
          {ticker}
        </Link>
        <p className="mt-1 text-[11px] uppercase tracking-[0.14em] text-olive/45">
          {item.ativo.setor || item.ativo.tipo_fii || "cadastro"}
        </p>
      </td>
      <td className="px-3 py-3">
        {item.ativo.tipo ? <Badge tone="olive">{item.ativo.tipo}</Badge> : <DataBadge state="AUSENTE" />}
      </td>
      <td className="px-3 py-3">
        <p className="ticker text-sm text-olive">{preco.text}</p>
        <DataBadge state={preco.kind} />
      </td>
      <td className="px-3 py-3">
        <ul className="space-y-1">
          {listIndicatorKeys()
            .filter((key) => key !== "preco")
            .map((key) => {
              const shown = displayField(
                item.snapshot ? item.snapshot[key] : null,
                campoDoSnapshot(item.snapshot, key),
                key === "vpa",
              );
              return (
                <li key={key} className="flex items-center justify-between gap-2">
                  <span className="text-[11px] uppercase tracking-[0.12em] text-olive/50">{key}</span>
                  <span className="flex items-center gap-2">
                    <span className="ticker text-xs text-olive">{shown.text}</span>
                    <DataBadge state={shown.kind} />
                  </span>
                </li>
              );
            })}
        </ul>
      </td>
      <td className="px-3 py-3">
        <p className="text-xs text-olive/70">{formatDate(item.snapshot?.data_coleta) || "AUSENTE"}</p>
        <p className="mt-1 text-[11px] uppercase tracking-[0.12em] text-olive/45">
          ref {formatDate(item.snapshot?.data_referencia) || "AUSENTE"}
        </p>
      </td>
      <td className="px-3 py-3">
        <div className="flex flex-wrap gap-1">
          {item.naCarteira ? <Badge tone="gold">Carteira</Badge> : null}
          {item.acompanhado ? <Badge tone="olive">Acompanhado</Badge> : null}
          {!item.naCarteira && !item.acompanhado ? <DataBadge state="AUSENTE" /> : null}
        </div>
      </td>
    </tr>
  );
}
