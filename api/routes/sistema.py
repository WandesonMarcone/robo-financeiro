"""Endpoints públicos da API (Fase 5, Etapa 10).

``GET /api/v1/healthz`` — rota pública sem autenticação nem dados sensíveis,
usada apenas como verificação de vida da camada HTTP.
"""
from flask import Blueprint

from api.respostas import resposta_ok

bp = Blueprint("api_sistema", __name__)


@bp.get("/healthz")
def healthz():
    """Resposta pública de vida da API."""
    return resposta_ok({"status": "ok", "api": "v1"})
