const TOKEN_KEY = "ef_session_token";
const EXPIRED_KEY = "ef_session_expired";

export const SESSION_HEADER = "X-Session-Token";

export function getSessionToken(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window.sessionStorage.getItem(TOKEN_KEY);
}

export function setSessionToken(token: string): void {
  if (typeof window === "undefined") {
    return;
  }
  window.sessionStorage.setItem(TOKEN_KEY, token);
}

export function clearSessionToken(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.sessionStorage.removeItem(TOKEN_KEY);
}

export function markSessionExpired(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.sessionStorage.setItem(EXPIRED_KEY, "1");
}

export function consumeSessionExpired(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  const flag = window.sessionStorage.getItem(EXPIRED_KEY);
  if (flag) {
    window.sessionStorage.removeItem(EXPIRED_KEY);
  }
  return flag === "1";
}

export function tokenNeverInUrl(url: string): boolean {
  const lower = url.toLowerCase();
  if (lower.includes("token=")) {
    return false;
  }
  if (lower.includes("x-session-token")) {
    return false;
  }
  if (lower.includes("api-key=")) {
    return false;
  }
  if (lower.includes("senha=")) {
    return false;
  }
  return true;
}

export function storageHasPassword(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  const inspect = (store: Storage) => {
    for (let i = 0; i < store.length; i += 1) {
      const key = store.key(i);
      if (!key) {
        continue;
      }
      const value = store.getItem(key) || "";
      if (key.toLowerCase().includes("senha") || key.toLowerCase().includes("password")) {
        return true;
      }
      if (value.toLowerCase().includes("senha=") || value.toLowerCase().includes("password=")) {
        return true;
      }
    }
    return false;
  };
  return inspect(window.sessionStorage) || inspect(window.localStorage);
}
