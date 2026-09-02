"""Endpoints de preferências individuais do usuário (Fase 6, Etapa 5).

Recursos privados 1:1: o proprietário é SEMPRE o usuário autenticado
(``g.usuario``). Não existe id de recurso vindo do cliente — ``usuario_id`` no
payload é rejeitado com 400 — portanto não há acesso cruzado entre usuários
(anti-IDOR/BOLA estrutural). Nenhuma regra de autorização é duplicada: apenas a
permissão ``preferencias.proprias`` da matriz central (``services/autorizacao``).

Não implementa notificações reais, envio Telegram, planos ou frontend — apenas
a persistência das preferências para etapas futuras.
"""
from flask import Blueprint, g, request

from api.auth import rota_protegida
from api.respostas import resposta_erro, resposta_ok
from api.serializadores import serializar_preferencias
from services import autorizacao, preferencias

bp = Blueprint("api_preferencias", __name__)


def _ip():
    """IP de origem da requisição para a trilha de auditoria."""
    return request.remote_addr


def _corpo():
    """Corpo JSON da requisição, tolerante a payloads ausentes/inválidos."""
    return request.get_json(silent=True) or {}


@bp.get("")
@rota_protegida("preferencias.proprias")
def consultar_preferencias():
    """Retorna as preferências do usuário autenticado (cria com defaults se ausente)."""
    try:
        preferencias_atual = preferencias.obter_ou_criar_preferencias(
            g.usuario, session=g.sessao
        )
    except autorizacao.PermissaoNegadaError:
        return resposta_erro("Acesso negado.", 403)
    except ValueError as exc:
        return resposta_erro(str(exc), 400)
    return resposta_ok(serializar_preferencias(preferencias_atual))


@bp.patch("")
@rota_protegida("preferencias.proprias")
def atualizar_preferencias():
    """Atualiza parcialmente as preferências do usuário autenticado.

    Valida rigorosamente booleanos, enums de frequência, campos proibidos e
    desconhecidos e valores nulos. ``usuario_id`` no payload é rejeitado.
    """
    corpo = _corpo()
    if not corpo:
        return resposta_erro(
            "Informe ao menos um campo válido para atualizar.", 400
        )
    try:
        preferencias_atual = preferencias.atualizar_preferencias(
            g.usuario, corpo, session=g.sessao, ip=_ip()
        )
    except autorizacao.PermissaoNegadaError:
        return resposta_erro("Acesso negado.", 403)
    except ValueError as exc:
        return resposta_erro(str(exc), 400)
    return resposta_ok(serializar_preferencias(preferencias_atual))


@bp.post("/restaurar")
@rota_protegida("preferencias.proprias")
def restaurar_preferencias():
    """Restaura os defaults seguros das preferências do usuário autenticado."""
    try:
        preferencias_atual = preferencias.restaurar_preferencias_padrao(
            g.usuario, session=g.sessao, ip=_ip()
        )
    except autorizacao.PermissaoNegadaError:
        return resposta_erro("Acesso negado.", 403)
    except ValueError as exc:
        return resposta_erro(str(exc), 400)
    return resposta_ok(
        serializar_preferencias(preferencias_atual), meta={"restaurado": True}
    )
