"""Taxonomia canonica de FIIs: Tijolo/Papel/FOF/Hibrido + segmentos."""

from __future__ import annotations

import re
import unicodedata

import config

MACROS_FII = ("Tijolo", "Papel", "FOF", "Híbrido")

EMOJI_MACRO_FII = {
    "Tijolo": "🧱",
    "Papel": "📜",
    "FOF": "🔄",
    "Híbrido": "🧩",
}

EXCECOES_TIPO_FII = {
    "MXRF11": "Papel",
    "GARE11": "Tijolo",
}

_SEGMENTOS = (
    ("CRI", "Papel", ("TITULOS", "PAPEL", "RECEBIVEL", "VALORES MOBILIARIOS", "CRI", "LCI", "CRA", "CERTIFICADOS")),
    ("Cotas de FIIs", "FOF", ("FUNDO DE FUNDOS", "FOF", "COTAS DE FUNDOS", "COTAS DE FIIS")),
    ("Misto", "Híbrido", ("HIBRIDO", "MISTO", "MULTIESTRATEGIA", "MULTI ESTRATEGIA", "MULTI-ESTRATEGIA")),
    ("Logística", "Tijolo", ("LOGISTIC", "GALPAO", "INDUSTRIAL")),
    ("Shoppings", "Tijolo", ("SHOPPING", "MALL")),
    ("Lajes Corporativas", "Tijolo", ("LAJE", "CORPORATIV", "ESCRITORIO", "OFFICE")),
    ("Residencial", "Tijolo", ("RESIDENCIAL", "APARTAMENTO", "VIVENDAS")),
    ("Renda Urbana", "Tijolo", ("RENDA URBANA", "AGENCI", "BANCAR")),
    ("Hotéis", "Tijolo", ("HOTEL", "HOTEIS", "HOSPEDAGEM")),
    ("Educacional", "Tijolo", ("EDUCACIONAL", "ESCOLA", "UNIVERSIDADE", "FACULDADE")),
    ("Hospitais", "Tijolo", ("HOSPITAL", "SAUDE", "CLINICA")),
    ("Varejo", "Tijolo", ("VAREJO", "VAREJISTA", "HIGH STREET", "HIGHSTREET")),
    ("Desenvolvimento", "Tijolo", ("DESENVOLVIMENTO", "INCORPORA", "CONSTRUCAO", "ESTOQUE")),
    ("Fiagro", "Tijolo", ("FIAGRO",)),
    ("Agronegócio", "Tijolo", ("AGRO", "FAZENDA", "RURAL")),
    ("Infraestrutura", "Tijolo", ("INFRAESTRUTURA", "INFRASTRUCTURE", "INFRA", "RODOVIA", "FERROVIA", "SANEAMENTO", "TRANSMISSAO")),
)

_SEGMENTO_PADRAO = {
    "Tijolo": "Outros",
    "Papel": "CRI",
    "FOF": "Cotas de FIIs",
    "Híbrido": "Misto",
}


def _sem_acento_upper(valor):
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return texto.upper().strip()


def _mapa_fiis():
    return getattr(config, "MAPA_SETORES_FII", None) or {}


def _palavra_no_texto(chave, palavra):
    """Casa alias no texto. Tokens curtos (CRI) exigem borda, nao substring."""
    if not palavra or not chave:
        return False
    if len(palavra) <= 3:
        return re.search(
            r"(?<![A-Z0-9])" + re.escape(palavra) + r"(?![A-Z0-9])",
            chave,
        ) is not None
    return palavra in chave


def _casar_segmentos(texto):
    chave = _sem_acento_upper(texto)
    if not chave:
        return []
    achados = []
    vistos = set()
    for canonical, macro, palavras in _SEGMENTOS:
        if any(_palavra_no_texto(chave, palavra) for palavra in palavras):
            marca = (canonical, macro)
            if marca not in vistos:
                vistos.add(marca)
                achados.append(marca)
    return achados


def tipo_macro_fii(texto, ticker=""):
    """Macro canonica (Tijolo/Papel/FOF/Hibrido) a partir da planilha ou do texto livre."""
    t = str(ticker or "").strip().upper()
    if t in EXCECOES_TIPO_FII:
        return EXCECOES_TIPO_FII[t]
    chave = _sem_acento_upper(texto)
    for macro in MACROS_FII:
        if _sem_acento_upper(macro) == chave:
            return macro
    tipo, _segmento, _emoji = classificar_fii(texto, ticker)
    return tipo


def segmento_fii_canonico(texto, tipo=None, ticker=""):
    """Segmento canonico da coluna C (StatusInvest/Fundamentus ou ja canonico)."""
    macro = tipo if tipo in MACROS_FII else tipo_macro_fii(tipo or texto, ticker)
    chave = _sem_acento_upper(texto)
    mapa = _mapa_fiis()
    for nome in mapa.get(macro, []):
        if _sem_acento_upper(nome) == chave:
            return nome
    for canonical, macro_seg in _casar_segmentos(texto):
        if macro == "Híbrido":
            return _SEGMENTO_PADRAO["Híbrido"]
        if macro_seg == macro:
            return canonical
    return _SEGMENTO_PADRAO.get(macro, "Outros")


def classificar_fii(setor, ticker=""):
    """Devolve (macro, segmento, emoji) a partir do texto livre da fonte."""
    t = str(ticker or "").strip().upper()
    achados = _casar_segmentos(setor)
    macros = list(dict.fromkeys(item[1] for item in achados))
    if t in EXCECOES_TIPO_FII:
        tipo = EXCECOES_TIPO_FII[t]
    elif len(macros) > 1:
        tipo = "Híbrido"
    elif macros:
        tipo = macros[0]
    else:
        tipo = "Tijolo"
    segmento = segmento_fii_canonico(setor, tipo, ticker)
    return tipo, segmento, EMOJI_MACRO_FII.get(tipo, "🏢")


def classificar_fii_e_emoji(setor, ticker=""):
    tipo, _segmento, emoji = classificar_fii(setor, ticker)
    return tipo, emoji


def dados_linha_fii(linha):
    """Ticker, macro e segmento canonicos de uma linha da aba BD_FIIs."""
    ticker = str(linha[0] if linha else "").strip().upper()
    tipo_bruto = str(linha[1]).strip() if len(linha) > 1 else ""
    setor_bruto = str(linha[2]).strip() if len(linha) > 2 else ""
    if not tipo_bruto and not setor_bruto:
        return ticker, "", ""
    tipo = tipo_macro_fii(tipo_bruto or setor_bruto, ticker)
    segmento = segmento_fii_canonico(setor_bruto or tipo_bruto, tipo, ticker)
    return ticker, tipo, segmento
