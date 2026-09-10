"""Endpoints de leitura de documentos (Fase 5, Etapa 10).

``GET /api/v1/documentos`` — permissão ``documentos.consultar``. Filtros básicos
seguros: ``ativo_id``, ``ticker``, ``tipo_documento`` e ``status``. A resposta
nunca inclui ``texto_extraido``, ``resumo_ia``, ``log_erro`` nem arquivos.
"""
from flask import Blueprint, g, request
from sqlalchemy.orm import joinedload

from api import dependencias
from api.auth import rota_protegida
from api.respostas import resposta_erro, resposta_ok
from api.serializadores import serializar_documento
from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos

bp = Blueprint("api_documentos", __name__)


@bp.get("")
@rota_protegida("documentos.consultar")
def listar_documentos():
    """Lista metadados de documentos, sem conteúdo pesado."""
    sessao = g.sessao
    query = sessao.query(DocumentosQualitativos)

    try:
        ativo_id = dependencias.inteiro_do_argumento("ativo_id")
    except ValueError as exc:
        return resposta_erro(str(exc), 400)
    if ativo_id is not None:
        query = query.filter(DocumentosQualitativos.ativo_id == ativo_id)

    ticker = request.args.get("ticker")
    if ticker:
        query = query.filter(
            DocumentosQualitativos.ativo.has(Ativo.ticker == str(ticker).strip().upper())
        )

    tipo_documento = request.args.get("tipo_documento")
    if tipo_documento:
        query = query.filter(
            DocumentosQualitativos.tipo_documento == str(tipo_documento).strip()
        )

    status = request.args.get("status")
    if status:
        query = query.filter(
            DocumentosQualitativos.status_processamento == str(status).strip().upper()
        )

    page, page_size, offset = dependencias.obter_paginacao()
    total = query.count()
    registros = (
        query.options(joinedload(DocumentosQualitativos.ativo))
        .order_by(DocumentosQualitativos.data_publicacao.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )
    return resposta_ok(
        [serializar_documento(registro) for registro in registros],
        meta=dependencias.meta_paginacao(total, page, page_size, len(registros)),
    )
