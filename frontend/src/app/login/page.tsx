"use client";

import { FormEvent, useState } from "react";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { Input } from "@/components/Input";
import { LogoSlot } from "@/components/LogoSlot";
import { useAuth } from "@/components/AuthProvider";
import { ApiError } from "@/lib/api";

export default function LoginPage() {
  const { login, expired } = useAuth();
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setErro(null);
    setSubmitting(true);
    try {
      await login(email.trim(), senha);
    } catch (err) {
      if (err instanceof ApiError && err.statusCode === 401) {
        setErro("Credenciais invalidas.");
      } else {
        setErro(err instanceof Error ? err.message : "Falha no login.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-sand px-4 py-10">
      <div className="w-full max-w-md space-y-6">
        <div className="flex justify-center rounded bg-olive px-4 py-5">
          <LogoSlot />
        </div>
        <Card eyebrow="Acesso institucional" title="Entrar">
          <form className="space-y-4" onSubmit={onSubmit} noValidate>
            {expired ? (
              <p className="border border-gold/40 bg-sand px-3 py-2 text-sm text-olive" role="status">
                Sessao expirada. Entre novamente.
              </p>
            ) : null}
            {erro ? (
              <p className="border border-[#5c1f1f]/30 bg-sand px-3 py-2 text-sm text-[#5c1f1f]" role="alert">
                {erro}
              </p>
            ) : null}
            <Input
              label="Email"
              name="email"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
            <Input
              label="Senha"
              name="senha"
              type="password"
              autoComplete="current-password"
              value={senha}
              onChange={(e) => setSenha(e.target.value)}
              required
            />
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? "Autenticando..." : "Entrar"}
            </Button>
          </form>
        </Card>
        <p className="text-center text-[11px] uppercase tracking-[0.2em] text-olive/50">
          Consome somente /api/v1
        </p>
      </div>
    </div>
  );
}
