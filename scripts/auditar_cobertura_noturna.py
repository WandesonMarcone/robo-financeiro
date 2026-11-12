"""Audita se a atualização noturna realmente cobriu ações e FIIs.

O workflow não deve ser considerado saudável apenas porque terminou sem uma
exceção Python. Esta checagem lê os carimbos que a própria coleta gravou na
planilha e falha de forma explícita quando há ativos sem coleta recente.  Com
isso, o GitHub Actions aciona o aviso administrativo já existente e o problema
fica visível no histórico em vez de permanecer silencioso por dias.
"""
from __future__ import annotations

import argparse
import re
from datetime import date, datetime, timedelta

import pytz


TICKER = re.compile(r"^[A-Z0-9]{4,10}$")
CARIMBO = re.compile(r"^OK\s+(\d{2})/(\d{2})\s+(\d{2}):(\d{2})$")


def ler_carimbo(valor: object, ano: int) -> datetime | None:
    """Converte o formato deliberadamente simples ``OK dd/mm hh:mm``.

    A coleta grava esse formato para leitura humana. A auditoria reconstitui o
    ano com cuidado para o caso de uma execução na primeira semana de janeiro.
    """
    encontrado = CARIMBO.match(str(valor or "").strip().upper())
    if not encontrado:
        return None
    dia, mes, hora, minuto = (int(parte) for parte in encontrado.groups())
    try:
        return datetime(ano, mes, dia, hora, minuto)
    except ValueError:
        return None


def avaliar_linhas(linhas: list[list[str]], *, coluna_carimbo: int,
                   referencia: date, atraso_maximo_dias: int) -> dict:
    """Devolve cobertura por aba sem tocar em rede; usada também nos testes."""
    limite = referencia - timedelta(days=atraso_maximo_dias)
    validos: list[tuple[str, datetime | None]] = []
    for linha in linhas[1:]:
        ticker = str(linha[0] if linha else "").strip().upper()
        if not TICKER.fullmatch(ticker):
            continue
        carimbo = linha[coluna_carimbo] if len(linha) > coluna_carimbo else ""
        momento = ler_carimbo(carimbo, referencia.year)
        # Um carimbo de dezembro lido em janeiro pertence ao ano anterior.
        if momento and momento.date() > referencia and referencia.month == 1 and momento.month == 12:
            momento = momento.replace(year=referencia.year - 1)
        validos.append((ticker, momento))
    ausentes = [ticker for ticker, momento in validos if momento is None]
    atrasados = [ticker for ticker, momento in validos if momento and momento.date() < limite]
    return {
        "total": len(validos),
        "atualizados": len(validos) - len(ausentes) - len(atrasados),
        "ausentes": ausentes,
        "atrasados": atrasados,
        "limite": limite.isoformat(),
    }


def executar(*, atraso_maximo_dias: int = 1, referencia: date | None = None,
             planilha=None) -> dict:
    if atraso_maximo_dias < 0 or atraso_maximo_dias > 10:
        raise ValueError("atraso_maximo_dias_invalido")
    if referencia is None:
        referencia = datetime.now(pytz.timezone("America/Sao_Paulo")).date()
    if planilha is None:
        import config
        from modules.utils import conectar_gspread
        planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
    acoes = avaliar_linhas(planilha.worksheet("BD_Acoes").get_all_values(), coluna_carimbo=32,
                           referencia=referencia, atraso_maximo_dias=atraso_maximo_dias)
    fiis = avaliar_linhas(planilha.worksheet("BD_FIIs").get_all_values(), coluna_carimbo=17,
                          referencia=referencia, atraso_maximo_dias=atraso_maximo_dias)
    pendentes = {
        "acoes": acoes["ausentes"] + acoes["atrasados"],
        "fiis": fiis["ausentes"] + fiis["atrasados"],
    }
    return {"referencia": referencia.isoformat(), "acoes": acoes, "fiis": fiis,
            "ok": not pendentes["acoes"] and not pendentes["fiis"], "pendentes": pendentes}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-atraso-dias", type=int, default=1)
    parser.add_argument("--data-referencia", default="", help="AAAA-MM-DD, apenas para diagnóstico")
    args = parser.parse_args()
    referencia = date.fromisoformat(args.data_referencia) if args.data_referencia else None
    resultado = executar(atraso_maximo_dias=args.max_atraso_dias, referencia=referencia)
    print(resultado)
    if not resultado["ok"]:
        raise SystemExit("cobertura_noturna_incompleta")


if __name__ == "__main__":
    main()
