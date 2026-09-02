"""Endpoints de leitura de relatórios (Fase 5, Etapa 10).

``GET /api/v1/relatorios`` — permissão ``relatorios.consultar``. Relatório
agregado de leitura construído exclusivamente com os dados já existentes no
banco (contagens por tipo/severidade/status). Não cria motor de relatórios.
"""
from datetime import datetime

from flask import Blueprint, g
from sqlalchemy import func

from api.auth import rota_protegida
from api.respostas import resposta_ok
from api.serializadores import _texto_tipo_ativo
from pipeline_dados.banco_dados import (
    AlertaEvento,
    Ativo,
    DocumentosQualitativos,
    IndicadorHistorico,
)

bp = Blueprint("api_relatorios", __name__)


def _contagem_por_grupo(sessao, modelo, coluna):
    """Conta registros do modelo agrupados por ``coluna`` (dict texto->total)."""
    resultado = {}
    for valor, total in sessao.query(coluna, func.count(modelo.id)).group_by(coluna):
        chave = _texto_tipo_ativo(valor)
        resultado[str(chave)] = int(total)
    return resultado


@bp.get("")
@rota_protegida("relatorios.consultar")
def relatorio_geral():
    """Resumo agregado de leitura dos dados existentes."""
    sessao = g.sessao

    ativos_total = sessao.query(func.count(Ativo.id)).scalar() or 0
    indicadores_total = sessao.query(func.count(IndicadorHistorico.id)).scalar() or 0
    alertas_total = sessao.query(func.count(AlertaEvento.id)).scalar() or 0
    documentos_total = sessao.query(func.count(DocumentosQualitativos.id)).scalar() or 0

    dados = {
        "gerado_em": datetime.now().isoformat(),
        "ativos": {
            "total": int(ativos_total),
            "por_tipo": _contagem_por_grupo(sessao, Ativo, Ativo.tipo),
        },
        "indicadores": {
            "total": int(indicadores_total),
            "por_tipo_ativo": _contagem_por_grupo(
                sessao, IndicadorHistorico, IndicadorHistorico.tipo_ativo
            ),
        },
        "alertas": {
            "total": int(alertas_total),
            "por_severidade": _contagem_por_grupo(
                sessao, AlertaEvento, AlertaEvento.severidade
            ),
            "por_tipo": _contagem_por_grupo(
                sessao, AlertaEvento, AlertaEvento.tipo_alerta
            ),
        },
        "documentos": {
            "total": int(documentos_total),
            "por_status": _contagem_por_grupo(
                sessao, DocumentosQualitativos, DocumentosQualitativos.status_processamento
            ),
        },
    }
    return resposta_ok(dados)
