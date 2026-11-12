"""Recuperação auditável da taxonomia de FIIs que ficou sem segmento.

Não presume que todo FII seja de tijolo. A rotina usa o segmento publicado na
fonte estruturada, converte apenas quando a regra canônica tem evidência e
preserva classificações já existentes. Os casos sem evidência continuam
marcados para investigação; nunca são preenchidos com um palpite.
"""
from __future__ import annotations

import io
from datetime import datetime

from modules.taxonomia_fiis import MACROS_FII, classificar_fii, segmento_fii_canonico


VALORES_DESCONHECIDOS = {"", "N/D", "N/A", "NA", "-", "PENDENTE DE IA"}


def _desconhecido(valor: object) -> bool:
    return str(valor or "").strip().upper() in VALORES_DESCONHECIDOS


def resolver_classificacao(ticker: str, tipo_atual: object, segmento_atual: object,
                           segmento_fonte: object) -> tuple[str, str] | None:
    """Retorna classificação comprovada ou ``None`` se não houver evidência.

    Valores já válidos não são reescritos, o que protege correções manuais e
    evita que uma oscilação de fonte desfaça um setor confirmado.
    """
    tipo_existente = str(tipo_atual or "").strip()
    segmento_existente = str(segmento_atual or "").strip()
    if tipo_existente in MACROS_FII and not _desconhecido(segmento_existente):
        return None
    bruto = str(segmento_fonte or "").strip()
    if _desconhecido(bruto):
        return None
    tipo_fonte, segmento_fonte_canonico, _ = classificar_fii(bruto, ticker)
    tipo = tipo_existente if tipo_existente in MACROS_FII else tipo_fonte
    segmento = segmento_fii_canonico(bruto, tipo, ticker)
    if tipo not in MACROS_FII or _desconhecido(segmento):
        return None
    if tipo == tipo_existente and segmento == segmento_existente:
        return None
    return tipo, segmento


def segmentos_fundamentus():
    """Lê somente a coluna de segmento do resultado público do Fundamentus."""
    import pandas as pd
    from modules.utils import get_request_with_retry

    resposta = get_request_with_retry(
        "https://fundamentus.com.br/fii_resultado.php",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    tabela = pd.read_html(io.StringIO(resposta.text), decimal=",", thousands=".")[0]
    if "Papel" not in tabela.columns or "Segmento" not in tabela.columns:
        raise RuntimeError("segmento_indisponivel_na_fonte")
    resultado = {}
    for _, linha in tabela.iterrows():
        ticker = str(linha.get("Papel") or "").strip().upper()
        segmento = str(linha.get("Segmento") or "").strip()
        if ticker and not _desconhecido(segmento):
            resultado[ticker] = segmento
    return resultado


def corrigir_taxonomia_fiis(planilha=None, segmentos=None) -> dict:
    """Corrige apenas linhas FII sem taxonomia comprovada e retorna auditoria."""
    if planilha is None:
        import config
        from modules.utils import conectar_gspread
        planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
    if segmentos is None:
        segmentos = segmentos_fundamentus()
    aba = planilha.worksheet("BD_FIIs")
    linhas = aba.get_all_values()
    atualizacoes, resolvidos, sem_evidencia = [], [], []
    for indice, linha in enumerate(linhas[1:], start=2):
        ticker = str(linha[0] if linha else "").strip().upper()
        if not ticker:
            continue
        tipo_atual = linha[1] if len(linha) > 1 else ""
        segmento_atual = linha[2] if len(linha) > 2 else ""
        resolucao = resolver_classificacao(ticker, tipo_atual, segmento_atual, segmentos.get(ticker))
        if resolucao is None:
            if _desconhecido(tipo_atual) or _desconhecido(segmento_atual):
                sem_evidencia.append(ticker)
            continue
        tipo, segmento = resolucao
        atualizacoes.extend((
            {"range": f"B{indice}", "values": [[tipo]]},
            {"range": f"C{indice}", "values": [[segmento]]},
        ))
        resolvidos.append({"ticker": ticker, "tipo": tipo, "segmento": segmento,
                           "fonte": "FUNDAMENTUS_SEGMENTO"})
    if atualizacoes:
        aba.batch_update(atualizacoes, value_input_option="USER_ENTERED")
    return {
        "executado_em": datetime.now().isoformat(timespec="seconds"),
        "fonte": "FUNDAMENTUS_SEGMENTO",
        "corrigidos": resolvidos,
        "sem_evidencia": sem_evidencia,
        "quantidade_corrigida": len(resolvidos),
        "quantidade_sem_evidencia": len(sem_evidencia),
    }
