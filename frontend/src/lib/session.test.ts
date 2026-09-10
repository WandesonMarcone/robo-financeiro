import { afterEach, describe, expect, it } from "vitest";
import {
  clearSessionToken,
  consumeSessionExpired,
  getSessionToken,
  markSessionExpired,
  setSessionToken,
  storageHasPassword,
  tokenNeverInUrl,
} from "./session";

describe("sessao", () => {
  afterEach(() => {
    sessionStorage.clear();
    localStorage.clear();
  });

  it("rejeita token em query, path ou header na URL", () => {
    expect(tokenNeverInUrl("/api/v1/me")).toBe(true);
    expect(tokenNeverInUrl("/api/v1/me?token=abc")).toBe(false);
    expect(tokenNeverInUrl("/api/v1/auth?x-session-token=abc")).toBe(false);
    expect(tokenNeverInUrl("/login?api-key=k")).toBe(false);
    expect(tokenNeverInUrl("/login?senha=segredo")).toBe(false);
  });

  it("guarda o token apenas em sessionStorage", () => {
    setSessionToken("tok-web");
    expect(getSessionToken()).toBe("tok-web");
    expect(sessionStorage.getItem("ef_session_token")).toBe("tok-web");
    expect(localStorage.getItem("ef_session_token")).toBeNull();
  });

  it("remove o token no logout local", () => {
    setSessionToken("tok-web");
    clearSessionToken();
    expect(getSessionToken()).toBeNull();
  });

  it("nao persiste senha no storage", () => {
    setSessionToken("tok-web");
    expect(storageHasPassword()).toBe(false);
  });

  it("marca e consome sessao expirada", () => {
    markSessionExpired();
    expect(consumeSessionExpired()).toBe(true);
    expect(consumeSessionExpired()).toBe(false);
  });
});
