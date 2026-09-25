import { describe, expect, it } from "vitest";
import { APP_HOME, LOGIN_PATH, authRedirect, isPublicPath } from "./guards";

describe("protecao de rotas", () => {
  it("login e publico; area autenticada nao", () => {
    expect(isPublicPath("/login")).toBe(true);
    expect(isPublicPath("/dashboard")).toBe(false);
    expect(isPublicPath("/ativos")).toBe(false);
    expect(isPublicPath("/carteira")).toBe(false);
    expect(isPublicPath("/documentos")).toBe(false);
  });

  it("nao autenticado e enviado ao login", () => {
    expect(authRedirect("unauthenticated", "/dashboard")).toBe(LOGIN_PATH);
    expect(authRedirect("unauthenticated", "/ativos")).toBe(LOGIN_PATH);
    expect(authRedirect("unauthenticated", "/carteira")).toBe(LOGIN_PATH);
    expect(authRedirect("unauthenticated", "/documentos")).toBe(LOGIN_PATH);
    expect(authRedirect("unauthenticated", "/login")).toBeNull();
  });

  it("autenticado na area principal; login redireciona", () => {
    expect(authRedirect("authenticated", "/login")).toBe(APP_HOME);
    expect(authRedirect("authenticated", "/dashboard")).toBeNull();
    expect(authRedirect("loading", "/dashboard")).toBeNull();
  });
});
