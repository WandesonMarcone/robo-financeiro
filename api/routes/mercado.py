"""Endpoints de leitura dos dados de mercado persistidos (Fase 7, Etapa 7.3).

Expõem via HTTP a camada de leitura de produção ``services/mercado``
(snapshots de mercado e dados contábeis persistidos). Somente leitura: nenhum
endpoint altera, cria ou apaga dados.

- ``GET /api/v1/mercado/snapshots`` — permissão ``dados.consultar``;
- ``GET /api/v1/mercado/snapshots/mais-recente`` — permissão ``dados.consultar``;
- ``GET /api/v1/mercado/dados-financeiros`` — permissão ``dados.consultar``.
"""
from datetime import date

from flask import Blueprint, g, request

from api import dependencias
from api.auth import rota_protegida
from api.respostas import resposta_erro, resposta_ok
from api.serializadores import serializar_dados_financeiros, serializar_snapshot
from services import mercado

bp = Blueprint("api_mercado", __name__)

TIPOS_ATIVO_VALIDOS = ("ACAO", "FII")


def _data_referencia_do_argumento():
    """Interpreta ``?data_referencia=YYYY-MM-DD``; None quando ausente."""
    bruto = request.args.get("data_referencia")
    if bruto is None or str(bruto).strip() == "":
        return None
    try:
        return date.fromisoformat(str(bruto).strip())
    except ValueError:
        raise ValueError(
            "Filtro 'data_referencia' inválido. Use o formato AAAA-MM-DD."
        ) from None


def _argumentos_snapshot():
    """Interpreta os filtros comuns de snapshot (ticker/ativo_id/tipo/data)."""
    ticker = request.args.get("ticker")
    ativo_id = dependencias.inteiro_do_argumento("ativo_id")
    tipo_ativo = request.args.get("tipo_ativo")
    if tipo_ativo:
        normalizado = str(tipo_ativo).strip().upper()
        if normalizado not in TIPOS_ATIVO_VALIDOS:
            raise ValueError("Filtro 'tipo_ativo' inválido. Use ACAO ou FII.")
        tipo_ativo = normalizado
    else:
        tipo_ativo = None
    data_referencia = _data_referencia_do_argumento()
    return ticker, ativo_id, tipo_ativo, data_referencia


@bp.get("/snapshots")
@rota_protegida("dados.consultar")
def listar_snapshots():
    """Lista os snapshots de mercado persistidos, com filtros seguros."""
    sessao = g.sessao
    try:
        ticker, ativo_id, tipo_ativo, data_referencia = _argumentos_snapshot()
        registros = mercado.obter_snapshots(
            ticker=ticker,
            ativo_id=ativo_id,
            tipo=tipo_ativo,
            data_referencia=data_referencia,
            limite=dependencias.obter_limite(),
            session=sessao,
        )
    except ValueError as exc:
        return resposta_erro(str(exc), 400)
    return resposta_ok(
        [serializar_snapshot(registro) for registro in registros],
        meta={"total": len(registros)},
    )


@bp.get("/snapshots/mais-recente")
@rota_protegida("dados.consultar")
def snapshot_mais_recente():
    """Snapshot de mercado mais recente do ativo filtrado (ou 404)."""
    sessao = g.sessao
    try:
        ticker, ativo_id, tipo_ativo, _ = _argumentos_snapshot()
        registro = mercado.obter_snapshot_mais_recente(
            ticker=ticker,
            ativo_id=ativo_id,
            tipo=tipo_ativo,
            session=sessao,
        )
    except ValueError as exc:
        return resposta_erro(str(exc), 400)
    if registro is None:
        return resposta_erro("Nenhum snapshot de mercado encontrado.", 404)
    return resposta_ok(serializar_snapshot(registro))


@bp.get("/dados-financeiros")
@rota_protegida("dados.consultar")
def listar_dados_financeiros():
    """Lista os dados contábeis persistidos (CVM), com filtros seguros."""
    sessao = g.sessao
    try:
        ticker, ativo_id, tipo_ativo, data_referencia = _argumentos_snapshot()
        tipo_doc = request.args.get("tipo_doc")
        registros = mercado.obter_dados_financeiros(
            ticker=ticker,
            ativo_id=ativo_id,
            tipo=tipo_ativo,
            tipo_doc=tipo_doc,
            data_referencia=data_referencia,
            limite=dependencias.obter_limite(),
            session=sessao,
        )
    except ValueError as exc:
        return resposta_erro(str(exc), 400)
    return resposta_ok(
        [serializar_dados_financeiros(registro) for registro in registros],
        meta={"total": len(registros)},
    )
