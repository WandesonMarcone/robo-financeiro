import type { ReactNode } from "react";
import { EmptyState } from "./EmptyState";
import { ErrorState } from "./ErrorState";
import { Loading } from "./Loading";
import type { ResourceState } from "@/lib/dashboard";

export function SectionState<T>({
  state,
  emptyTitle,
  emptyDetail,
  children,
}: {
  state: ResourceState<T>;
  emptyTitle: string;
  emptyDetail?: string;
  children: (data: T) => ReactNode;
}) {
  if (state.kind === "forbidden") {
    return <ErrorState title="Acesso negado (403)" detail={state.message} />;
  }
  if (state.kind === "error") {
    return <ErrorState title="Falha ao carregar" detail={state.message} />;
  }
  if (state.kind === "absent") {
    return <EmptyState title={emptyTitle} detail={state.message || emptyDetail} />;
  }
  if (Array.isArray(state.data) && state.data.length === 0) {
    return <EmptyState title={emptyTitle} detail={emptyDetail} />;
  }
  return <>{children(state.data)}</>;
}

export function DashboardLoading() {
  return (
    <div className="space-y-4" role="status">
      <Loading label="Carregando dashboard" />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {["kpi-a", "kpi-b", "kpi-c", "kpi-d"].map((key) => (
          <div key={key} className="h-32 animate-pulse border border-olive/10 bg-white" />
        ))}
      </div>
    </div>
  );
}
