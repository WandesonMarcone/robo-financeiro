"""Descoberta controlada de ETFs, BDRs e criptomoedas.

As fontes servem para localizar candidatos. Antes do cadastro, o símbolo é
validado por cotação e registrado no Neon; a planilha recebe um espelho
recuperável, sem que uma indisponibilidade temporária do Sheets descarte o
candidato qualificado.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
import re

import requests

from services.coletor_etfs_bdrs import registrar_instrumento
from services.planilha_instrumentos import listar_tickers_planilha


URL_LISTA_BRAPI = "https://brapi.dev/api/quote/list"
URL_MERCADO_CRIPTO = "https://api.coingecko.com/api/v3/coins/markets"
STABLECOINS = frozenset({"USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDE", "PYUSD"})


def _get_json(url, *, params=None, headers=None, get=requests.get):
    resposta = get(url, params=params, headers=headers or {}, timeout=35)
    resposta.raise_for_status()
    return resposta.json()


def candidatos_b3(tipo, get=requests.get):
    tipo = str(tipo or "").upper()
    if tipo not in {"ETF", "BDR"}:
        raise ValueError("tipo B3 inválido")
    subtipo = "etf" if tipo == "ETF" else "bdr"
    payload = _get_json(
        URL_LISTA_BRAPI,
        params={
            "subType": subtipo, "limit": "2000", "sortBy": "volume",
            "sortOrder": "desc",
        },
        get=get,
    )
    candidatos = []
    for item in payload.get("stocks") or []:
        ticker = str(item.get("stock") or "").strip().upper()
        if not ticker or str(item.get("subType") or "").lower() != subtipo:
            continue
        preco = item.get("close")
        volume = item.get("volume")
        if preco in (None, 0) or volume in (None, 0):
            continue
        candidatos.append({
            "ticker": ticker,
            "tipo": tipo,
            "nome": item.get("name") or ticker,
            "simbolo_yahoo": f"{ticker}.SA",
            "dados_planilha": {
                "fechamento": preco,
                "variacao_percentual": item.get("change"),
                "volume": volume,
                "fonte": "BRAPI_LISTA_ATIVOS",
                "referencia_em": payload.get("requestedAt"),
            },
        })
    return candidatos


def candidatos_cripto(get=requests.get):
    headers = {}
    chave = (os.getenv("COINGECKO_API_KEY") or "").strip()
    if chave:
        headers["x-cg-demo-api-key"] = chave
    payload = _get_json(
        URL_MERCADO_CRIPTO,
        params={
            "vs_currency": "brl", "order": "market_cap_desc",
            "per_page": "25", "page": "1", "sparkline": "false",
        },
        headers=headers,
        get=get,
    )
    candidatos = []
    for item in payload or []:
        simbolo = str(item.get("symbol") or "").strip().upper()
        ranking = item.get("market_cap_rank")
        # A coluna ticker do catálogo aceita até 12 caracteres. Símbolos do
        # CoinGecko podem conter nomes internos com '_' (ex.: FIGR_HELOC),
        # que não são pares negociáveis no Yahoo e ainda estouram o limite ao
        # receber o sufixo BRL. Esses itens não devem entrar no catálogo.
        if (
            not re.fullmatch(r"[A-Z0-9]{2,9}", simbolo)
            or simbolo in STABLECOINS
            or not ranking
            or int(ranking) > 20
        ):
            continue
        preco = item.get("current_price")
        volume = item.get("total_volume")
        if preco in (None, 0) or not volume or float(volume) < 50_000_000:
            continue
        candidatos.append({
            "ticker": f"{simbolo}BRL",
            "tipo": "CRIPTO",
            "nome": item.get("name") or simbolo,
            "simbolo_yahoo": f"{simbolo}-USD",
            "simbolo_exterior": f"{simbolo}-USD",
            "dados_planilha": {
                "fechamento": preco,
                "variacao_percentual": item.get("price_change_percentage_24h"),
                "volume": volume,
                "fonte": "COINGECKO_MERCADO",
                "referencia_em": item.get("last_updated") or datetime.now(timezone.utc),
            },
        })
    return candidatos


def descobrir_e_cadastrar(tipo, limite=3, *, planilha=None, get=requests.get,
                           registrar=registrar_instrumento):
    tipo = str(tipo or "").strip().upper()
    limite = max(0, min(int(limite), 10))
    # A planilha é a lista visível, mas uma indisponibilidade transitória não
    # pode paralisar o cadastro no Neon. O upsert central impede duplicidade
    # e a próxima sincronização repõe o espelho.
    espelho_lista = "OK"
    try:
        existentes = listar_tickers_planilha(tipo, planilha=planilha)
    except Exception:
        existentes = set()
        espelho_lista = "PENDENTE"
    candidatos = candidatos_cripto(get=get) if tipo == "CRIPTO" else candidatos_b3(tipo, get=get)
    novos = []
    falhas = []
    for item in candidatos:
        if item["ticker"] in existentes or len(novos) >= limite:
            continue
        try:
            registro = registrar(
                item["ticker"], tipo,
                simbolo_exterior=item.get("simbolo_exterior"),
                simbolo_yahoo=item.get("simbolo_yahoo"),
                nome=item.get("nome"),
                fonte_cadastro="DESCOBERTA_AUTOMATICA",
                planilha=planilha,
                dados_planilha=item.get("dados_planilha"),
            )
            novos.append({"ticker": item["ticker"], "registro": registro})
            existentes.add(item["ticker"])
        except Exception as exc:
            falhas.append({"ticker": item["ticker"], "erro": type(exc).__name__})
    return {
        "tipo": tipo, "encontrados": len(candidatos), "adicionados": novos,
        "falhas": falhas, "ordem_persistencia": "NEON_ANTES_PLANILHA",
        "espelho_lista": espelho_lista,
    }

