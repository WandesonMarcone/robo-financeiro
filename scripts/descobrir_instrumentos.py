"""Descobre poucos instrumentos novos por execução, sem expansão irrestrita."""
import argparse

from services.descoberta_instrumentos import descobrir_e_cadastrar


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tipo", required=True, choices=("ETF", "BDR", "CRIPTO"))
    parser.add_argument("--limite", type=int, default=3)
    args = parser.parse_args()
    resultado = descobrir_e_cadastrar(args.tipo, limite=args.limite)
    print(resultado)
    if resultado.get("falhas"):
        raise SystemExit("descoberta_instrumentos_incompleta")
