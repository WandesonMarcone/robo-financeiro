"""Endpoints de leitura de indicadores e histórico (Fase 5, Etapa 10).

- ``GET /api/v1/indicadores`` — permissão ``indicadores.consultar``;
- ``GET /api/v1/indicadores/<ativo_id>/historico`` — permissão
  ``historico.consultar`` (estado mais recente por indicador; não é série
  temporal — ``meta.serie_temporal = false``).
"""
from flask import Blueprint, g, request
from sqlalchemy.orm import joinedload

from api import dependencias
from api.auth import rota_protegida
from api.respostas import resposta_erro, resposta_ok
from api.serializadores import serializar_indicador
from pipeline_dados.banco_dados import Ativo, IndicadorHistorico

bp = Blueprint("api_indicadores", __name__)

TIPOS_ATIVO_VALIDOS = ("ACAO", "FII")


def _filtros(query):
    """Aplica os filtros seguros de indicadores à query."""
    ativo_id = dependencias.inteiro_do_argumento("ativo_id")
    if ativo_id is not None:
        query = query.filter(IndicadorHistorico.ativo_id == ativo_id)

    ticker = request.args.get("ticker")
    if ticker:
        query = query.filter(
            IndicadorHistorico.ativo.has(Ativo.ticker == str(ticker).strip().upper())
        )

    indicador = request.args.get("indicador")
    if indicador:
        query = query.filter(
            IndicadorHistorico.indicador == str(indicador).strip()
        )

    tipo_ativo = request.args.get("tipo_ativo")
    if tipo_ativo:
        normalizado = str(tipo_ativo).strip().upper()
        if normalizado not in TIPOS_ATIVO_VALIDOS:
            raise ValueError("Filtro 'tipo_ativo' inválido. Use ACAO ou FII.")
        query = query.filter(IndicadorHistorico.tipo_ativo == normalizado)

    return query


@bp.get("")
@rota_protegida("indicadores.consultar")
def listar_indicadores():
    """Lista o estado atual dos indicadores, com filtros seguros."""
    sessao = g.sessao
    try:
        query = _filtros(sessao.query(IndicadorHistorico))
    except ValueError as exc:
        return resposta_erro(str(exc), 400)

    page, page_size, offset = dependencias.obter_paginacao()
    total = query.count()
    registros = (
        query.options(joinedload(IndicadorHistorico.ativo))
        .order_by(IndicadorHistorico.tipo_ativo, IndicadorHistorico.indicador)
        .offset(offset)
        .limit(page_size)
        .all()
    )
    return resposta_ok(
        [serializar_indicador(registro) for registro in registros],
        meta=dependencias.meta_paginacao(total, page, page_size, len(registros)),
    )


@bp.get("/<int:ativo_id>/historico")
@rota_protegida("historico.consultar")
def historico_do_ativo(ativo_id):
    """Estado atual dos indicadores do ativo (não é série temporal)."""
    sessao = g.sessao
    ativo = sessao.get(Ativo, ativo_id)
    if ativo is None:
        return resposta_erro("Ativo não encontrado.", 404)

    query = sessao.query(IndicadorHistorico).filter(
        IndicadorHistorico.ativo_id == ativo_id
    )
    page, page_size, offset = dependencias.obter_paginacao()
    total = query.count()
    registros = (
        query.options(joinedload(IndicadorHistorico.ativo))
        .order_by(IndicadorHistorico.indicador)
        .offset(offset)
        .limit(page_size)
        .all()
    )
    meta = dependencias.meta_paginacao(total, page, page_size, len(registros))
    meta["ativo_id"] = ativo_id
    meta["ticker"] = ativo.ticker
    meta["serie_temporal"] = False
    return resposta_ok(
        [serializar_indicador(registro) for registro in registros],
        meta=meta,
    )
