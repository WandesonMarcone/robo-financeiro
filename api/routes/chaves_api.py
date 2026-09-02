"""Endpoints de autogerenciamento de API Keys (Correção 2).

Recursos privados com dono: o dono é SEMPRE o usuário autenticado
(``g.usuario``). Nenhum ``usuario_id`` enviado pelo cliente é aceito — o escopo
é aplicado pela própria camada de serviços (``services/chaves_api.py``), que
filtra por ``usuario_id`` e devolve ``None``/vazio para chaves de terceiros
(anti-IDOR/BOLA, indistinguível de inexistente).

Reutiliza integralmente ``services/chaves_api.py``: nenhuma lógica de hash,
validação ou autorização é duplicada aqui. A permissão ``conta.propria`` da
matriz central (``services/autorizacao.py``) protege os endpoints — o RBAC não
é alterado e nenhuma permissão nova é criada.

Garantias:
- a chave original é retornada SOMENTE na criação, nunca depois;
- nenhuma resposta inclui ``chave_hash`` nem a chave original;
- consulta/revogação de chave de outro usuário responde ``404``;
- a auditoria registra as operações sensíveis (``API_KEY_CRIADA`` e
  ``API_KEY_REVOGADA``) sem chave nem hash — registrada pelo serviço.
"""
from datetime import datetime

from flask import Blueprint, g, request

from api.auth import rota_protegida
from api.respostas import resposta_erro, resposta_ok
from api.serializadores import serializar_chave_api
from services import chaves_api

bp = Blueprint("api_chaves_api", __name__)

# Permissão de escopo próprio já existente na matriz central (não altera RBAC).
PERMISSAO_PROPRIA = "conta.propria"


def _ip():
    """IP de origem da requisição para a trilha de auditoria."""
    return request.remote_addr


def _corpo():
    """Corpo JSON da requisição, tolerante a payloads ausentes/inválidos."""
    return request.get_json(silent=True) or {}


def _interpretar_expira_em(valor):
    """Interpreta ``expira_em`` (ISO 8601) de forma tolerante.

    Retorna ``None`` quando ausente/vazio, um ``datetime`` válido, ou uma
    ``resposta_erro`` (tuple) quando o valor não é uma data válida.
    """
    if valor is None or not str(valor).strip():
        return None
    try:
        return datetime.fromisoformat(str(valor).strip())
    except ValueError:
        return resposta_erro(
            "O campo 'expira_em' deve ser uma data ISO 8601 válida.", 400
        )


@bp.post("")
@rota_protegida(PERMISSAO_PROPRIA)
def criar_api_key():
    """Gera uma nova API Key para o usuário autenticado (exposição única).

    A chave original é devolvida apenas aqui e nunca é persistida (somente o
    hash SHA-256, pela camada de serviço). O ``usuario_id`` de terceiros
    enviado no corpo é ignorado: o dono é sempre ``g.usuario``.
    """
    corpo = _corpo()
    rotulo = corpo.get("rotulo")
    if not rotulo or not str(rotulo).strip():
        return resposta_erro("O rótulo da API Key é obrigatório.", 400)

    expira_em = _interpretar_expira_em(corpo.get("expira_em"))
    if isinstance(expira_em, tuple):
        return expira_em

    try:
        chave = chaves_api.criar_chave_api(
            g.usuario,
            rotulo,
            expira_em=expira_em,
            autor=g.usuario,
            session=g.sessao,
            ip=_ip(),
        )
    except ValueError as exc:
        return resposta_erro(str(exc), 400)

    return resposta_ok({"chave": chave}, meta={"criada": True})


@bp.get("")
@rota_protegida(PERMISSAO_PROPRIA)
def listar_api_keys():
    """Lista os metadados das próprias API Keys (nunca a chave nem o hash)."""
    registros = chaves_api.listar_chaves_api(
        g.usuario, autor=g.usuario, session=g.sessao
    )
    return resposta_ok(
        [serializar_chave_api(registro) for registro in registros],
        meta={"total": len(registros)},
    )


@bp.get("/<int:chave_id>")
@rota_protegida(PERMISSAO_PROPRIA)
def consultar_api_key(chave_id):
    """Consulta o estado/metadados de uma chave própria (anti-IDOR/BOLA).

    Chave inexistente e chave de outro usuário produzem a mesma resposta
    ``404`` — nenhuma informação sobre a existência de chaves de terceiros.
    """
    registro = chaves_api.buscar_chave_api(
        g.usuario, chave_id, autor=g.usuario, session=g.sessao
    )
    if registro is None:
        return resposta_erro("Recurso não encontrado.", 404)
    return resposta_ok(serializar_chave_api(registro))


@bp.delete("/<int:chave_id>")
@rota_protegida(PERMISSAO_PROPRIA)
def revogar_api_key(chave_id):
    """Revoga a própria API Key (imediato e irreversível).

    O filtro da camada de serviço inclui ``usuario_id``: uma chave de outro
    usuário retorna ``False`` e a resposta é ``404`` (anti-IDOR/BOLA). A
    auditoria ``API_KEY_REVOGADA`` é registrada sem segredos pelo serviço.
    """
    revogada = chaves_api.revogar_chave_api(
        g.usuario, chave_id, autor=g.usuario, session=g.sessao, ip=_ip()
    )
    if not revogada:
        return resposta_erro("Recurso não encontrado.", 404)
    return resposta_ok({"removido": True, "id": chave_id})
