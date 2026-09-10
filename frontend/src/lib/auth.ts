import { isUnauthorized, loginRequest, logoutRequest, meRequest } from "./api";
import {
  clearSessionToken,
  consumeSessionExpired,
  getSessionToken,
  setSessionToken,
  storageHasPassword,
} from "./session";
import type { Usuario } from "./types";

export async function signIn(email: string, senha: string): Promise<Usuario> {
  const payload = await loginRequest(email, senha);
  setSessionToken(payload.token);
  return payload.usuario;
}

export async function signOut(): Promise<void> {
  try {
    if (getSessionToken()) {
      await logoutRequest();
    }
  } catch {
    return;
  } finally {
    clearSessionToken();
  }
}

export async function restoreSession(): Promise<Usuario | null> {
  if (!getSessionToken()) {
    return null;
  }
  try {
    return await meRequest();
  } catch (error) {
    if (isUnauthorized(error)) {
      clearSessionToken();
      return null;
    }
    throw error;
  }
}

export function takeExpiredFlag(): boolean {
  return consumeSessionExpired();
}

export function credentialsWereStored(): boolean {
  return storageHasPassword();
}
