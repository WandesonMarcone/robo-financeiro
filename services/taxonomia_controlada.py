"""Classificação auditável de ativos a partir de fontes controladas.

Este módulo deliberadamente não faz scraping de páginas de consulta da B3.
Ele recebe documentos já coletados pelo robô e produz uma evidência pequena,
reprodutível e apropriada para auditoria humana. Cada tipo de ativo possui sua
própria política de fontes; não existe uma regra genérica que trate FII, ação,
ETF e BDR como se fossem o mesmo instrumento.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


POLITICAS_DE_FONTE = {
    "FII": {
        "primaria": "RELATORIO_GERENCIAL_OU_INFORME_CVM_FNET",
        "confirmacao": "DADOS_ABERTOS_CVM",
        "contingencia": "FUNDAMENTUS_SEGMENTO",
    },
    "ACAO": {
        "primaria": "CLASSIFICACAO_SETORIAL_B3_AUTORIZADA",
        "confirmacao": "FORMULARIO_REFERENCIA_OU_DFP_ITR_CVM",
        "contingencia": None,
    },
    "ETF": {
        "primaria": "FICHA_B3_E_FACTSHEET_GESTORA",
        "confirmacao": "FUNDO_NET_CVM",
        "contingencia": None,
    },
    "BDR": {
        "primaria": "PROGRAMA_BDR_B3_E_EMISSOR_LASTRO",
        "confirmacao": "RELATORIO_ANUAL_DO_EMISSOR",
        "contingencia": None,
    },
}


@dataclass(frozen=True)
class EvidenciaTaxonomia:
    classe: str
    segmento: str
    confianca: str
    fonte: str
    trecho: str


def _normalizar(texto: object) -> str:
    valor = unicodedata.normalize("NFKD", str(texto or ""))
    valor = "".join(char for char in valor if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", valor).upper().strip()


def _trecho(texto: str, padrao: str) -> str:
    encontrado = re.search(padrao, texto, flags=re.IGNORECASE)
    if not encontrado:
        return ""
    inicio = max(0, encontrado.start() - 80)
    fim = min(len(texto), encontrado.end() + 180)
    return re.sub(r"\s+", " ", texto[inicio:fim]).strip()[:420]


def classificar_texto_fii(texto: object, tipo_documento: object = "") -> EvidenciaTaxonomia | None:
    """Classifica FII apenas com indicação explícita em documento oficial.

    O texto pode conter referências a outros fundos (por exemplo, uma posição
    em HGLG11). Por isso, menções soltas a CRI/cotas não bastam: exigimos uma
    declaração de segmento, objetivo ou composição de carteira do próprio
    fundo. A saída ``None`` é o resultado correto quando não há prova.
    """
    original = str(texto or "")
    chave = _normalizar(original)
    if len(chave) < 40:
        return None
    origem = "RELATORIO_GERENCIAL" if "RELATORIO" in _normalizar(tipo_documento) else "DOCUMENTO_OFICIAL_FII"

    regras = (
        ("Papel", "CRI", r"(?:IMOBILIARIO\s+CRI|CERTIFICADOS?\s+DE\s+RECEBIVEIS\s+IMOBILIARIOS|CARTEIRA.{0,100}\bCRI\b|ALOCACAO.{0,100}\bCRI\b)"),
        ("FOF", "Cotas de FIIs", r"(?:FUNDO\s+DE\s+FUNDOS|OBJETIVO.{0,160}COTAS?\s+DE\s+FUNDOS?\s+IMOBILIARIOS|CARTEIRA.{0,100}COTAS?\s+DE\s+FII)"),
        ("Tijolo", "Logística", r"(?:SEGMENTO\s+DE\s+ATUACAO\s*[:\-]?\s*LOGISTICA|FUNDO.{0,100}LOGISTICO|PORTFOLIO.{0,100}(?:GALPOES|LOGISTICA))"),
        ("Tijolo", "Shoppings", r"(?:SEGMENTO\s+DE\s+ATUACAO\s*[:\-]?\s*SHOPPINGS?|PORTFOLIO.{0,100}SHOPPINGS?)"),
        ("Tijolo", "Lajes Corporativas", r"(?:SEGMENTO\s+DE\s+ATUACAO\s*[:\-]?\s*(?:LAJES?|ESCRITORIOS?|CORPORATIV)|PORTFOLIO.{0,100}(?:LAJES?|ESCRITORIOS?))"),
        ("Tijolo", "Renda Urbana", r"(?:SEGMENTO\s+DE\s+ATUACAO\s*[:\-]?\s*RENDA\s+URBANA|RENDA\s+URBANA)"),
        ("Híbrido", "Misto", r"(?:MULTIESTRATEGIA|MULTI\s+ESTRATEGIA|SEGMENTO\s+MISTO|FUNDO\s+HIBRIDO)"),
    )
    for classe, segmento, padrao in regras:
        achado = _trecho(chave, padrao)
        if achado:
            return EvidenciaTaxonomia(classe, segmento, "ALTA", origem, achado)
    return None


def melhor_evidencia_fii(documentos) -> tuple[EvidenciaTaxonomia, object] | None:
    """Seleciona a melhor prova em relatórios antes de outros documentos."""
    ordenados = sorted(
        documentos,
        key=lambda doc: (
            "RELATORIO" not in _normalizar(getattr(doc, "tipo_documento", "")),
            getattr(doc, "data_publicacao", None) or "",
        ),
        reverse=False,
    )
    for documento in ordenados:
        texto = "\n".join(filter(None, (
            getattr(documento, "texto_extraido", None),
            getattr(documento, "resumo_ia", None),
            getattr(documento, "assunto", None),
        )))
        evidencia = classificar_texto_fii(texto, getattr(documento, "tipo_documento", ""))
        if evidencia:
            return evidencia, documento
    return None
