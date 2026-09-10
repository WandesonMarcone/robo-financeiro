"""Endpoints de leitura de ativos (Fase 5, Etapa 10).

``GET /api/v1/ativos`` — permissão ``dados.consultar``. Filtros básicos
seguros: ``tipo`` (ACAO/FII) e ``ticker`` (igualdade exata, identificador).
"""
from flask import Blueprint, g, request
from sqlalchemy.orm import joinedload

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
        query = query.filter(Ativo.ticker == str(ticker).strip().upper())

    page, page_size, offset = dependencias.obter_paginacao()
    total = query.count()
    registros = (
        query.options(joinedload(Ativo.perfil))
        .order_by(Ativo.ticker)
        .offset(offset)
        .limit(page_size)
        .all()
    )
    return resposta_ok(
        [serializar_ativo(registro) for registro in registros],
        meta=dependencias.meta_paginacao(total, page, page_size, len(registros)),
    )
