"""Executa a coleta isolada de fundamentos para um ativo."""
import argparse
import json
from pathlib import Path

from services.fundamentos_valuation import coletar_fundamentos_valuation


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker")
    parser.add_argument("--automatico", action="store_true")
    parser.add_argument("--limite", type=int, default=4)
    parser.add_argument("--anos", type=int, default=5, choices=(3, 4, 5))
    args = parser.parse_args()
    if args.automatico:
        from services.fila_fundamentos_acoes import executar_fila
        resultado = executar_fila(limite=args.limite)
        Path("resultado-fundamentos.json").write_text(json.dumps(resultado, ensure_ascii=False, default=str), encoding="utf-8")
        print(json.dumps(resultado, ensure_ascii=False, default=str))
        if resultado["falhas"]:
            raise SystemExit("fila_fundamentos_com_falhas")
        raise SystemExit(0)
    if not args.ticker:
        parser.error("informe --ticker ou --automatico")
    resultado = coletar_fundamentos_valuation(args.ticker, anos=args.anos)
    resumo = {"universo": 1, "processados": [{"ticker": args.ticker, "estado": "PARCIAL" if resultado.get("status") == "ok" else "FALHA", "detalhe": resultado}], "falhas": [args.ticker] if resultado.get("status") != "ok" or resultado.get("falhas") else []}
    Path("resultado-fundamentos.json").write_text(json.dumps(resumo, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps(resultado, ensure_ascii=False, default=str))
    if resultado.get("status") != "ok":
        raise SystemExit("coleta_fundamentos_sem_dados")
