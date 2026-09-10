import { Badge } from "./Badge";

const map: Record<string, "gold" | "olive" | "critical" | "neutral"> = {
  baixa: "neutral",
  baixo: "neutral",
  ok: "neutral",
  media: "gold",
  medio: "gold",
  warning: "gold",
  qualidade: "gold",
  alta: "olive",
  alto: "olive",
  mercado: "olive",
  erro: "critical",
  critica: "critical",
  critico: "critical",
};

export function AlertBadge({
  label,
  priority,
}: {
  label: string;
  priority?: string;
}) {
  const key = (priority || label).toLowerCase();
  return <Badge tone={map[key] || "neutral"}>{label}</Badge>;
}
