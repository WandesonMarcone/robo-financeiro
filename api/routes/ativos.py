"""Endpoints de leitura de ativos (Fase 5, Etapa 10).

``GET /api/v1/ativos`` — permissão ``dados.consultar``. Filtros básicos
seguros: ``tipo`` (ACAO/FII) e ``ticker`` (busca parcial).
"""
from flask import Blueprint, g, request

from api import dependencias
from api.auth import rota_protegida
from api.respostas import resposta_erro, resposta_ok
from api.serializadores import serializar_ativo
from pipeline_dados.banco_dados import Ativo, TipoAtivo

bp = Blueprint("api_ativos", __name__)

TIPOS_VALIDOS = (TipoAtivo.ACAO.name, TipoAtivo.FII.name)


@bp.get("")
@rota_protegida("dados.consultar")
def listar_ativos():
    """Lista os ativos disponíveis com metadados de perfil."""
    sessao = g.sessao
    query = sessao.query(Ativo)

    tipo = request.args.get("tipo")
    if tipo:
        tipo_normalizado = str(tipo).strip().upper()
        if tipo_normalizado not in TIPOS_VALIDOS:
            return resposta_erro("Filtro 'tipo' inválido. Use ACAO ou FII.", 400)
        query = query.filter(Ativo.tipo == TipoAtivo[tipo_normalizado])

    ticker = request.args.get("ticker")
    if ticker:
        termo = f"%{str(ticker).strip().upper()}%"
        query = query.filter(Ativo.ticker.like(termo))

    limite = dependencias.obter_limite()
    registros = query.order_by(Ativo.ticker).limit(limite).all()
    return resposta_ok(
        [serializar_ativo(registro) for registro in registros],
        meta={"total": len(registros)},
    )
