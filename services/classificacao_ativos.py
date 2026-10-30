"""Regras determinísticas para classificação periódica de ativos.

A IA extrai evidências de documentos oficiais; este módulo valida a resposta.
Ausência de evidência nunca vira automaticamente Tijolo ou Outros.
"""
from __future__ import annotations
import os
from datetime import date, datetime, timedelta
from typing import Any, Mapping

INTERVALO_REANALISE_DIAS = int(os.environ.get("CLASSIFICACAO_ATIVOS_INTERVALO_DIAS", "120"))
CONFIANCA_MINIMA_AUTO = 90
TIPOS_FII = {"Tijolo", "Papel", "FOF", "Híbrido"}
SEGMENTOS_PAPEL = {"Recebíveis Imobiliários"}
SUBTIPOS_PAPEL = {"CRI", "LCI/LH"}
SEGMENTOS_FOF = {"Cotas de outros FIIs"}
FONTES_OFICIAIS = {"cvm", "fnet", "b3", "anbima", "administrador", "gestor", "documento_oficial"}

def reanalise_devida(ultima_data: date | datetime | None, agora=None) -> bool:
    if ultima_data is None:
        return True
    agora = agora or datetime.utcnow()
    ultima = ultima_data.date() if isinstance(ultima_data, datetime) else ultima_data
    return agora.date() >= ultima + timedelta(days=INTERVALO_REANALISE_DIAS)

def _texto(valor: Any) -> str:
    return str(valor or "").strip()

def validar_classificacao(dados: Mapping[str, Any]) -> tuple[str, list[str]]:
    erros = []
    tipo = _texto(dados.get("tipo_ativo")).upper()
    classe = _texto(dados.get("classe"))
    segmento = _texto(dados.get("segmento"))
    subtipo = _texto(dados.get("subtipo"))
    fonte = _texto(dados.get("fonte")).lower()
    evidencia = _texto(dados.get("evidencia"))
    confianca = int(dados.get("confianca") or 0)
    if tipo not in {"FII", "ACAO"}:
        erros.append("tipo_ativo inválido ou ausente")
    if tipo == "FII" and classe and classe not in TIPOS_FII:
        erros.append("classe de FII inválida")
    if tipo == "FII" and classe == "Papel" and segmento not in SEGMENTOS_PAPEL:
        erros.append("Papel exige Recebíveis Imobiliários")
    if tipo == "FII" and classe == "Papel" and subtipo and subtipo not in SUBTIPOS_PAPEL:
        erros.append("subtipo de Papel inválido")
    if tipo == "FII" and classe == "FOF" and segmento not in SEGMENTOS_FOF:
        erros.append("FOF exige Cotas de outros FIIs")
    if fonte not in FONTES_OFICIAIS:
        erros.append("fonte não oficial ou não informada")
    if not evidencia:
        erros.append("evidência documental ausente")
    estrategias = {str(x).lower() for x in (dados.get("estrategias") or [])}
    if {"high grade", "high yield"} <= estrategias:
        erros.append("High Grade e High Yield não podem coexistir")
    if "high grade" in estrategias and "grau de investimento" not in evidencia.lower():
        erros.append("High Grade exige evidência de grau de investimento")
    if any(x in estrategias for x in {"high grade", "high yield", "mid yield"}) and not evidencia:
        erros.append("estratégia de crédito exige evidência explícita")
    return ("aprovada" if not erros and confianca >= CONFIANCA_MINIMA_AUTO else "pendente"), erros

def normalizar_classificacao(dados: Mapping[str, Any]) -> dict[str, Any]:
    saida = {
        "tipo_ativo": _texto(dados.get("tipo_ativo")).upper() or None,
        "classe": _texto(dados.get("classe")) or None,
        "segmento": _texto(dados.get("segmento")) or None,
        "subtipo": _texto(dados.get("subtipo")) or None,
        "indexadores": [_texto(x).upper() for x in (dados.get("indexadores") or []) if _texto(x)],
        "estrategias": [_texto(x) for x in (dados.get("estrategias") or []) if _texto(x)],
        "confianca": max(0, min(100, int(dados.get("confianca") or 0))),
        "fonte": _texto(dados.get("fonte")).lower() or None,
        "evidencia": _texto(dados.get("evidencia")) or None,
    }
    saida["status"], saida["erros"] = validar_classificacao(saida)
    return saida

def prompt_classificacao_fii(ticker: str, texto_documento: str) -> str:
    return f"""Extraia somente fatos explícitos do documento oficial do FII {ticker}.
Não use DY para inferir High Grade ou High Yield.
Só informe CDI/IPCA se o documento indicar o indexador.
Só informe High Grade se houver evidência de grau de investimento.
Se não houver evidência, use null, lista vazia ou não confirmado.
Não classifique automaticamente como Tijolo quando faltar informação.
Campos JSON: tipo_ativo, classe, segmento, subtipo, indexadores,
estrategias, confianca, fonte, evidencia.
Segmento de Papel: Recebíveis Imobiliários. Subtipos: CRI ou LCI/LH.
Segmento de FOF: Cotas de outros FIIs.
Documento:
{texto_documento}
"""
