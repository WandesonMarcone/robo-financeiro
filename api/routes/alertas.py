"""Endpoints de leitura de alertas (Fase 5, Etapa 10).

``GET /api/v1/alertas`` — permissão ``alertas.consultar``. Filtros básicos
seguros: ``ativo_id``, ``ticker``, ``tipo`` (tipo de alerta), ``severidade`` e
``tipo_ativo``. Somente leitura: nenhum alerta é alterado nesta etapa.
"""
from flask import Blueprint, g, request

from api import dependencias
from api.auth import rota_protegida
from api.respostas import resposta_erro, resposta_ok
from api.serializadores import serializar_alerta
from pipeline_dados.banco_dados import AlertaEvento, Ativo

bp = Blueprint("api_alertas", __name__)

TIPOS_ALERTA_VALIDOS = ("QUALIDADE", "MERCADO", "CRITICO")
SEVERIDADES_VALIDAS = ("OK", "WARNING", "ERRO", "CRITICO", "IGNORADO")
TIPOS_ATIVO_VALIDOS = ("ACAO", "FII")


@bp.get("")
@rota_protegida("alertas.consultar")
def listar_alertas():
    """Lista os eventos de alerta registrados, com filtros seguros."""
    sessao = g.sessao
    query = sessao.query(AlertaEvento)

    try:
        ativo_id = dependencias.inteiro_do_argumento("ativo_id")
    except ValueError as exc:
        return resposta_erro(str(exc), 400)
    if ativo_id is not None:
        query = query.filter(AlertaEvento.ativo_id == ativo_id)

    ticker = request.args.get("ticker")
    if ticker:
        termo = f"%{str(ticker).strip().upper()}%"
        query = query.join(Ativo).filter(Ativo.ticker.like(termo))

    tipo = request.args.get("tipo")
    if tipo:
        normalizado = str(tipo).strip().upper()
        if normalizado not in TIPOS_ALERTA_VALIDOS:
            return resposta_erro(
                "Filtro 'tipo' inválido. Use QUALIDADE, MERCADO ou CRITICO.", 400
            )
        query = query.filter(AlertaEvento.tipo_alerta == normalizado)

    severidade = request.args.get("severidade")
    if severidade:
        normalizado = str(severidade).strip().upper()
        if normalizado not in SEVERIDADES_VALIDAS:
            return resposta_erro(
                "Filtro 'severidade' inválido.", 400
            )
        query = query.filter(AlertaEvento.severidade == normalizado)

    tipo_ativo = request.args.get("tipo_ativo")
    if tipo_ativo:
        normalizado = str(tipo_ativo).strip().upper()
        if normalizado not in TIPOS_ATIVO_VALIDOS:
            return resposta_erro(
                "Filtro 'tipo_ativo' inválido. Use ACAO ou FII.", 400
            )
        query = query.filter(AlertaEvento.tipo_ativo == normalizado)

    limite = dependencias.obter_limite()
    registros = (
        query.order_by(AlertaEvento.data_evento.desc(), AlertaEvento.id.desc())
        .limit(limite)
        .all()
    )
    return resposta_ok(
        [serializar_alerta(registro) for registro in registros],
        meta={"total": len(registros)},
    )
