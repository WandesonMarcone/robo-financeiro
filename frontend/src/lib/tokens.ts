export const colors = {
  sand: "#F4F1EA",
  olive: "#1B2E1C",
  gold: "#C5A059",
  white: "#FFFFFF",
  ink: "#1A1A1A",
} as const;

export const navItems = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/ativos", label: "Ativos" },
  { href: "/indicadores", label: "Indicadores" },
  { href: "/documentos", label: "Documentos" },
  { href: "/alertas", label: "Alertas" },
  { href: "/preferencias", label: "Preferencias" },
] as const;
