"""Endpoints do usuário autenticado (Fase 5, Etapa 10).

``GET /api/v1/me`` — permissão ``conta.propria``. Retorna somente informações
não sensíveis do usuário autenticado, nunca ``senha_hash``, sessões, API Keys,
tokens ou segredos.
"""
from flask import Blueprint, g

from api.auth import rota_protegida
from api.respostas import resposta_ok
from api.serializadores import serializar_usuario

bp = Blueprint("api_usuarios", __name__)


@bp.get("/me")
@rota_protegida("conta.propria")
def usuario_atual():
    """Dados públicos e não sensíveis do usuário autenticado."""
    return resposta_ok(serializar_usuario(g.usuario))
