"""Carteira popular, nomes de exibicao e filtro de oportunidades.

A carteira destacada nas varreduras vem do ranking real de favoritos
(``ativos_acompanhados``), nao de listas hardcoded. Nomes oficiais de acoes
vem do catalogo/CVM ou da captura Yahoo no scraper; nada e inventado. FII
exibe so o ticker. Oportunidades exigem liquidez e, nas acoes, ticker
mapeado na B3.
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
_TOKENS_B3 = (
    "ON", "PN", "PNA", "PNB", "PNC", "PND", "UNT", "UNIT",
    "NM", "N1", "N2", "N2M", "EJ", "ED", "EB", "EX",
)
_SUFIXOS_B3 = re.compile(
    r"[\s,\-/]+(?:" + "|".join(_TOKENS_B3) + r")\s*$",
    re.IGNORECASE,
)
_SUFIXO_COLADO = re.compile(
    r"(?<=[A-Za-z]{3})(?:ON|PN[A-D]?)\s*$",
    re.IGNORECASE,
)
_CACHE_NOMES = {}


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


def limpar_cache_nomes():
    """Limpa o cache da captura atual (testes / novo ciclo)."""
    _CACHE_NOMES.clear()


def _tirar_codigos_b3(texto):
    """Remove ON/PN/NM/EJ e afins (Yahoo/B3), inclusive colados (RENNERON)."""
    atual = str(texto or "").strip()
    while atual:
        novo = _SUFIXOS_B3.sub("", atual).strip(" .,")
        novo = _SUFIXO_COLADO.sub("", novo).strip(" .,")
        if novo == atual:
            break
        atual = novo
    return atual


def _encurtar_nome(nome):
    texto = re.sub(r"\s+", " ", str(nome or "")).strip()
    if not texto:
        return ""
    texto = _tirar_codigos_b3(texto)
    if " - " in texto:
        cauda = _tirar_codigos_b3(
            _SUFIXOS_SOCIETARIOS.sub("", texto.rsplit(" - ", 1)[-1]).strip(" .,")
        )
        if cauda and 1 <= len(cauda.split()) <= 3:
            texto = cauda
    texto = _tirar_codigos_b3(
        _SUFIXOS_SOCIETARIOS.sub("", texto).strip(" .,")
    )
    if not texto:
        return ""
    partes = texto.split()
    if len(partes) >= 3 and partes[0].casefold().startswith("petrol"):
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


def _nome_curto_empresa(emp):
    if emp is None:
        return None
    escolhido = (
        getattr(emp, "nome_comercial", None)
        or getattr(emp, "nome", None)
        or getattr(emp, "razao_social", None)
    )
    curto = _encurtar_nome(escolhido)
    return curto or None


def _nome_do_catalogo(ticker):
    try:
        resumo = _resumo_empresa(ticker)
    except Exception:
        logger.debug("Catalogo indisponivel para nome de %s", ticker, exc_info=True)
        return None
    if not resumo or not resumo.get("empresa"):
        return None
    return _nome_curto_empresa(resumo["empresa"])


def _cnpj_conhecido(ticker):
    chave = normalizar_ticker(ticker)
    if not chave:
        return None
    mapa = getattr(config, "MAPA_CNPJ_B3", {}) or {}
    for cnpj, tkr in mapa.items():
        if normalizar_ticker(tkr) == chave:
            return cnpj
    return None


def _nome_por_cnpj(ticker):
    """Nome oficial pelo CNPJ do mapa B3, mesmo se o ticker nao estiver vinculado."""
    cnpj = _cnpj_conhecido(ticker)
    if not cnpj:
        return None
    try:
        from pipeline_dados.repositorio_catalogo import RepositorioCatalogo

        emp = RepositorioCatalogo().obter_empresa_por_cnpj(cnpj)
    except Exception:
        logger.debug("Catalogo CNPJ indisponivel para %s", ticker, exc_info=True)
        return None
    return _nome_curto_empresa(emp)


def _persistir_nome_catalogo(ticker, longo, comercial):
    """Preenche nome comercial vazio da empresa ja cadastrada. Nao cria CNPJ."""
    comercial = str(comercial or "").strip()
    if not comercial:
        return
    try:
        from pipeline_dados.repositorio_catalogo import RepositorioCatalogo

        repo = RepositorioCatalogo()
        emp = repo.obter_empresa_por_ticker(ticker)
        if emp is None:
            return
        if getattr(emp, "nome_comercial", None):
            return
        repo.obter_ou_criar_empresa(
            nome=emp.nome,
            cnpj=emp.cnpj,
            nome_comercial=comercial,
            fonte="yahoo_finance",
            evidencia=f"Yahoo Finance ({ticker})",
        )
    except Exception:
        logger.debug("Persistencia de nome indisponivel para %s", ticker, exc_info=True)


def _candidato_limpo(valor, ticker):
    curto = _encurtar_nome(valor)
    if not curto:
        return None
    if curto.upper() == normalizar_ticker(ticker):
        return None
    if any(p.upper() in _TOKENS_B3 for p in curto.split()):
        curto = _tirar_codigos_b3(curto)
        if curto.isupper():
            curto = curto.title()
        curto = _encurtar_nome(curto)
    if not curto or curto.upper() == normalizar_ticker(ticker):
        return None
    return curto


def registrar_nome_capturado(ticker, fonte):
    """Cacheia e persiste o nome vindo do Yahoo (dict) ou de um texto.

    Prefere o nome comercial limpo (sem ON/PN/NM/EJ). ``shortName`` da B3
    costuma trazer classe e segmento; ``longName``/``displayName`` sao melhores.
    """
    chave = normalizar_ticker(ticker)
    if not chave:
        return None
    display = short = longn = None
    if isinstance(fonte, dict):
        display = fonte.get("displayName")
        short = fonte.get("shortName")
        longn = fonte.get("longName")
        ordem = (display, longn, short)
    else:
        ordem = (fonte,)
    curto = None
    for bruto in ordem:
        candidato = _candidato_limpo(bruto, chave)
        if candidato:
            curto = candidato
            break
    if not curto:
        return None
    _CACHE_NOMES[chave] = curto
    raiz = raiz_ticker(chave)
    if raiz:
        _CACHE_NOMES.setdefault(raiz, curto)
    _persistir_nome_catalogo(chave, longn or display or short or curto, curto)
    return curto


def nome_empresa(ticker, tipo="acao"):
    """Nome oficial curto, ou ``None`` se nao houver fonte (nao inventa).

    FII nao usa nome comercial: a exibicao e so o ticker.
    """
    if tipo == "fii":
        return None
    chave = normalizar_ticker(ticker)
    if not chave:
        return None
    irmaos = _tickers_mesma_empresa(chave)
    for candidato in irmaos:
        cached = _CACHE_NOMES.get(candidato)
        if cached:
            return cached
    raiz = raiz_ticker(chave)
    if raiz and raiz in _CACHE_NOMES:
        return _CACHE_NOMES[raiz]
    for candidato in irmaos:
        curto = _nome_do_catalogo(candidato)
        if curto:
            return curto
    for candidato in irmaos:
        curto = _nome_por_cnpj(candidato)
        if curto:
            return curto
    return None


def rotulo_ticker(ticker, tipo="acao"):
    """Acao: ``Petrobras (PETR4)``. FII: so o ticker."""
    chave = normalizar_ticker(ticker) or str(ticker or "").strip().upper()
    if tipo == "fii":
        return chave
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
    "limpar_cache_nomes",
    "nome_empresa",
    "obter_carteira_popular",
    "registrar_nome_capturado",
    "rotulo_grupo",
    "rotulo_ticker",
    "ticker_no_mapa_b3",
]
