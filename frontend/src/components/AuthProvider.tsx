"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";
import { ApiError, setAuthFailureHandler } from "@/lib/api";
import { restoreSession, signIn, signOut, takeExpiredFlag } from "@/lib/auth";
import type { AuthStatus, Usuario } from "@/lib/types";

type AuthContextValue = {
  status: AuthStatus;
  usuario: Usuario | null;
  expired: boolean;
  forbidden: string | null;
  error: string | null;
  login: (email: string, senha: string) => Promise<void>;
  logout: () => Promise<void>;
  clearForbidden: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [usuario, setUsuario] = useState<Usuario | null>(null);
  const [expired, setExpired] = useState(false);
  const [forbidden, setForbidden] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  const applyUnauthorized = useCallback(() => {
    setUsuario(null);
    setStatus("unauthenticated");
    setExpired(true);
  }, []);

  useEffect(() => {
    let cancelled = false;
    restoreSession()
      .then((user) => {
        if (cancelled) return;
        if (user) {
          setUsuario(user);
          setStatus("authenticated");
          setExpired(false);
          return;
        }
        setUsuario(null);
        setStatus("unauthenticated");
        setExpired(takeExpiredFlag());
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setStatus("error");
        setError(err instanceof Error ? err.message : "Falha ao verificar sessao");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    setAuthFailureHandler((apiError: ApiError) => {
      if (apiError.statusCode === 401) applyUnauthorized();
      if (apiError.statusCode === 403) setForbidden(apiError.message || "Acesso negado.");
    });
    return () => setAuthFailureHandler(null);
  }, [applyUnauthorized]);

  const login = useCallback(async (email: string, senha: string) => {
    setError(null);
    const user = await signIn(email, senha);
    setUsuario(user);
    setStatus("authenticated");
    setExpired(false);
    router.replace("/dashboard");
  }, [router]);

  const logout = useCallback(async () => {
    await signOut();
    setUsuario(null);
    setStatus("unauthenticated");
    setExpired(false);
    router.replace("/login");
  }, [router]);

  const value = useMemo(
    () => ({
      status, usuario, expired, forbidden, error, login, logout,
      clearForbidden: () => setForbidden(null),
    }),
    [status, usuario, expired, forbidden, error, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth requer AuthProvider");
  return ctx;
}
