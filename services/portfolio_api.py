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


@portfolio_api.get("/api/v1/health")
def health():
    return jsonify({"status": "ok", "service": "portfolio-market-readonly"})


@portfolio_api.get("/api/v1/assets/<ticker>")
@requires_portfolio_user
def asset(ticker: str):
    symbol = ticker.strip().upper()
    if not _TICKER.fullmatch(symbol):
        return jsonify({"message": "Ticker inválido."}), 400

    requested_type = (request.args.get("asset_type") or "").strip().lower()
    if requested_type in {"etf", "bdr"}:
        from services.coletor_etfs_bdrs import detalhe_instrumento_menu

        instrument, metrics = detalhe_instrumento_menu(symbol)
        if instrument is None or str(instrument.get("tipo") or "").lower() != requested_type:
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
