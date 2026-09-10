import type { Usuario } from "./types";

export function papelDoUsuario(usuario: Usuario | null): string | null {
  return usuario?.papel ?? null;
}

export function exibirPapel(papel: string | null): string {
  if (!papel) {
    return "";
  }
  return papel.replaceAll("_", " ");
}
