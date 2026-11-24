"""API de leitura para a Carteira Consolidada.

Não expõe credenciais, comandos administrativos, arquivos do Drive ou a conexão
do Neon. A conta Supabase é validada antes da consulta aos dados consolidados
pelo Robô Financeiro.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date, timedelta
from functools import wraps

import requests
from flask import Blueprint, jsonify, request

portfolio_api = Blueprint("portfolio_api", __name__)
logger = logging.getLogger(__name__)
_TICKER = re.compile(r"^[A-Z0-9._-]{1,16}$")
_MARKET_TYPES = {
    "etf": "ETF", "bdr": "BDR", "crypto": "CRIPTO", "cripto": "CRIPTO",
    "currency": "MOEDA", "moeda": "MOEDA", "index": "INDICE", "indice": "INDICE",
    "commodity": "COMMODITY",
}
_ASSET_CLASSES = {
    "stock": "ACAO", "action": "ACAO", "acao": "ACAO",
    "fii": "FII", "etf": "ETF", "bdr": "BDR",
    "crypto": "CRIPTO", "cripto": "CRIPTO",
    "currency": "MOEDA", "moeda": "MOEDA",
}


def _origins() -> set[str]:
    raw = os.environ.get("PORTFOLIO_WEB_ORIGINS", "")
    return {value.strip().rstrip("/") for value in raw.split(",") if value.strip()}


def _cors(response):
    origin = (request.headers.get("Origin") or "").rstrip("/")
    if origin and origin in _origins():
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        response.headers["Vary"] = "Origin"
    return response


@portfolio_api.after_request
def apply_cors(response):
    return _cors(response)


@portfolio_api.before_request
def preflight():
    if request.method == "OPTIONS":
        return _cors(jsonify({"ok": True}))
    return None


def _supabase_user(token: str) -> dict | None:
    url = (os.environ.get("PORTFOLIO_SUPABASE_URL") or "").rstrip("/")
    key = (os.environ.get("PORTFOLIO_SUPABASE_PUBLISHABLE_KEY") or "").strip()
    if not url or not key:
        return None
    try:
        response = requests.get(
            f"{url}/auth/v1/user",
            headers={"apikey": key, "Authorization": f"Bearer {token}"},
            timeout=8,
        )
        return response.json() if response.status_code == 200 else None
    except requests.RequestException:
        logger.warning("Não foi possível validar sessão da Carteira.")
        return None


def requires_portfolio_user(function):
    @wraps(function)
    def protected(*args, **kwargs):
        token = (request.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        if not os.environ.get("PORTFOLIO_SUPABASE_URL") or not os.environ.get("PORTFOLIO_SUPABASE_PUBLISHABLE_KEY"):
            return jsonify({"message": "Integração da Carteira não configurada no Render."}), 503
        if not token or not _supabase_user(token):
            return jsonify({"message": "Sessão da Carteira não autorizada."}), 401
        return function(*args, **kwargs)
    return protected


def _to_number(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("R$", "").replace("%", "").replace(" ", "")
    if "." in text and "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _period_days(default=30):
    try:
        return max(7, min(int(request.args.get("days") or default), 730)), None
    except ValueError:
        return None, (jsonify({"message": "Período inválido."}), 400)


def _requested_class(required=False):
    value = (request.args.get("asset_type") or "").strip().lower()
    asset_class = _ASSET_CLASSES.get(value)
    if required and not asset_class:
        return None, (jsonify({"message": "Informe asset_type válido."}), 400)
    if value and not asset_class:
        return None, (jsonify({"message": "Classe de ativo inválida."}), 400)
    return asset_class, None


@portfolio_api.get("/api/v1/health")
def health():
    return jsonify({"status": "ok", "service": "portfolio-market-readonly"})


@portfolio_api.get("/api/v1/market/overview")
@requires_portfolio_user
def market_overview():
    """Macro, índices e Tesouro já consolidados pelo mesmo robô."""
    from services.painel_mercado import resumo_mercado

    data = resumo_mercado()
    return jsonify({"data": data, "source": "robo_financeiro"})


@portfolio_api.get("/api/v1/assets/<ticker>")
@requires_portfolio_user
def asset(ticker: str):
    symbol = ticker.strip().upper()
    if not _TICKER.fullmatch(symbol):
        return jsonify({"message": "Ticker inválido."}), 400

    requested_type = (request.args.get("asset_type") or "").strip().lower()
    if requested_type in _MARKET_TYPES:
        from services.coletor_etfs_bdrs import detalhe_instrumento_menu

        instrument, metrics = detalhe_instrumento_menu(symbol)
        if instrument is None or str(instrument.get("tipo") or "").upper() != _MARKET_TYPES[requested_type]:
            return jsonify({"data": None, "message": "Ativo ainda sem dados consolidados pelo Robô."}), 404
        metric_map = {
            str(item.get("chave")): _to_number(item.get("valor_numerico"))
            for item in metrics
        }
        return jsonify({"data": {
            "ticker": symbol,
            "asset_type": requested_type,
            "price": _to_number(instrument.get("fechamento")),
            "updated_at": (
                instrument.get("referencia_em").isoformat()
                if hasattr(instrument.get("referencia_em"), "isoformat")
                else instrument.get("referencia_em")
            ),
            "source": "robo_financeiro",
            "indicators": {
                "dy": metric_map.get("dividend_yield"),
                "pvp": metric_map.get("p_vp"),
                "pl": metric_map.get("p_l"),
                "roe": metric_map.get("roe"),
                "volatility_30d": metric_map.get("volatilidade_30d"),
                "liquidity_30d_brl": metric_map.get("liquidez_media_30d_brl"),
                "distance_from_52w_high": metric_map.get("distancia_maxima_1a"),
            },
            "classification": {
                "type": instrument.get("tipo"),
                "sector": None,
                "subsector": instrument.get("indice_referencia"),
            },
        }})
    is_fii = requested_type == "fii"

    # A planilha consolidada é o dado operacional mais atual. Ela usa os mesmos
    # pipelines e a mesma base SQL/Neon já mantidos pelo Robô Financeiro.
    from services.planilhas import buscar_ativo_na_planilha
    data = buscar_ativo_na_planilha(symbol, is_fii)
    if data is None and not is_fii:
        data = buscar_ativo_na_planilha(symbol, False)
    if data is None:
        return jsonify({"data": None, "message": "Ativo ainda sem dados consolidados pelo Robô."}), 404

    payload = {
        "ticker": symbol,
        "asset_type": "fii" if is_fii else (requested_type or "stock"),
        "price": _to_number(data.get("preco")),
        "updated_at": data.get("atualizado_em"),
        "source": "robo_financeiro",
        "indicators": {
            "dy": _to_number(data.get("dy")),
            "pvp": _to_number(data.get("pvp")),
            "pl": _to_number(data.get("pl")),
            "roe": _to_number(data.get("roe")),
            "vpa": _to_number(data.get("vpa")),
            "lpa": _to_number(data.get("lpa")),
            "monthly_dividend": _to_number(data.get("div_mensal")),
        },
        "classification": {
            "type": data.get("tipo"),
            "sector": data.get("setor"),
            "subsector": data.get("subsetor"),
        },
    }
    return jsonify({"data": payload})


@portfolio_api.get("/api/v1/assets/<ticker>/history")
@requires_portfolio_user
def asset_history(ticker: str):
    """Série EOD existente no Neon, limitada a dois anos e sem preenchimento fictício."""
    symbol = ticker.strip().upper()
    if not _TICKER.fullmatch(symbol):
        return jsonify({"message": "Ticker inválido."}), 400
    requested_type = (request.args.get("asset_type") or "").strip().lower()
    try:
        days = max(7, min(int(request.args.get("days") or 365), 730))
    except ValueError:
        return jsonify({"message": "Período inválido."}), 400
    is_fii = requested_type == "fii"

    if requested_type in _MARKET_TYPES:
        from sqlalchemy import text
        from atualizador_documentos import SessionDB

        since = date.today() - timedelta(days=days)
        session = SessionDB()
        try:
            rows = session.execute(text("""
                SELECT o.referencia_em, o.fechamento, o.variacao_percentual
                FROM observacoes_instrumentos_internacionais o
                JOIN instrumentos_internacionais i ON i.id=o.instrumento_id
                WHERE UPPER(i.ticker)=:ticker AND i.tipo=:tipo
                  AND o.referencia_em >= :desde
                ORDER BY o.referencia_em ASC
            """), {"ticker": symbol, "tipo": _MARKET_TYPES[requested_type], "desde": since}).mappings().all()
            points = [{
                "date": row["referencia_em"].date().isoformat(),
                "price": float(row["fechamento"]) if row["fechamento"] is not None else None,
                "change_percent": float(row["variacao_percentual"]) if row["variacao_percentual"] is not None else None,
            } for row in rows if row["fechamento"] is not None]
        finally:
            session.close()
        coverage = {
            "requested_days": days,
            "points": len(points),
            "first_date": points[0]["date"] if points else None,
            "last_date": points[-1]["date"] if points else None,
            "source": "neon_market_eod",
        }
        return jsonify({"data": points, "coverage": coverage})

    from sqlalchemy import func
    from atualizador_documentos import SessionDB
    from pipeline_dados.banco_dados import Ativo
    from pipeline_dados.modelos_snapshots import SnapshotAcao, SnapshotFii

    model = SnapshotFii if is_fii else SnapshotAcao
    since = date.today() - timedelta(days=days)
    session = SessionDB()
    try:
        rows = (
            session.query(model)
            .join(Ativo, model.ativo_id == Ativo.id)
            .filter(func.upper(Ativo.ticker) == symbol)
            .filter(model.data_referencia >= since)
            .order_by(model.data_referencia.asc())
            .all()
        )
        points = [
            {
                "date": row.data_referencia.isoformat(),
                "price": float(row.preco) if row.preco is not None else None,
                "dy": float(row.dy) if row.dy is not None else None,
                "pvp": float(row.pvp) if row.pvp is not None else None,
            }
            for row in rows
            if row.preco is not None
        ]
    finally:
        session.close()

    coverage = {
        "requested_days": days,
        "points": len(points),
        "first_date": points[0]["date"] if points else None,
        "last_date": points[-1]["date"] if points else None,
        "source": "neon_eod_snapshots",
    }
    return jsonify({"data": points, "coverage": coverage})


@portfolio_api.get("/api/v1/assets/<ticker>/income")
@requires_portfolio_user
def asset_income(ticker: str):
    """Distribuições por cota/ação; fonte e qualidade nunca são ocultadas."""
    symbol = ticker.strip().upper()
    if not _TICKER.fullmatch(symbol):
        return jsonify({"message": "Ticker inválido."}), 400
    asset_class, error = _requested_class()
    if error:
        return error
    days, error = _period_days()
    if error:
        return error
    from sqlalchemy import text
    from atualizador_documentos import SessionDB

    since = date.today() - timedelta(days=days)
    session = SessionDB()
    try:
        rows = session.execute(text("""
            SELECT data_ex,data_pagamento,tipo,valor_unitario,moeda,fonte,qualidade_fonte
            FROM proventos_ativos
            WHERE ticker=:ticker AND data_ex>=:desde
              AND (:classe IS NULL OR classe=:classe)
            ORDER BY data_ex ASC, tipo ASC
        """), {"ticker": symbol, "desde": since, "classe": asset_class}).mappings().all()
    finally:
        session.close()
    data = [{
        "ex_date": row["data_ex"].isoformat(),
        "payment_date": row["data_pagamento"].isoformat() if row["data_pagamento"] else None,
        "type": row["tipo"], "amount_per_unit": float(row["valor_unitario"]),
        "currency": row["moeda"], "source": row["fonte"],
        "source_quality": row["qualidade_fonte"],
    } for row in rows]
    return jsonify({"data": data, "coverage": {"requested_days": days, "events": len(data)}})


@portfolio_api.get("/api/v1/assets/<ticker>/corporate-events")
@requires_portfolio_user
def asset_corporate_events(ticker: str):
    symbol = ticker.strip().upper()
    if not _TICKER.fullmatch(symbol):
        return jsonify({"message": "Ticker inválido."}), 400
    asset_class, error = _requested_class()
    if error:
        return error
    days, error = _period_days()
    if error:
        return error
    from sqlalchemy import text
    from atualizador_documentos import SessionDB

    since = date.today() - timedelta(days=days)
    session = SessionDB()
    try:
        rows = session.execute(text("""
            SELECT data_referencia,tipo,fator,descricao,fonte,qualidade_fonte
            FROM eventos_corporativos_ativos
            WHERE ticker=:ticker AND data_referencia>=:desde
              AND (:classe IS NULL OR classe=:classe)
            ORDER BY data_referencia ASC, tipo ASC
        """), {"ticker": symbol, "desde": since, "classe": asset_class}).mappings().all()
    finally:
        session.close()
    data = [{
        "date": row["data_referencia"].isoformat(), "type": row["tipo"],
        "factor": float(row["fator"]) if row["fator"] is not None else None,
        "description": row["descricao"], "source": row["fonte"],
        "source_quality": row["qualidade_fonte"],
    } for row in rows]
    return jsonify({"data": data, "coverage": {"requested_days": days, "events": len(data)}})


@portfolio_api.get("/api/v1/assets/<ticker>/performance")
@requires_portfolio_user
def asset_performance(ticker: str):
    """Retorno do ativo, não da carteira pessoal.

    O total simples supõe uma unidade mantida durante todo o período, sem
    reinvestimento, impostos ou corretagem. A Carteira calcula TWR/XIRR a partir
    das transações do usuário.
    """
    symbol = ticker.strip().upper()
    if not _TICKER.fullmatch(symbol):
        return jsonify({"message": "Ticker inválido."}), 400
    asset_class, error = _requested_class(required=True)
    if error:
        return error
    days, error = _period_days()
    if error:
        return error
    from sqlalchemy import text
    from atualizador_documentos import SessionDB

    since = date.today() - timedelta(days=days)
    session = SessionDB()
    try:
        if asset_class in {"ACAO", "FII"}:
            table = "snapshots_acoes" if asset_class == "ACAO" else "snapshots_fiis"
            prices = session.execute(text(f"""
                SELECT s.data_referencia AS data,s.preco
                FROM {table} s JOIN ativos a ON a.id=s.ativo_id
                WHERE UPPER(a.ticker)=:ticker AND s.data_referencia>=:desde AND s.preco IS NOT NULL
                ORDER BY s.data_referencia ASC
            """), {"ticker": symbol, "desde": since}).mappings().all()
        elif asset_class in {"ETF", "BDR", "CRIPTO", "MOEDA"}:
            prices = session.execute(text("""
                SELECT o.referencia_em AS data,o.fechamento AS preco
                FROM observacoes_instrumentos_internacionais o
                JOIN instrumentos_internacionais i ON i.id=o.instrumento_id
                WHERE UPPER(i.ticker)=:ticker AND i.tipo=:classe
                  AND o.referencia_em>=:desde AND o.fechamento IS NOT NULL
                ORDER BY o.referencia_em ASC
            """), {"ticker": symbol, "classe": asset_class, "desde": since}).mappings().all()
        else:
            prices = []
        income = session.execute(text("""
            SELECT COALESCE(SUM(valor_unitario),0) AS total
            FROM proventos_ativos
            WHERE ticker=:ticker AND classe=:classe AND data_ex>=:desde
        """), {"ticker": symbol, "classe": asset_class, "desde": since}).scalar_one()
    finally:
        session.close()
    if len(prices) < 2:
        return jsonify({"data": None, "message": "Histórico insuficiente no período."}), 404
    start_price, end_price = float(prices[0]["preco"]), float(prices[-1]["preco"])
    income_per_unit = float(income or 0)
    price_return = ((end_price / start_price) - 1) * 100
    income_return = (income_per_unit / start_price) * 100
    return jsonify({"data": {
        "ticker": symbol, "asset_type": asset_class.lower(), "requested_days": days,
        "first_date": str(prices[0]["data"])[:10], "last_date": str(prices[-1]["data"])[:10],
        "price_start": start_price, "price_end": end_price,
        "price_return_percent": price_return, "income_per_unit": income_per_unit,
        "income_return_percent": income_return,
        "simple_total_return_percent": price_return + income_return,
        "method": "buy_and_hold_one_unit_without_reinvestment",
        "personalized_portfolio_return": False,
    }})
