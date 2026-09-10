"""Rate limit in-process da API (Fase 9, Etapa 9.4).

Contador em memória por processo: sem Redis, sem Flask-Limiter, sem infra
nova. Adequado a um único worker; em múltiplos processos o teto é por
instância. ``healthz`` fica fora. Em ``TESTING`` o limite só vale quando
``API_RATE_LIMIT_EM_TESTE`` está ligado (a suíte não deve 429).
"""
from collections import defaultdict, deque
from threading import Lock
from time import monotonic

from flask import current_app, request

from api.respostas import resposta_erro
import config

_JANELA_SEGUNDOS = 60.0
_cadeados = Lock()
_janelas = defaultdict(deque)

ROTAS_AUTH = ("/api/v1/auth/login", "/api/v1/auth/register")


def _limpar(fila, agora):
    corte = agora - _JANELA_SEGUNDOS
    while fila and fila[0] <= corte:
        fila.popleft()


def permitir(chave, teto):
    """True se a chave ainda cabe no teto da janela de 60s."""
    if teto is None or teto <= 0:
        return True
    agora = monotonic()
    with _cadeados:
        fila = _janelas[chave]
        _limpar(fila, agora)
        if len(fila) >= teto:
            return False
        fila.append(agora)
        return True


def resetar():
    """Zera o estado in-process (testes)."""
    with _cadeados:
        _janelas.clear()


def _identidade():
    return (request.remote_addr or "desconhecido").strip() or "desconhecido"


def _caminho():
    return (request.path or "").rstrip("/") or "/"


def _teto_da_rota(caminho):
    if caminho in ROTAS_AUTH:
        return int(config.RATE_LIMIT_AUTH_POR_MINUTO)
    return int(config.RATE_LIMIT_API_POR_MINUTO)


def verificar_rate_limit():
    """before_request: 429 quando o teto da janela foi atingido."""
    caminho = _caminho()
    if not caminho.startswith("/api/v1"):
        return None
    if caminho == "/api/v1/healthz":
        return None
    if current_app.config.get("TESTING") and not current_app.config.get(
        "API_RATE_LIMIT_EM_TESTE"
    ):
        return None
    teto = _teto_da_rota(caminho)
    if teto <= 0:
        return None
    chave = f"{_identidade()}|{caminho if caminho in ROTAS_AUTH else 'api'}"
    if permitir(chave, teto):
        return None
    return resposta_erro("Limite de requisições excedido. Tente novamente em instantes.", 429)


def registrar_rate_limit(app):
    """Registra o before_request no app Flask (só nas rotas da API)."""
    app.before_request(verificar_rate_limit)
