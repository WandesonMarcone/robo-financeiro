"""Normalização de identidade e datas do Core de Dados (Fase 3).

Responsabilidade única: centralizar a limpeza/padronização de CNPJ, nomes e
datas, eliminando parsers ad-hoc espalhados pelos coletores. Não depende de
banco, rede ou fontes externas, portanto é reutilizável e testável offline.
"""
import re
import unicodedata
from datetime import date, datetime

_FORMATOS_DATA = (
    "%Y-%m-%d",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y %H:%M:%S",
)


def normalizar_cnpj(cnpj) -> str | None:
    """Retorna apenas os 14 dígitos do CNPJ, ou None se o valor for inválido."""
    if cnpj is None:
        return None
    digitos = re.sub(r"\D", "", str(cnpj))
    return digitos if len(digitos) == 14 else None


def formatar_cnpj(cnpj) -> str:
    """Converte para o formato XX.XXX.XXX/XXXX-XX usado pela CVM/B3.

    Se o valor não tiver 14 dígitos, devolve a entrada original inalterada.
    """
    digitos = normalizar_cnpj(cnpj)
    if digitos is None:
        return str(cnpj)
    return f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:]}"


def normalizar_data(valor) -> date | None:
    """Converte date/datetime/string em date, cobrindo os formatos das fontes
    do projeto (CVM, FNET/B3). Retorna None quando não for possível parsear.
    """
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if valor is None:
        return None

    texto = str(valor).strip()
    if not texto:
        return None

    for formato in _FORMATOS_DATA:
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None


def normalizar_texto(texto) -> str:
    """Remove acentos para casamento de nomes (ex.: fundos na B3/CVM)."""
    if not texto:
        return ""
    return "".join(
        c for c in unicodedata.normalize("NFD", str(texto)) if unicodedata.category(c) != "Mn"
    )
