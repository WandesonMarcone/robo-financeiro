"""Seleção determinística de lotes curtos para atualização de mercado.

O estado fica separado da seleção para que só seja persistido depois que as
gravações de dados tenham sido concluídas com sucesso.
"""
from __future__ import annotations


def normalizar_tickers(valores):
    vistos = set()
    resultado = []
    for valor in valores or []:
        ticker = str(valor or "").strip().upper()
        if ticker and ticker not in vistos:
            vistos.add(ticker)
            resultado.append(ticker)
    return resultado


def proximo_lote(tickers, cursor, limite):
    """Retorna até o limite em rotação e o cursor seguinte."""
    ativos = normalizar_tickers(tickers)
    if limite < 0:
        raise ValueError("limite_invalido")
    if not ativos or limite == 0:
        return [], 0
    try:
        inicio = int(cursor)
    except (TypeError, ValueError):
        inicio = 0
    inicio %= len(ativos)
    quantidade = min(int(limite), len(ativos))
    lote = [ativos[(inicio + offset) % len(ativos)] for offset in range(quantidade)]
    return lote, (inicio + quantidade) % len(ativos)


def distribuir_limite(total, quantidade_acoes, quantidade_fiis):
    """Divide o teto total proporcionalmente, mantendo ambos os tipos vivos."""
    if total < 1:
        raise ValueError("total_invalido")
    acoes = max(0, int(quantidade_acoes))
    fiis = max(0, int(quantidade_fiis))
    universo = acoes + fiis
    if not universo:
        return 0, 0
    if not fiis:
        return min(total, acoes), 0
    if not acoes:
        return 0, min(total, fiis)

    limite_fiis = max(1, round(total * fiis / universo))
    limite_fiis = min(limite_fiis, fiis, total - 1)
    limite_acoes = min(total - limite_fiis, acoes)
    sobra = total - limite_acoes - limite_fiis
    if sobra and limite_acoes < acoes:
        limite_acoes += sobra
    elif sobra and limite_fiis < fiis:
        limite_fiis += sobra
    return limite_acoes, limite_fiis
