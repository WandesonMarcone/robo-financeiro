import type { Metadata } from "next";
import { Allerta_Stencil, Inter, Montserrat } from "next/font/google";
import { AuthProvider } from "@/components/AuthProvider";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { AppGate } from "@/components/AppGate";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
});

const display = Allerta_Stencil({
  weight: "400",
  subsets: ["latin"],
  variable: "--font-display",
});

const ticker = Montserrat({
  subsets: ["latin"],
  weight: ["800"],
  variable: "--font-ticker",
});

export const metadata: Metadata = {
  title: "Estrategia Fardada",
  description: "Website institucional que consome somente /api/v1",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR" className={`${inter.variable} ${display.variable} ${ticker.variable}`}>
      <body className="font-sans antialiased">
        <AuthProvider>
          <ProtectedRoute>
            <AppGate>{children}</AppGate>
          </ProtectedRoute>
        </AuthProvider>
      </body>
    </html>
  );
}
