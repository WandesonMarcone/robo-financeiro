import { ApiError, isForbidden, isUnauthorized } from "./api";
import type { PaginationMeta } from "./types";

export type ResourceOk<T> = {
  kind: "ok";
  data: T;
  meta?: PaginationMeta;
};

export type ResourceState<T> =
  | ResourceOk<T>
  | { kind: "forbidden"; message: string }
  | { kind: "error"; message: string }
  | { kind: "absent"; message?: string };

export async function loadResource<T>(fn: () => Promise<T>): Promise<ResourceState<T>> {
  try {
    const data = await fn();
    return { kind: "ok", data };
  } catch (error) {
    if (isUnauthorized(error)) {
      throw error;
    }
    if (isForbidden(error)) {
      return {
        kind: "forbidden",
        message: error instanceof ApiError ? error.message : "Acesso negado.",
      };
    }
    if (error instanceof ApiError && error.statusCode === 404) {
      return { kind: "absent", message: error.message };
    }
    return {
      kind: "error",
      message: error instanceof Error ? error.message : "Falha de comunicacao",
    };
  }
}

export function itemsOf<T>(state: ResourceState<T[]>): T[] {
  return state.kind === "ok" ? state.data : [];
}
