"""Contingência idempotente para fechamento EOD após a coleta principal."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import config
from modules.eod_snapshots import tentar_persistir_eod
from modules.utils import buscar_indices_b3_ohlc, conectar_gspread
from pipeline_dados.repositorio_indices import persistir_indices_diarios


def executar(agora=None, buscar_indices=None, abrir_planilha=None,
             salvar_snapshots=None, salvar_indices=None):
    """Grava o fechamento somente se IFIX e Ibovespa têm vela de hoje."""
    agora = agora or datetime.now(ZoneInfo("America/Sao_Paulo"))
    buscar_indices = buscar_indices or buscar_indices_b3_ohlc
    salvar_snapshots = salvar_snapshots or tentar_persistir_eod
    salvar_indices = salvar_indices or persistir_indices_diarios
    registros = buscar_indices()
    por_indice = {
        item.get("indice"): item for item in registros or []
        if item.get("data_pregao") == agora.date()
        and item.get("fechamento") is not None
    }
    if not por_indice:
        print("Fechamento ainda não confirmado no Yahoo para esta data; sem gravação.")
        return {"status": "sem_pregao_confirmado"}
    faltando = {"IFIX", "Ibovespa"} - por_indice.keys()
    if faltando:
        raise RuntimeError("Fechamento incompleto: " + ", ".join(sorted(faltando)))

    if abrir_planilha is None:
        abrir_planilha = lambda: conectar_gspread().open_by_url(config.SPREADSHEET_URL)
    resumo = salvar_snapshots(abrir_planilha(), agora)
    if not resumo or not (resumo.get("acoes_gravadas") or resumo.get("fiis_gravados")):
        raise RuntimeError("Nenhum snapshot EOD gravado; confira Sheets e Neon")
    for indice in ("IFIX", "Ibovespa"):
        salvar_indices([por_indice[indice]], agora.date())
    print(f"EOD {agora.date()}: ações={resumo.get('acoes_gravadas', 0)}, "
          f"FIIs={resumo.get('fiis_gravados', 0)}, índices=2.")
    return {"status": "gravado", "resumo": resumo, "indices": 2}


if __name__ == "__main__":
    executar()
