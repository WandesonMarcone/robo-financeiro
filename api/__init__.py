"""Camada HTTP/API da Estratégia Fardada (Fase 5, Etapa 10).

Integração aditiva com o Flask existente em ``main.py``: um único Blueprint
registrado sob ``/api/v1``. Quando ``API_ENABLED`` está desabilitada (padrão),
nenhuma rota nem handler é registrado — o comportamento legado permanece 100%
intacto.
"""
import logging

from flask import request

import config
from api.blueprint import criar_blueprint_api
from api.respostas import resposta_erro

logger = logging.getLogger(__name__)

PREFIXO_API = "/api/v1"


def integrar_api(app, habilitada=None):
    """Integra a API ao Flask existente de forma aditiva.

    ``habilitada`` opcional; quando omitida, respeita ``config.API_ENABLED``.
    Retorna ``True`` quando a API foi integrada e ``False`` quando desabilitada.
    """
    if habilitada is None:
        habilitada = config.API_ENABLED
    if not habilitada:
        logger.info("API HTTP %s desabilitada (API_ENABLED).", PREFIXO_API)
        return False

    app.register_blueprint(criar_blueprint_api(), url_prefix=PREFIXO_API)
    _registrar_handlers_escopados(app)
    logger.info("API HTTP %s habilitada e integrada.", PREFIXO_API)
    return True


def _registrar_handlers_escopados(app):
    """Handlers de 404/405 aplicados somente ao prefixo da API.

    Rotas fora de ``/api/v1`` (webhook, página raiz etc.) preservam o
    comportamento padrão do Flask (HTML), evitando interferência legada.
    """

    @app.errorhandler(404)
    def _nao_encontrado(exc):
        if request.path.startswith(PREFIXO_API):
            return resposta_erro("Recurso não encontrado.", 404)
        return exc

    @app.errorhandler(405)
    def _metodo_nao_permitido(exc):
        if request.path.startswith(PREFIXO_API):
            return resposta_erro("Método não permitido.", 405)
        return exc
