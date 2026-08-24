"""Deduplicação de documentos por conteúdo (SHA-256) — Fase 3.

Responsabilidade única: calcular o hash de conteúdo dos PDFs e detectar
duplicatas exatas por SHA-256, preservando id_b3/url_pdf como identificadores
de origem e mantendo rastreabilidade sem alterar o schema existente.
"""
import hashlib

from pipeline_dados.banco_dados import DocumentosQualitativos

STATUS_DUPLICADO = "DUPLICADO"


def calcular_hash_sha256(conteudo: bytes) -> str:
    """Hash determinístico do conteúdo bruto do PDF para comparação exata."""
    return hashlib.sha256(conteudo).hexdigest()


def buscar_original_por_hash(session, hash_sha256, exceto_id=None):
    """Retorna o documento que já possui o hash, ou None.

    Um documento só é considerado duplicado por conteúdo quando o SHA-256 é
    exatamente igual. Nome de arquivo e ticker não são usados como prova de
    duplicidade.
    """
    if not hash_sha256:
        return None
    query = session.query(DocumentosQualitativos).filter(
        DocumentosQualitativos.hash_sha256 == hash_sha256
    )
    if exceto_id is not None:
        query = query.filter(DocumentosQualitativos.id != exceto_id)
    return query.first()


def verificar_duplicidade(session, conteudo: bytes, exceto_id=None):
    """Calcula o hash e localiza duplicata exata por conteúdo.

    Retorna (hash_pdf, documento_original). documento_original é None quando o
    conteúdo é inédito no banco.
    """
    hash_pdf = calcular_hash_sha256(conteudo)
    original = buscar_original_por_hash(session, hash_pdf, exceto_id=exceto_id)
    return hash_pdf, original


def marcar_duplicado(doc, original):
    """Marca o documento como duplicado do original, sem remover o registro.

    O hash permanece NULL no duplicado (a coluna hash_sha256 é única, e apenas
    o documento canônico guarda o valor), preservando a rastreabilidade via
    log_erro e os identificadores de origem (id_b3/url_pdf).
    """
    doc.status_processamento = STATUS_DUPLICADO
    doc.log_erro = f"Conteúdo duplicado do documento #{original.id}"
