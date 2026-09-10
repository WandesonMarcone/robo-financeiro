import type { AuthStatus } from "./types";

export const LOGIN_PATH = "/login";
export const APP_HOME = "/dashboard";

export function isPublicPath(pathname: string): boolean {
  return pathname === LOGIN_PATH;
}

export function authRedirect(
  status: AuthStatus,
  pathname: string,
): typeof LOGIN_PATH | typeof APP_HOME | null {
  const pub = isPublicPath(pathname);
  if (status === "unauthenticated" && !pub) {
    return LOGIN_PATH;
  }
  if (status === "authenticated" && pub) {
    return APP_HOME;
  }
  return null;
}
