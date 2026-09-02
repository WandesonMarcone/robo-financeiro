"""Endpoints de carteira/posições por usuário (Fase 6, Etapa 4).

Recursos privados com dono: o proprietário é SEMPRE o usuário autenticado
(``g.usuario``) — ``usuario_id`` enviado pelo cliente é ignorado. O isolamento
é aplicado por ``services/escopo.py`` via ``buscar_recurso_escopado``: recurso
inexistente e recurso de outro usuário produzem a mesma resposta ``404``
(anti-IDOR/BOLA). Nenhuma regra de autorização é duplicada — apenas a
permissão ``carteira.propria`` da matriz central e a política de escopo.
"""
from flask import Blueprint, g, request

from api.auth import rota_protegida
from api.respostas import resposta_erro, resposta_ok
from api.serializadores import serializar_posicao
from services import autorizacao, carteira

bp = Blueprint("api_carteira", __name__)


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
@rota_protegida("carteira.propria")
def listar_posicoes():
    """Lista as posições da carteira do usuário autenticado."""
    registros = carteira.listar_posicoes(g.usuario, session=g.sessao)
    return resposta_ok(
        [serializar_posicao(registro) for registro in registros],
        meta={"total": len(registros)},
    )


@bp.post("")
@rota_protegida("carteira.propria")
def adicionar_posicao():
    """Cria uma posição na carteira do usuário autenticado.

    O proprietário é ``g.usuario`` — ``usuario_id`` no corpo é ignorado.
    """
    corpo = _corpo()
    ativo_id = _interpretar_ativo_id(corpo.get("ativo_id"))
    if ativo_id is None:
        return resposta_erro(
            "O campo 'ativo_id' é obrigatório e deve ser um inteiro positivo.", 400
        )
    try:
        posicao = carteira.adicionar_posicao(
            g.usuario,
            ativo_id,
            corpo.get("quantidade"),
            corpo.get("preco_medio"),
            session=g.sessao,
            ip=_ip(),
        )
    except autorizacao.PermissaoNegadaError:
        return resposta_erro("Acesso negado.", 403)
    except ValueError as exc:
        return resposta_erro(str(exc), 400)
    return resposta_ok(serializar_posicao(posicao), meta={"criado": True})


@bp.get("/<int:posicao_id>")
@rota_protegida("carteira.propria")
def consultar_posicao(posicao_id):
    """Consulta uma posição pelo id, aplicando o escopo (anti-IDOR/BOLA)."""
    posicao = carteira.buscar_posicao(g.usuario, posicao_id, session=g.sessao)
    if posicao is None:
        return resposta_erro("Recurso não encontrado.", 404)
    return resposta_ok(serializar_posicao(posicao))


@bp.patch("/<int:posicao_id>")
@rota_protegida("carteira.propria")
def atualizar_posicao(posicao_id):
    """Atualiza quantidade e/ou preço médio, aplicando o escopo (anti-IDOR/BOLA)."""
    corpo = _corpo()
    if not any(campo in corpo for campo in ("quantidade", "preco_medio")):
        return resposta_erro(
            "Informe 'quantidade' e/ou 'preco_medio' para atualizar.", 400
        )
    try:
        posicao = carteira.atualizar_posicao(
            g.usuario,
            posicao_id,
            quantidade=corpo.get("quantidade"),
            preco_medio=corpo.get("preco_medio"),
            session=g.sessao,
            ip=_ip(),
        )
    except ValueError as exc:
        return resposta_erro(str(exc), 400)
    if posicao is None:
        return resposta_erro("Recurso não encontrado.", 404)
    return resposta_ok(serializar_posicao(posicao))


@bp.delete("/<int:posicao_id>")
@rota_protegida("carteira.propria")
def remover_posicao(posicao_id):
    """Remove uma posição pelo id, aplicando o escopo (anti-IDOR/BOLA)."""
    removida = carteira.remover_posicao(
        g.usuario, posicao_id, session=g.sessao, ip=_ip()
    )
    if not removida:
        return resposta_erro("Recurso não encontrado.", 404)
    return resposta_ok({"removido": True, "id": posicao_id})
