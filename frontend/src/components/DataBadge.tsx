import { Badge } from "./Badge";

const TONE: Record<string, "neutral" | "gold" | "olive" | "critical"> = {
  PRESENTE: "olive",
  ZERO: "gold",
  AUSENTE: "neutral",
  NAO_APLICAVEL: "neutral",
  INVALIDO: "critical",
  FRESH: "olive",
  STALE: "gold",
  MISSING: "critical",
};

export function DataBadge({ state }: { state: string | null | undefined }) {
  if (!state) {
    return <Badge tone="neutral">AUSENTE</Badge>;
  }
  const key = state.toUpperCase();
  return <Badge tone={TONE[key] || "neutral"}>{key}</Badge>;
}
