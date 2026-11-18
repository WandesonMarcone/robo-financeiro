"""Contingência idempotente para fechamento EOD após a coleta principal."""
from __future__ import annotations

from datetime import datetime
import re
from zoneinfo import ZoneInfo

import config
from modules.eod_snapshots import tentar_persistir_eod
from modules.utils import buscar_indices_b3_ohlc, conectar_gspread
from pipeline_dados.repositorio_indices import persistir_indices_diarios
from pipeline_dados.repositorio_snapshots import auditar_cobertura_snapshots


def validar_frescor_planilha(planilha, dia):
    """Exige maioria de ativos com coleta intradiária nas duas abas."""
    for aba_nome, coluna in (("BD_Acoes", 32), ("BD_FIIs", 17)):
        linhas = planilha.worksheet(aba_nome).get_all_values()[1:]
        ativos = [linha for linha in linhas if linha and
                  re.fullmatch(r"[A-Z0-9]{4,10}", str(linha[0]).strip().upper())]
        if not ativos:
            raise RuntimeError(f"{aba_nome}: sem ativos cadastrados")
        recentes = 0
        for linha in ativos:
            carimbo = str(linha[coluna]).strip() if len(linha) > coluna else ""
            match = re.fullmatch(r"OK\s+(\d{2})/(\d{2})\s+(\d{2}):(\d{2})", carimbo)
            if match and (int(match[1]), int(match[2])) == (dia.day, dia.month) and int(match[3]) >= 10:
                recentes += 1
        if recentes / len(ativos) < 0.6:
            raise RuntimeError(
                f"{aba_nome}: somente {recentes}/{len(ativos)} ativos "
                "com atualização intradiária; snapshot omitido"
            )


def executar(agora=None, buscar_indices=None, abrir_planilha=None,
             salvar_snapshots=None, salvar_indices=None, validar_planilha=None,\n             auditar_cobertura=None):
    """Grava o fechamento somente se IFIX e Ibovespa têm vela de hoje."""
    agora = agora or datetime.now(ZoneInfo("America/Sao_Paulo"))
    buscar_indices = buscar_indices or buscar_indices_b3_ohlc
    salvar_snapshots = salvar_snapshots or tentar_persistir_eod
    salvar_indices = salvar_indices or persistir_indices_diarios
    auditar_cobertura = auditar_cobertura or auditar_cobertura_snapshots
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
    planilha = abrir_planilha()
    (validar_planilha or validar_frescor_planilha)(planilha, agora.date())
    resumo = salvar_snapshots(planilha, agora)
    if not resumo or not resumo.get("acoes_gravadas") or not resumo.get("fiis_gravados"):
        raise RuntimeError("Fechamento incompleto de ações ou FIIs; confira Sheets e Neon")
    for indice in ("IFIX", "Ibovespa"):
        salvar_indices([por_indice[indice]], agora.date())
    if resumo.get("omitidos_sem_ativo") or resumo.get("omitidos_sem_dados"):
        raise RuntimeError(
            "Fechamento parcial: "
            f"sem cadastro={resumo.get('tickers_sem_ativo', {})}; "
            f"sem indicadores={resumo.get('tickers_sem_dados', {})}"
        )

    # Só considerar o EOD completo quando cada ativo ativo do catálogo tiver
    # snapshot na mesma data. Isso detecta catálogo e Sheets divergentes.
    cobertura = auditar_cobertura(agora.date())
    if not cobertura.get("completa"):
        faltantes = cobertura.get("faltantes", {})
        raise RuntimeError(
            "Cobertura EOD divergente: "
            f"ações={cobertura.get('gravados', {}).get('acoes', 0)}/"
            f"{cobertura.get('esperados', {}).get('acoes', 0)} "
            f"faltando={faltantes.get('acoes', [])}; "
            f"FIIs={cobertura.get('gravados', {}).get('fiis', 0)}/"
            f"{cobertura.get('esperados', {}).get('fiis', 0)} "
            f"faltando={faltantes.get('fiis', [])}"
        )
    print(f"EOD {agora.date()}: ações={resumo.get('acoes_gravadas', 0)}, "
          f"FIIs={resumo.get('fiis_gravados', 0)}, índices=2.")
    return {"status": "gravado", "resumo": resumo, "indices": 2, "cobertura": cobertura}


if __name__ == "__main__":
    executar()
