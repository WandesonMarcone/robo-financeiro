"use client";

import { useState, type ReactNode } from "react";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";
import { useAuth } from "./AuthProvider";
import { Button } from "./Button";

export function AppShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const { forbidden, clearForbidden } = useAuth();

  return (
    <div className="min-h-screen bg-sand">
      <Header onMenu={() => setOpen(true)} />
      <div className="md:flex">
        <Sidebar open={open} onClose={() => setOpen(false)} />
        <main className="min-h-[calc(100vh-4rem)] flex-1 px-4 py-6 md:px-8">
          {forbidden ? (
            <div className="mb-4 flex items-start justify-between border border-[#5c1f1f]/30 bg-white px-4 py-3">
              <div>
                <p className="text-[11px] uppercase tracking-[0.18em] text-[#5c1f1f]">Acesso negado</p>
                <p className="mt-1 text-sm text-olive/80">{forbidden}</p>
              </div>
              <Button type="button" variant="ghost" onClick={clearForbidden}>
                Fechar
              </Button>
            </div>
          ) : null}
          {children}
        </main>
      </div>
    </div>
  );
}
