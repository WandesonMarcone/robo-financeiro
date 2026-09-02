"""Factory do Blueprint único da API (Fase 5, Etapa 10).

Agrupa os Blueprints por recurso sob um único Blueprint ``/api/v1``. Erros não
tratados são convertidos em resposta JSON genérica (sem stack trace) pelo
handler de exceções registrado aqui.
"""
import logging

from flask import Blueprint

from api.respostas import resposta_erro
from api.routes import (
    alertas,
    ativos,
    documentos,
    indicadores,
    relatorios,
    sistema,
    usuarios,
)

logger = logging.getLogger(__name__)


def criar_blueprint_api():
    """Monta e retorna o Blueprint da API com todas as rotas registradas."""
    bp = Blueprint("api_v1", __name__)

    bp.register_blueprint(ativos.bp, url_prefix="/ativos")
    bp.register_blueprint(indicadores.bp, url_prefix="/indicadores")
    bp.register_blueprint(alertas.bp, url_prefix="/alertas")
    bp.register_blueprint(documentos.bp, url_prefix="/documentos")
    bp.register_blueprint(relatorios.bp, url_prefix="/relatorios")
    bp.register_blueprint(usuarios.bp)
    bp.register_blueprint(sistema.bp)

    @bp.errorhandler(Exception)
    def _erro_inesperado(exc):
        logger.exception("Erro interno não tratado na API: %s", exc)
        return resposta_erro("Erro interno do servidor.", 500)

    return bp
