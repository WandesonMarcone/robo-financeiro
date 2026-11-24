"""Coleta proventos e eventos em lote curto e rotativo."""
import argparse
import os

from services.proventos_eventos import coletar_proventos_eventos


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limite-por-classe", type=int, default=int(os.getenv("EVENTOS_LIMITE_POR_CLASSE", "20")))
    parser.add_argument("--janela-dias", type=int, default=int(os.getenv("EVENTOS_JANELA_DIAS", "75")))
    parser.add_argument("--pausa-segundos", type=float, default=1)
    args = parser.parse_args()
    resultado = coletar_proventos_eventos(
        limite_por_classe=args.limite_por_classe,
        janela_dias=args.janela_dias,
        pausa_segundos=args.pausa_segundos,
    )
    print(resultado)
    if resultado["falhas"]:
        raise SystemExit("coleta_proventos_eventos_incompleta")
