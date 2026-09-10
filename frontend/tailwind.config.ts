import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        sand: "#F4F1EA",
        olive: "#1B2E1C",
        gold: "#C5A059",
        ink: "#1A1A1A",
      },
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "system-ui", "sans-serif"],
        ticker: ["var(--font-ticker)", "system-ui", "sans-serif"],
      },
      boxShadow: {
        card: "0 8px 24px rgba(27, 46, 28, 0.08)",
      },
    },
  },
  plugins: [],
};

export default config;
