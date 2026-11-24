"""Executa a coleta isolada de fundamentos para um ativo."""
import argparse
import json

from services.fundamentos_valuation import coletar_fundamentos_valuation


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--anos", type=int, default=5, choices=(3, 4, 5))
    args = parser.parse_args()
    resultado = coletar_fundamentos_valuation(args.ticker, anos=args.anos)
    print(json.dumps(resultado, ensure_ascii=False, default=str))
    if resultado.get("status") != "ok":
        raise SystemExit("coleta_fundamentos_sem_dados")
