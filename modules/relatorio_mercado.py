"""Carteira popular, nomes de exibicao e filtro de oportunidades.

A carteira destacada nas varreduras vem do ranking real de favoritos
(``ativos_acompanhados``), nao de listas hardcoded. Nomes oficiais vem do
catalogo/CVM ou do mapa de iscas; nada e inventado. Oportunidades exigem
liquidez e, nas acoes, ticker mapeado na B3.
"""

from __future__ import annotations

import logging
import re

import config
from pipeline_dados.identidade_visual import (
    agrupar_tickers_por_empresa,
    chave_canonica,
    normalizar_ticker,
    raiz_ticker,
)

logger = logging.getLogger("robo.relatorio")

_SUFIXOS_SOCIETARIOS = re.compile(
    r"\b(s\.?a\.?|s/a|ltda\.?)\s*$",
    re.IGNORECASE,
)


def obter_carteira_popular(tipo, limite=None):
    """Tickers mais salvos como favorito. Lista vazia se ninguem acompanha."""
    teto = limite if limite is not None else getattr(
        config, "CARTEIRA_POPULAR_LIMITE", 5
    )
    try:
        from pipeline_dados.repositorio_favoritos import RepositorioFavoritos

        return RepositorioFavoritos().ranking_mais_acompanhados(tipo, teto)
    except Exception:
        logger.debug("Ranking de favoritos indisponivel para %s", tipo, exc_info=True)
        return []


def _encurtar_nome(nome):
    texto = re.sub(r"\s+", " ", str(nome or "")).strip()
    if not texto:
        return ""
    texto = _SUFIXOS_SOCIETARIOS.sub("", texto).strip(" .,")
    if not texto:
        return str(nome).strip()
    partes = texto.split()
    if len(partes) >= 3 and partes[0].upper() == "PETROLEO":
        return partes[-1].title() if partes[-1].isupper() else partes[-1]
    if texto.isupper():
        return texto.title()
    return texto


def _resumo_empresa(ticker):
    from services.catalogo_empresas import obter_resumo_empresa

    return obter_resumo_empresa(ticker)


def _tickers_mesma_empresa(ticker):
    """Classes da mesma raiz B3 (PETR3/PETR4), sem misturar BBAS e BBSE.

    A ordem prioriza o ticker pedido e o canonico visual; as demais classes
    vem do mapa setorial ja existente, nao de uma lista de nomes.
    """
    chave = normalizar_ticker(ticker)
    if not chave:
        return []
    vistos = []

    def _incluir(valor):
        normalizado = normalizar_ticker(valor)
        if normalizado and normalizado not in vistos:
            vistos.append(normalizado)

    _incluir(chave)
    _incluir(chave_canonica(chave))
    raiz = raiz_ticker(chave)
    if not raiz:
        return vistos
    mapa = getattr(config, "MAPA_SETORES_B3", {}) or {}
    for subsetores in mapa.values():
        for lista in (subsetores or {}).values():
            for outro in lista or []:
                if raiz_ticker(outro) == raiz:
                    _incluir(outro)
    return vistos


def _nome_do_catalogo(ticker):
    try:
        resumo = _resumo_empresa(ticker)
    except Exception:
        logger.debug("Catalogo indisponivel para nome de %s", ticker, exc_info=True)
        return None
    if not resumo or not resumo.get("empresa"):
        return None
    emp = resumo["empresa"]
    escolhido = emp.nome_comercial or emp.nome
    curto = _encurtar_nome(escolhido)
    return curto or None


def nome_empresa(ticker, tipo="acao"):
    """Nome oficial curto, ou ``None`` se nao houver fonte (nao inventa)."""
    chave = normalizar_ticker(ticker)
    if not chave:
        return None
    for candidato in _tickers_mesma_empresa(chave):
        curto = _nome_do_catalogo(candidato)
        if curto:
            return curto
    if tipo == "fii":
        isca = (getattr(config, "MAPA_ISCAS_MASTER", {}) or {}).get(chave)
        if isca:
            return str(isca).strip()
    return None


def rotulo_ticker(ticker, tipo="acao"):
    """``Petrobras (PETR4)`` ou so o ticker se nao houver nome oficial."""
    chave = normalizar_ticker(ticker) or str(ticker or "").strip().upper()
    nome = nome_empresa(chave, tipo)
    if nome:
        return f"{nome} ({chave})"
    return chave


def _nome_entre(tickers, tipo="acao"):
    """Primeiro nome oficial encontrado entre os tickers (nao inventa)."""
    for ticker in tickers or []:
        nome = nome_empresa(ticker, tipo)
        if nome:
            return nome
    return None


def rotulo_grupo(membros, tipo="acao"):
    """Rotulo de botao: um ticker ou ``Petrobras (PETR3/PETR4)``."""
    presentes = [normalizar_ticker(t) for t in (membros or [])]
    presentes = [t for t in presentes if t]
    if not presentes:
        return ""
    if len(presentes) == 1:
        return rotulo_ticker(presentes[0], tipo)
    nome = _nome_entre(presentes, tipo)
    classes = "/".join(presentes)
    if nome:
        return f"{nome} ({classes})"
    return classes


def ticker_no_mapa_b3(ticker):
    chave = normalizar_ticker(ticker)
    if not chave:
        return False
    mapa = getattr(config, "MAPA_SETORES_B3", {}) or {}
    for subsetores in mapa.values():
        for lista in (subsetores or {}).values():
            if chave in lista:
                return True
    return False


def _pct_para_filtro(valor, minimo):
    if minimo < 1 and valor >= 1:
        return minimo * 100
    return minimo


def eh_oportunidade_fii(pvp, dy, liquidez=None, vacancia=None, filtros=None):
    f = filtros or (getattr(config, "FILTROS_FIXOS", {}) or {}).get("fii") or {}
    try:
        pvp = float(pvp)
        dy = float(dy)
    except (TypeError, ValueError):
        return False
    if not (f.get("pvp_min", 0) <= pvp <= f.get("pvp_max", 1.05)):
        return False
    if dy < _pct_para_filtro(dy, f.get("dy_min", 0.09)):
        return False
    liq_min = f.get("liquidez_min")
    if liq_min is not None:
        try:
            if float(liquidez) < liq_min:
                return False
        except (TypeError, ValueError):
            return False
    vac_max = f.get("vacancia_max")
    if vac_max is not None and vacancia is not None:
        try:
            vac = float(vacancia)
        except (TypeError, ValueError):
            vac = None
        if vac is not None and vac > vac_max:
            return False
    return True


def eh_oportunidade_acao(pl, pvp, dy, roe, liquidez=None, ticker=None, filtros=None):
    f = filtros or (getattr(config, "FILTROS_FIXOS", {}) or {}).get("acao") or {}
    if ticker is not None and not ticker_no_mapa_b3(ticker):
        return False
    try:
        pl = float(pl)
        pvp = float(pvp)
        dy = float(dy)
        roe = float(roe)
    except (TypeError, ValueError):
        return False
    if not (f.get("pl_min", 3) <= pl <= f.get("pl_max", 12)):
        return False
    if not (f.get("pvp_min", 0.5) <= pvp <= f.get("pvp_max", 1.8)):
        return False
    if dy < _pct_para_filtro(dy, f.get("dy_min", 0.06)):
        return False
    if roe < _pct_para_filtro(roe, f.get("roe_min", 0.10)):
        return False
    liq_min = f.get("liquidez_min")
    if liq_min is not None:
        try:
            if float(liquidez) < liq_min:
                return False
        except (TypeError, ValueError):
            return False
    return True


def agrupar_linhas_por_empresa(itens, tipo="acao"):
    """Agrupa linhas de relatorio por empresa.

    ``itens``: lista de ``{"ticker": str, "corpo": str}``.
    Um ticker sozinho vira ``Petrobras (PETR4)`` no titulo.
    Dois ou mais da mesma raiz: nome em cima, tickers abaixo.
    """
    if not itens:
        return []
    por_ticker = {}
    for item in itens:
        chave = normalizar_ticker(item.get("ticker"))
        if not chave:
            continue
        por_ticker[chave] = item
    blocos = []
    for _raiz, membros in agrupar_tickers_por_empresa(list(por_ticker)):
        presentes = [t for t in membros if t in por_ticker]
        if not presentes:
            continue
        nome = _nome_entre(presentes, tipo)
        if len(presentes) == 1:
            item = por_ticker[presentes[0]]
            titulo = rotulo_ticker(presentes[0], tipo)
            corpo = item.get("corpo") or ""
            blocos.append(f"{titulo}\n{corpo}" if corpo else titulo)
        else:
            cabeca = nome or "/".join(presentes)
            partes = [f"*{cabeca}*"]
            for ticker in presentes:
                item = por_ticker[ticker]
                corpo = item.get("corpo") or ""
                partes.append(f"   {ticker}")
                if corpo:
                    for linha in str(corpo).splitlines():
                        partes.append(f"   {linha}" if not linha.startswith("   ") else linha)
            blocos.append("\n".join(partes))
    return blocos


def juntar_blocos(titulo, itens, tipo="acao"):
    linhas = agrupar_linhas_por_empresa(itens, tipo)
    if not linhas:
        return ""
    return f"{titulo}\n" + "\n\n".join(linhas)


__all__ = [
    "agrupar_linhas_por_empresa",
    "eh_oportunidade_acao",
    "eh_oportunidade_fii",
    "juntar_blocos",
    "nome_empresa",
    "obter_carteira_popular",
    "rotulo_grupo",
    "rotulo_ticker",
    "ticker_no_mapa_b3",
]
