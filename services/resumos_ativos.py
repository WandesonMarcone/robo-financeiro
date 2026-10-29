"""Geracao em lote e substituicao do resumo atual de cada ativo."""

import json
import logging
from datetime import datetime

from atualizador_documentos import SessionDB
from pipeline_dados.banco_dados import Ativo, TipoAtivo
from pipeline_dados.modelos_resumos import ResumoAtivo

logger = logging.getLogger("robo.resumos")


def _fontes(fatos):
    return json.dumps([str(f) for f in (fatos or [])], ensure_ascii=False)


def gerar_resumos_ativos():
    """Gera/substitui resumos de todos os ativos cadastrados.

    Cada ativo faz commit isolado para que uma falha não descarte os demais.
    A fonte do resumo é registrada em ``fontes`` para auditoria.
    """
    from services.dashboard_menus import _fatos_para_resumo
    from modules.module_ia import gerar_resumo_painel
    from services.planilhas import buscar_ativo_na_planilha

    resultado = {
        "total": 0,
        "gerados": 0,
        "sem_fatos": 0,
        "erros": 0,
        "por_tipo": {"FII": 0, "ACAO": 0},
    }
    session = SessionDB()
    try:
        ativos = session.query(Ativo).order_by(Ativo.ticker).all()
        resultado["total"] = len(ativos)
        for ativo in ativos:
            ticker = str(ativo.ticker or "").strip().upper()
            tipo = (
                "fii"
                if ativo.tipo == TipoAtivo.FII or str(ativo.tipo).upper().endswith("FII")
                else "acao"
            )
            try:
                indicadores = buscar_ativo_na_planilha(ticker, tipo == "fii")
                fatos = _fatos_para_resumo(ticker, tipo, indicadores)
                if not fatos:
                    resultado["sem_fatos"] += 1
                    continue
                resumo = (gerar_resumo_painel(ticker, tipo, fatos) or "").strip()
                if not resumo:
                    resultado["sem_fatos"] += 1
                    continue
                registro = (
                    session.query(ResumoAtivo)
                    .filter(ResumoAtivo.ativo_id == ativo.id)
                    .first()
                )
                if registro is None:
                    registro = ResumoAtivo(ativo_id=ativo.id, resumo=resumo)
                    session.add(registro)
                registro.resumo = resumo
                registro.fontes = _fontes(fatos)
                registro.modelo = "cadeia_configurada"
                registro.status = "GERADO"
                registro.gerado_em = datetime.utcnow()
                registro.erro = None
                session.commit()
                resultado["gerados"] += 1
                resultado["por_tipo"]["FII" if tipo == "fii" else "ACAO"] += 1
            except Exception as erro:
                session.rollback()
                resultado["erros"] += 1
                logger.warning("Falha no resumo de %s", ticker, exc_info=True)
        return resultado
    finally:
        session.close()


def mensagem_resultado_resumos(resultado):
    return (
        "🤖 Geração de resumos concluída.\n\n"
        f"Ativos examinados: {resultado.get('total', 0)}\n"
        f"Resumos gravados/substituídos: {resultado.get('gerados', 0)}\n"
        f"Sem fatos suficientes: {resultado.get('sem_fatos', 0)}\n"
        f"Erros: {resultado.get('erros', 0)}\n"
        f"FIIs: {resultado.get('por_tipo', {}).get('FII', 0)}\n"
        f"Ações: {resultado.get('por_tipo', {}).get('ACAO', 0)}"
    )
