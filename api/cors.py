"""CORS da API HTTP (Fase 11, Etapa 11.2).

Allowlist explícita de origens do Website separado. Sem Flask-CORS, sem
wildcard ``*``, sem refletir Origin arbitrário. Aplicado somente ao prefixo
``/api/v1`` e somente quando a API está integrada (``API_ENABLED``).

Regras:
- origem permitida vem de ``config.API_CORS_ORIGINS`` (env ``API_CORS_ORIGINS``);
- comparação exata (scheme + host + porta); barra final é ignorada na config;
- lista vazia = nenhum ``Access-Control-Allow-Origin`` (fail-closed);
- ``*`` na env é descartado no parse e nunca ecoado;
- ``Access-Control-Allow-Credentials`` só é emitido junto de uma origem
  permitida concreta (nunca com ``*``);
- preflight OPTIONS de origem permitida responde 204; origem recusada não
  recebe cabeçalhos CORS (o browser bloqueia).
"""
from flask import request

import config

PREFIXO_API = "/api/v1"

CABECALHOS_PERMITIDOS = (
    "Accept",
    "Content-Type",
    "X-API-Key",
    "X-Session-Token",
)

METODOS_PERMITIDOS = "GET, POST, PATCH, DELETE, OPTIONS"

MAX_AGE_PREFLIGHT = "600"


def _normalizar_origem(origem):
    """Remove espaços e barra final; vazio ou ``*`` vira ``None``."""
    if not origem or not isinstance(origem, str):
        return None
    candidata = origem.strip().rstrip("/")
    if not candidata or candidata == "*":
        return None
    return candidata


def origem_permitida(origem, permitidas=None):
    """True quando ``origem`` está na allowlist (igualdade exata)."""
    candidata = _normalizar_origem(origem)
    if candidata is None:
        return False
    if permitidas is None:
        permitidas = config.API_CORS_ORIGINS
    return candidata in permitidas


def cabecalhos_cors(origem, permitidas=None):
    """Monta os cabeçalhos CORS para uma origem permitida, ou dict vazio.

    Ecoa a origem normalizada da allowlist (nunca ``*``). Credentials só
    acompanham origem concreta.
    """
    candidata = _normalizar_origem(origem)
    if candidata is None or not origem_permitida(candidata, permitidas=permitidas):
        return {}
    return {
        "Access-Control-Allow-Origin": candidata,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Headers": ", ".join(CABECALHOS_PERMITIDOS),
        "Access-Control-Allow-Methods": METODOS_PERMITIDOS,
        "Access-Control-Max-Age": MAX_AGE_PREFLIGHT,
        "Vary": "Origin",
    }


def _caminho_da_api():
    caminho = request.path or ""
    return caminho.startswith(PREFIXO_API)


def verificar_preflight_cors():
    """before_request: responde OPTIONS do prefixo da API sem autenticar."""
    if request.method != "OPTIONS" or not _caminho_da_api():
        return None
    origem = request.headers.get("Origin")
    cabecalhos = cabecalhos_cors(origem)
    if not cabecalhos:
        return ("", 403)
    return ("", 204, cabecalhos)


def aplicar_cors_na_resposta(resposta):
    """after_request: anexa CORS só quando a Origin está na allowlist."""
    if not _caminho_da_api():
        return resposta
    origem = request.headers.get("Origin")
    for nome, valor in cabecalhos_cors(origem).items():
        resposta.headers[nome] = valor
    return resposta


def registrar_cors(app):
    """Registra preflight e after_request no app Flask (somente API ligada)."""
    app.before_request(verificar_preflight_cors)
    app.after_request(aplicar_cors_na_resposta)
