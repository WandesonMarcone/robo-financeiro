"use client";

import { useEffect, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "./AuthProvider";
import { Loading } from "./Loading";
import { ErrorState } from "./ErrorState";
import { Button } from "./Button";
import { authRedirect, isPublicPath } from "@/lib/guards";

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { status, error } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const isPublic = isPublicPath(pathname);
  const redirectTo = authRedirect(status, pathname);

  useEffect(() => {
    if (redirectTo) {
      router.replace(redirectTo);
    }
  }, [redirectTo, router]);

  if (status === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-sand">
        <Loading label="Verificando sessao" />
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-sand px-4">
        <div className="w-full max-w-md space-y-4">
          <ErrorState title="Sessao indisponivel" detail={error || "Nao foi possivel falar com a API."} />
          <Button type="button" onClick={() => window.location.reload()}>
            Tentar novamente
          </Button>
        </div>
      </div>
    );
  }

  if (status === "unauthenticated" && !isPublic) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-sand">
        <Loading label="Redirecionando para login" />
      </div>
    );
  }

  if (status === "authenticated" && isPublic) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-sand">
        <Loading label="Entrando na area protegida" />
      </div>
    );
  }

  return <>{children}</>;
}
