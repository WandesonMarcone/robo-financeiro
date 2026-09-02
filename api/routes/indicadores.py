"""Endpoints de leitura de indicadores e histórico (Fase 5, Etapa 10).

- ``GET /api/v1/indicadores`` — permissão ``indicadores.consultar``;
- ``GET /api/v1/indicadores/<ativo_id>/historico`` — permissão
  ``historico.consultar`` (expõe o estado histórico já armazenado).
"""
from flask import Blueprint, g, request

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
        termo = f"%{str(ticker).strip().upper()}%"
        query = query.join(Ativo).filter(Ativo.ticker.like(termo))

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

    limite = dependencias.obter_limite()
    registros = (
        query.order_by(IndicadorHistorico.tipo_ativo, IndicadorHistorico.indicador)
        .limit(limite)
        .all()
    )
    return resposta_ok(
        [serializar_indicador(registro) for registro in registros],
        meta={"total": len(registros)},
    )


@bp.get("/<int:ativo_id>/historico")
@rota_protegida("historico.consultar")
def historico_do_ativo(ativo_id):
    """Histórico existente de um ativo (somente leitura, dados não alterados)."""
    sessao = g.sessao
    ativo = sessao.get(Ativo, ativo_id)
    if ativo is None:
        return resposta_erro("Ativo não encontrado.", 404)

    query = sessao.query(IndicadorHistorico).filter(
        IndicadorHistorico.ativo_id == ativo_id
    )
    limite = dependencias.obter_limite()
    registros = query.order_by(IndicadorHistorico.indicador).limit(limite).all()
    return resposta_ok(
        [serializar_indicador(registro) for registro in registros],
        meta={
            "ativo_id": ativo_id,
            "ticker": ativo.ticker,
            "total": len(registros),
        },
    )
