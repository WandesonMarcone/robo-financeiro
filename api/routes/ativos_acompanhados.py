"""Endpoints de ativos acompanhados pelo usuário (Fase 6, Etapa 4).

Recursos privados com dono: o proprietário é SEMPRE o usuário autenticado
(``g.usuario``) — ``usuario_id`` enviado pelo cliente é ignorado. O isolamento
é aplicado por ``services/escopo.py`` via ``buscar_recurso_escopado``: recurso
inexistente e recurso de outro usuário produzem a mesma resposta ``404``
(anti-IDOR/BOLA). Nenhuma regra de autorização é duplicada — apenas a
permissão ``ativos.proprios`` da matriz central e a política de escopo.
"""
from flask import Blueprint, g, request

from api.auth import rota_protegida
from api.respostas import resposta_erro, resposta_ok
from api.serializadores import serializar_acompanhamento
from services import ativos_acompanhados, autorizacao

bp = Blueprint("api_ativos_acompanhados", __name__)


def _ip():
    """IP de origem da requisição para a trilha de auditoria."""
    return request.remote_addr


def _corpo():
    """Corpo JSON da requisição, tolerante a payloads ausentes/inválidos."""
    return request.get_json(silent=True) or {}


def _interpretar_ativo_id(valor):
    """Interpreta ``ativo_id`` como inteiro positivo; ``None`` quando inválido.

    Booleano (subclasse de int em Python) e valores <= 0 são rejeitados.
    """
    if isinstance(valor, bool) or not isinstance(valor, int):
        return None
    if valor <= 0:
        return None
    return valor


@bp.get("")
@rota_protegida("ativos.proprios")
def listar_acompanhamentos():
    """Lista os ativos acompanhados pelo usuário autenticado."""
    registros = ativos_acompanhados.listar_acompanhamentos(
        g.usuario, session=g.sessao
    )
    return resposta_ok(
        [serializar_acompanhamento(registro) for registro in registros],
        meta={"total": len(registros)},
    )


@bp.post("")
@rota_protegida("ativos.proprios")
def adicionar_acompanhamento():
    """Adiciona um ativo ao acompanhamento do usuário autenticado.

    O proprietário é ``g.usuario`` — ``usuario_id`` no corpo é ignorado.
    """
    ativo_id = _interpretar_ativo_id(_corpo().get("ativo_id"))
    if ativo_id is None:
        return resposta_erro(
            "O campo 'ativo_id' é obrigatório e deve ser um inteiro positivo.", 400
        )
    try:
        registro = ativos_acompanhados.adicionar_acompanhamento(
            g.usuario, ativo_id, session=g.sessao, ip=_ip()
        )
    except autorizacao.PermissaoNegadaError:
        return resposta_erro("Acesso negado.", 403)
    except ValueError as exc:
        return resposta_erro(str(exc), 400)
    return resposta_ok(serializar_acompanhamento(registro), meta={"criado": True})


@bp.get("/<int:acompanhamento_id>")
@rota_protegida("ativos.proprios")
def consultar_acompanhamento(acompanhamento_id):
    """Consulta um acompanhamento pelo id, aplicando o escopo (anti-IDOR/BOLA)."""
    registro = ativos_acompanhados.buscar_acompanhamento(
        g.usuario, acompanhamento_id, session=g.sessao
    )
    if registro is None:
        return resposta_erro("Recurso não encontrado.", 404)
    return resposta_ok(serializar_acompanhamento(registro))


@bp.delete("/<int:acompanhamento_id>")
@rota_protegida("ativos.proprios")
def remover_acompanhamento(acompanhamento_id):
    """Remove um acompanhamento pelo id, aplicando o escopo (anti-IDOR/BOLA)."""
    removido = ativos_acompanhados.remover_acompanhamento(
        g.usuario, acompanhamento_id, session=g.sessao, ip=_ip()
    )
    if not removido:
        return resposta_erro("Recurso não encontrado.", 404)
    return resposta_ok({"removido": True, "id": acompanhamento_id})
