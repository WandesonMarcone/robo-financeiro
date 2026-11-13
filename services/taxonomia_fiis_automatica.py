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
from services.taxonomia_controlada import melhor_evidencia_fii


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


def _documentos_por_ticker():
    """Lê somente documentos oficiais que já foram persistidos pelo robô."""
    from atualizador_documentos import SessionDB
    from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos, TipoAtivo
    sessao = SessionDB()
    try:
        linhas = sessao.query(Ativo.ticker, DocumentosQualitativos).join(
            DocumentosQualitativos, DocumentosQualitativos.ativo_id == Ativo.id
        ).filter(
            Ativo.tipo == TipoAtivo.FII,
            DocumentosQualitativos.status_processamento == "SALVO_DRIVE",
        ).order_by(DocumentosQualitativos.data_publicacao.desc()).all()
        resultado = {}
        for ticker, documento in linhas:
            resultado.setdefault(str(ticker).upper(), []).append(documento)
        return resultado
    finally:
        sessao.close()


def _tickers_manualmente_bloqueados():
    """Retorna ajustes do administrador, sem exigir que a migração exista."""
    from sqlalchemy import text
    from atualizador_documentos import SessionDB
    sessao = SessionDB()
    try:
        linhas = sessao.execute(text("""
            SELECT upper(a.ticker) AS ticker
            FROM sobreposicoes_manuais_ativos s
            JOIN ativos a ON a.id = s.ativo_id
            WHERE s.bloqueado IS TRUE
        """)).mappings().all()
        return {linha["ticker"] for linha in linhas}
    except Exception:
        sessao.rollback()
        return set()
    finally:
        sessao.close()


def _registrar_evidencias(evidencias):
    """Persiste auditoria se a migração já estiver instalada; não bloqueia coleta."""
    if not evidencias:
        return
    from sqlalchemy import text
    from atualizador_documentos import SessionDB
    sessao = SessionDB()
    try:
        for item in evidencias:
            sessao.execute(text("""
                INSERT INTO evidencias_taxonomia_ativos
                (ativo_id, classe, segmento, fonte, documento_id, trecho, confianca, aplicado)
                VALUES (:ativo_id, :classe, :segmento, :fonte, :documento_id, :trecho, :confianca, :aplicado)
            """), item)
        sessao.commit()
    except Exception:
        sessao.rollback()
    finally:
        sessao.close()


def corrigir_taxonomia_fiis(planilha=None, segmentos=None, usar_contingencia=False) -> dict:
    """Corrige N/D com documento oficial; Fundamentus é contingência opt-in."""
    if planilha is None:
        import config
        from modules.utils import conectar_gspread
        planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
    try:
        documentos = _documentos_por_ticker()
    except Exception:
        # Sem Neon disponível não há prova documental. A rotina não pode
        # "compensar" inventando uma classe.
        documentos = {}
    try:
        bloqueados_manuais = _tickers_manualmente_bloqueados()
    except Exception:
        bloqueados_manuais = set()
    if usar_contingencia and segmentos is None:
        segmentos = segmentos_fundamentus()
    segmentos = segmentos or {}
    aba = planilha.worksheet("BD_FIIs")
    linhas = aba.get_all_values()
    atualizacoes, resolvidos, sem_evidencia, auditoria = [], [], [], []
    for indice, linha in enumerate(linhas[1:], start=2):
        ticker = str(linha[0] if linha else "").strip().upper()
        if not ticker:
            continue
        if ticker in bloqueados_manuais:
            continue
        tipo_atual = linha[1] if len(linha) > 1 else ""
        segmento_atual = linha[2] if len(linha) > 2 else ""
        evidencia_doc = melhor_evidencia_fii(documentos.get(ticker, []))
        fonte, documento_id, trecho = None, None, None
        if evidencia_doc:
            evidencia, documento = evidencia_doc
            resolucao = resolver_classificacao(ticker, tipo_atual, segmento_atual, evidencia.segmento)
            fonte, documento_id, trecho = evidencia.fonte, documento.id, evidencia.trecho
        else:
            resolucao = resolver_classificacao(ticker, tipo_atual, segmento_atual, segmentos.get(ticker))
            if resolucao:
                fonte = "FUNDAMENTUS_SEGMENTO_CONTINGENCIA"
        if resolucao is None:
            if _desconhecido(tipo_atual) or _desconhecido(segmento_atual):
                sem_evidencia.append(ticker)
            continue
        tipo, segmento = resolucao
        atualizacoes.extend((
            {"range": f"B{indice}", "values": [[tipo]]},
            {"range": f"C{indice}", "values": [[segmento]]},
        ))
        resolvidos.append({"ticker": ticker, "tipo": tipo, "segmento": segmento, "fonte": fonte})
        if documento_id:
            auditoria.append({"ativo_id": next((getattr(d, "ativo_id", None) for d in documentos.get(ticker, []) if d.id == documento_id), None),
                              "classe": tipo, "segmento": segmento, "fonte": fonte,
                              "documento_id": documento_id, "trecho": trecho,
                              "confianca": "ALTA", "aplicado": True})
    if atualizacoes:
        aba.batch_update(atualizacoes, value_input_option="USER_ENTERED")
    _registrar_evidencias([item for item in auditoria if item["ativo_id"]])
    return {
        "executado_em": datetime.now().isoformat(timespec="seconds"),
        "fonte": "DOCUMENTOS_OFICIAIS_FII",
        "corrigidos": resolvidos,
        "sem_evidencia": sem_evidencia,
        "quantidade_corrigida": len(resolvidos),
        "quantidade_sem_evidencia": len(sem_evidencia),
    }
