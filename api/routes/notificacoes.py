"""Endpoints de consulta de notificações individualizadas (Fase 6, Etapa 6).

Recursos privados com dono: o proprietário é SEMPRE o usuário autenticado
(``g.usuario``) — ``usuario_id`` enviado pelo cliente é ignorado. O isolamento
é aplicado por ``services/escopo.py`` via ``buscar_recurso_escopado``:
notificação inexistente e notificação de outro usuário produzem a mesma
resposta ``404`` (anti-IDOR/BOLA). Nenhuma regra de autorização é duplicada —
apenas a permissão ``notificacoes.consultar`` da matriz central.

Somente leitura e estado (listar/consultar/marcar lida/excluir): a GERAÇÃO de
notificações é responsabilidade do motor central (``services/notificacoes``),
nunca desta API.
"""
from flask import Blueprint, g, request

from api.auth import rota_protegida
from api.respostas import resposta_erro, resposta_ok
from api.serializadores import serializar_notificacao
from services import notificacoes

bp = Blueprint("api_notificacoes", __name__)


def _ip():
    """IP de origem da requisição para a trilha de auditoria."""
    return request.remote_addr


@bp.get("")
@rota_protegida("notificacoes.consultar")
def listar_notificacoes():
    """Lista as notificações do usuário autenticado, com filtros seguros.

    Filtros opcionais: ``tipo`` (catálogo controlado), ``status`` (estados
    controlados) e ``nao_lidas`` (booleano). Valores inválidos retornam 400.
    """
    tipo = request.args.get("tipo")
    status = request.args.get("status")
    nao_lidas = request.args.get("nao_lidas")
    if nao_lidas is not None and str(nao_lidas).strip().lower() not in ("1", "true"):
        return resposta_erro("O parâmetro 'nao_lidas' deve ser '1' ou 'true'.", 400)
    try:
        registros = notificacoes.listar_notificacoes(
            g.usuario,
            session=g.sessao,
            tipo=tipo,
            status=status,
            nao_lidas=bool(nao_lidas),
        )
    except ValueError as exc:
        return resposta_erro(str(exc), 400)
    return resposta_ok(
        [serializar_notificacao(registro) for registro in registros],
        meta={"total": len(registros)},
    )


@bp.get("/<int:notificacao_id>")
@rota_protegida("notificacoes.consultar")
def consultar_notificacao(notificacao_id):
    """Consulta uma notificação pelo id, aplicando o escopo (anti-IDOR/BOLA)."""
    registro = notificacoes.buscar_notificacao(
        g.usuario, notificacao_id, session=g.sessao
    )
    if registro is None:
        return resposta_erro("Recurso não encontrado.", 404)
    return resposta_ok(serializar_notificacao(registro))


@bp.post("/ler-todas")
@rota_protegida("notificacoes.consultar")
def marcar_todas_lidas():
    """Marca TODAS as notificações não lidas do usuário autenticado como lidas.

    Opera somente sobre as notificações do próprio usuário — nunca sobre as de
    terceiros. Retorna a quantidade marcada em ``meta.total``.
    """
    total = notificacoes.marcar_todas_como_lida(
        g.usuario, session=g.sessao, ip=_ip()
    )
    return resposta_ok({"marcadas": total}, meta={"total": total})


@bp.post("/<int:notificacao_id>/lida")
@rota_protegida("notificacoes.consultar")
def marcar_notificacao_lida(notificacao_id):
    """Marca uma notificação como lida, aplicando o escopo (anti-IDOR/BOLA)."""
    registro = notificacoes.marcar_como_lida(
        g.usuario, notificacao_id, session=g.sessao, ip=_ip()
    )
    if registro is None:
        return resposta_erro("Recurso não encontrado.", 404)
    return resposta_ok(serializar_notificacao(registro), meta={"lida": True})


@bp.delete("/<int:notificacao_id>")
@rota_protegida("notificacoes.consultar")
def excluir_notificacao(notificacao_id):
    """Exclui uma notificação, aplicando o escopo (anti-IDOR/BOLA)."""
    excluida = notificacoes.excluir_notificacao(
        g.usuario, notificacao_id, session=g.sessao, ip=_ip()
    )
    if not excluida:
        return resposta_erro("Recurso não encontrado.", 404)
    return resposta_ok({"removido": True, "id": notificacao_id})
