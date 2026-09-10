"use client";

import { LogoSlot } from "./LogoSlot";
import { Button } from "./Button";
import { Badge } from "./Badge";
import { useAuth } from "./AuthProvider";
import { exibirPapel } from "@/lib/rbac";

export function Header({ onMenu }: { onMenu: () => void }) {
  const { usuario, logout } = useAuth();

  return (
    <header className="flex h-16 items-center justify-between border-b border-olive/15 bg-olive px-4 text-sand md:px-6">
      <div className="flex items-center gap-3">
        <button
          type="button"
          className="border border-gold/40 px-2 py-1 text-[11px] uppercase tracking-[0.16em] text-gold md:hidden"
          onClick={onMenu}
        >
          Menu
        </button>
        <LogoSlot />
      </div>
      <div className="flex items-center gap-3">
        {usuario ? (
          <>
            <div className="hidden text-right sm:block">
              <p className="text-sm text-sand">{usuario.nome}</p>
              <p className="text-[11px] uppercase tracking-[0.16em] text-sand/60">{usuario.email}</p>
            </div>
            <Badge tone="gold">{exibirPapel(usuario.papel) || usuario.papel}</Badge>
            <Button type="button" variant="ghost" className="border-gold/40 text-gold hover:text-sand" onClick={() => void logout()}>
              Sair
            </Button>
          </>
        ) : (
          <p className="hidden text-[11px] uppercase tracking-[0.2em] text-sand/60 sm:block">
            Website - Flask /api/v1
          </p>
        )}
      </div>
    </header>
  );
}
