"""API de leitura para a Carteira Consolidada.

Não expõe credenciais, comandos administrativos, arquivos do Drive ou a conexão
do Neon. A conta Supabase é validada antes da consulta aos dados consolidados
pelo Robô Financeiro.
"""
from __future__ import annotations

import logging
import os
import re
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
            "monthly_dividend": _to_number(data.get("div_mensal")),
        },
        "classification": {
            "type": data.get("tipo"),
            "sector": data.get("setor"),
            "subsector": data.get("subsetor"),
        },
    }
    return jsonify({"data": payload})
