"""Calcula quantos lotes noturnos são necessários para cobrir a base inteira.

O número nunca fica fixo no workflow: ele acompanha o cadastro real da
planilha. Assim, incluir novos ativos não cria silenciosamente uma parcela
sem atualização.
"""
from __future__ import annotations

import argparse
import math

from modules.lotes_atualizacao import distribuir_limite


def _tickers(linhas):
    return [str(linha[0]).strip().upper() for linha in linhas[1:] if linha and str(linha[0]).strip()]


def planejar(limite_total=30, planilha=None):
    if not 1 <= limite_total <= 30:
        raise ValueError("limite_total_invalido")
    if planilha is None:
        import config
        from modules.utils import conectar_gspread
        planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
    acoes = _tickers(planilha.worksheet("BD_Acoes").get_all_values())
    fiis = _tickers(planilha.worksheet("BD_FIIs").get_all_values())
    por_lote_acoes, por_lote_fiis = distribuir_limite(limite_total, len(acoes), len(fiis))
    ciclos_acoes = math.ceil(len(acoes) / por_lote_acoes) if por_lote_acoes else 0
    ciclos_fiis = math.ceil(len(fiis) / por_lote_fiis) if por_lote_fiis else 0
    return {
        "acoes": len(acoes), "fiis": len(fiis),
        "por_lote_acoes": por_lote_acoes, "por_lote_fiis": por_lote_fiis,
        "ciclos": max(1, ciclos_acoes, ciclos_fiis),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limite-total", type=int, default=30)
    parser.add_argument("--github-output", default="", help="Arquivo GITHUB_OUTPUT opcional")
    args = parser.parse_args()
    resultado = planejar(args.limite_total)
    print(resultado)
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as arquivo:
            for chave, valor in resultado.items():
                arquivo.write(f"{chave}={valor}\n")


if __name__ == "__main__":
    main()
