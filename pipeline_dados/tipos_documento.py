"""Catalogo de tipos de documento (FII/acao) e aliases da FNET/B3.

A IA e a exibicao so usam nomes deste catalogo. Rotulos genericos
(Documento, Sem Tipo) nao entram em Novos Documentos.
"""

import re
import unicodedata

from config import TIPOS_DOC_ACAO, TIPOS_DOC_FII

TIPOS_GENERICOS = frozenset(
    {
        "documento",
        "documento sem tipo",
        "documento_fii",
        "documento fii",
        "documento_acao",
        "documento acao",
        "sem tipo",
        "sem titulo",
        "n/a",
        "na",
        "none",
        "null",
    }
)

ALIAS_FII = {
    "ago": "Assembleia Geral",
    "age": "Assembleia Geral",
    "ago/age": "Assembleia Geral",
    "assembleia": "Assembleia Geral",
    "assembleia geral ordinaria": "Assembleia Geral",
    "assembleia geral extraordinaria": "Assembleia Geral",
    "assembleia geral de cotistas": "Assembleia Geral",
    "aviso ao mercado": "Comunicado ao Mercado",
    "aviso de fato relevante": "Fato Relevante",
    "informe": "Informe Mensal",
    "informe mensal": "Informe Mensal",
    "relatorio gerencial": "Relatorio Gerencial",
    "relatório gerencial": "Relatorio Gerencial",
    "demonstracoes financeiras": "Demonstracoes Financeiras",
    "demonstrações financeiras": "Demonstracoes Financeiras",
    "df": "Demonstracoes Financeiras",
    "rendimento": "Rendimentos",
    "aviso a cotistas": "Aviso aos Cotistas",
    "aviso aos cotistas": "Aviso aos Cotistas",
    "nova emissao": "Nova Emissao de Cotas",
    "nova emissao de cotas": "Nova Emissao de Cotas",
    "proposta de emissao": "Proposta Emissão de Cotas",
    "apresentacao trimestral": "Apresentação Trimestral De Resultados",
    "apresentacao de resultados": "Apresentação Trimestral De Resultados",
}

ALIAS_ACAO = {
    "aviso ao mercado": "Comunicado ao Mercado",
    "release de resultados": "Apresentação de Resultados",
    "apresentacao de resultados": "Apresentação de Resultados",
}


def _sem_acento(texto):
    return "".join(
        c
        for c in unicodedata.normalize("NFD", str(texto or ""))
        if unicodedata.category(c) != "Mn"
    )


def _chave(texto):
    bruto = _sem_acento(texto).strip().lower()
    bruto = bruto.replace("_", " ").replace("-", " ")
    bruto = re.sub(r"[^a-z0-9 /]+", " ", bruto)
    return re.sub(r"\s+", " ", bruto).strip()


def catalogo_fii():
    return tuple(TIPOS_DOC_FII.values())


def catalogo_acao():
    return tuple(TIPOS_DOC_ACAO.values())


def _mapa_oficial(valores):
    return {_chave(nome): nome for nome in valores}


def e_tipo_generico(tipo):
    chave = _chave(tipo)
    return not chave or chave in TIPOS_GENERICOS


def normalizar_tipo_documento(tipo, tipo_ativo="FII"):
    """Devolve nome oficial do catalogo ou None se generico/desconhecido."""
    if e_tipo_generico(tipo):
        return None
    chave = _chave(tipo)
    if str(tipo_ativo or "FII").upper() == "ACAO":
        alias = ALIAS_ACAO.get(chave)
        if alias:
            return alias
        return _mapa_oficial(catalogo_acao()).get(chave)
    alias = ALIAS_FII.get(chave)
    if alias:
        return alias
    return _mapa_oficial(catalogo_fii()).get(chave)


def tipo_exibivel(tipo, tipo_ativo="FII"):
    return normalizar_tipo_documento(tipo, tipo_ativo) is not None


def manter_tipo_catalogo(tipo_ia, original, tipo_ativo="FII"):
    """Usa o tipo da IA so se estiver no catalogo; senão tenta o original."""
    oficial = normalizar_tipo_documento(tipo_ia, tipo_ativo)
    if oficial:
        return oficial
    return normalizar_tipo_documento(original, tipo_ativo)
