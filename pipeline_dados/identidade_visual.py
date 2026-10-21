"""Identidade visual e agrupamento de classes da mesma empresa.

O catalogo de logos e pesquisado por ticker, mas a identidade visual pertence a
empresa/emissor. Este modulo centraliza os grupos conhecidos para que o cache
em memoria e o cache persistente do Telegram usem a MESMA chave canonica.

A raiz B3 (``PETR3``/``PETR4`` -> ``PETR``) tambem agrupa a listagem de acoes
no menu. Nenhum dado financeiro e compartilhado: cada ticker continua com suas
proprias linhas em ``ativos`` e ``dados_financeiros_*``.
"""

from __future__ import annotations

import re

# Cada grupo tem um ticker canonico (primeiro item). Todos os membros apontam
# para o mesmo arquivo de logo/cache.
GRUPOS_IDENTIDADE_VISUAL = (
    ("PETR4", "PETR3"),
)

CANONICO_VISUAL = {}
for _grupo in GRUPOS_IDENTIDADE_VISUAL:
    _canonico = _grupo[0]
    for _ticker in _grupo:
        CANONICO_VISUAL[_ticker] = _canonico

# Compatibilidade com o nome historico usado por ``services.logo_service``.
IDENTIDADE_VISUAL = {ticker: canonico for ticker, canonico in CANONICO_VISUAL.items()}


def normalizar_ticker(ticker):
    """Normaliza o ticker (``MXRF11_fii`` -> ``MXRF11``)."""
    if ticker is None:
        return ""
    texto = str(ticker).strip().upper().split("_", 1)[0]
    return re.sub(r"[^A-Z0-9]", "", texto)


def chave_canonica(ticker):
    """Ticker canonico de identidade visual (``PETR3`` -> ``PETR4``)."""
    normalizado = normalizar_ticker(ticker)
    return CANONICO_VISUAL.get(normalizado, normalizado)


def tickers_equivalentes(ticker):
    """Tickers do mesmo grupo visual, com o canonico primeiro."""
    normalizado = normalizar_ticker(ticker)
    if not normalizado:
        return []
    canonico = chave_canonica(normalizado)
    grupo = [t for t, c in CANONICO_VISUAL.items() if c == canonico]
    ordenado = [canonico] + sorted(t for t in grupo if t != canonico)
    if normalizado not in ordenado:
        ordenado.insert(0, normalizado)
    return list(dict.fromkeys(ordenado))


# Codigo B3: raiz de 4 caracteres + 1-2 digitos (PETR4, TAEE11, B3SA3).
_PADRAO_RAIZ_B3 = re.compile(r"^(?=.*[A-Z])([A-Z0-9]{4})\d{1,2}$")


def raiz_ticker(ticker):
    """Raiz B3 do ticker (``PETR3``/``PETR4`` -> ``PETR``)."""
    normalizado = normalizar_ticker(ticker)
    match = _PADRAO_RAIZ_B3.fullmatch(normalizado)
    if match:
        return match.group(1)
    return normalizado


def agrupar_tickers_por_empresa(tickers):
    """Agrupa classes da mesma empresa pela raiz B3, sem misturar dados.

    Cada ticker continua independente em ``ativos`` e nas cotacoes. O agrupamento
    serve so para listagens (ex. ``PETR3``/``PETR4`` no mesmo botao). Grupos com
    um ticker ficam sozinhos; grupos com duas ou mais classes compartilham a
    raiz. Nao inventa nomes comerciais.
    """
    grupos = {}
    for ticker in tickers or []:
        normalizado = normalizar_ticker(ticker)
        if not normalizado:
            continue
        raiz = raiz_ticker(normalizado)
        membros = grupos.setdefault(raiz, [])
        if normalizado not in membros:
            membros.append(normalizado)
    resultado = []
    for raiz, membros in grupos.items():
        resultado.append((raiz, sorted(membros)))
    resultado.sort(key=lambda item: item[1][0])
    return resultado


__all__ = [
    "CANONICO_VISUAL",
    "GRUPOS_IDENTIDADE_VISUAL",
    "IDENTIDADE_VISUAL",
    "agrupar_tickers_por_empresa",
    "chave_canonica",
    "normalizar_ticker",
    "raiz_ticker",
    "tickers_equivalentes",
]
