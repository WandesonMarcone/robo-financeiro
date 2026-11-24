"""Cadastra e coleta imediatamente um novo instrumento de mercado."""
import argparse

from services.coletor_etfs_bdrs import (
    TIPOS_INSTRUMENTO_MERCADO,
    coletar_instrumento,
    registrar_instrumento,
)


def executar(ticker, tipo, simbolo_yahoo=None):
    item = registrar_instrumento(
        ticker, tipo, simbolo_exterior=simbolo_yahoo, simbolo_yahoo=simbolo_yahoo
    )
    coleta = coletar_instrumento(item["ticker"])
    return {"cadastro": item, "primeira_coleta": coleta}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--tipo", required=True, choices=sorted(TIPOS_INSTRUMENTO_MERCADO))
    parser.add_argument("--simbolo-yahoo", default=None)
    args = parser.parse_args()
    print(executar(args.ticker, args.tipo, args.simbolo_yahoo))
