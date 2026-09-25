"""Matriz central de aplicabilidade — PARTE F.1.

Consulta determinística: indicador + classificação econômica da empresa
→ APLICAVEL | NAO_APLICAVEL | AUSENTE.

Não calcula nem altera valores. Não reimplementa a semântica de
PRESENTE/ZERO/AUSENTE/NAO_CALCULAVEL/NAO_APLICAVEL/INVALIDO: reutiliza as
constantes de ``semantica_indicadores``. APLICAVEL é só a decisão da matriz
(o indicador se aplica), não um status de valor.

Classificação AUSENTE/NAO_CLASSIFICADO não presume NAO_APLICAVEL.
Tipo de ativo continua sendo resolvido por ``indicador_aplicavel``.
"""
from __future__ import annotations

import unicodedata

import config
from pipeline_dados.catalogo_ativos import SETOR_NAO_CLASSIFICADO, setor_confiavel
from pipeline_dados.semantica_indicadores import AUSENTE, NAO_APLICAVEL, indicador_aplicavel, tipo_canonico

APLICAVEL = "APLICAVEL"

NATUREZA_BANCO = "BANCO"
NATUREZA_SEGURADORA = "SEGURADORA"
NATUREZA_INDUSTRIAL = "INDUSTRIAL"

SUBSETOR_BANCO = "Bancos"
SUBSETOR_SEGURO = "Seguros e Resseguros"
MACRO_FINANCEIRO = "Financeiro"

_ALIAS_INDICADOR = {
    "ebitda": "ebitda",
    "ebitda_ltm": "ebitda",
    "marg_ebitda": "marg_ebitda",
    "margem_ebitda": "marg_ebitda",
    "ev_ebitda": "ev_ebitda",
    "div_liq_ebitda": "div_liq_ebitda",
    "divida_liquida_ebitda": "div_liq_ebitda",
    "p_ebit": "p_ebit",
    "marg_ebit": "marg_ebit",
    "margem_ebit": "marg_ebit",
    "ebit_ltm": "ebit_ltm",
    "ev_ebit": "ev_ebit",
    "div_liq_ebit": "div_liq_ebit",
    "pl": "pl",
    "p_l": "pl",
    "pvp": "pvp",
    "p_vp": "pvp",
    "p_ativo": "p_ativo",
    "p_ativos": "p_ativo",
    "psr": "psr",
    "p_cap_giro": "p_cap_giro",
    "p_capital_de_giro": "p_cap_giro",
    "p_at_circ_liq": "p_at_circ_liq",
    "p_ativo_circulante_liquido": "p_at_circ_liq",
    "liq_corrente": "liq_corrente",
    "liquidez_corrente": "liq_corrente",
    "roe": "roe",
    "roa": "roa",
    "roic": "roic",
    "patrimonio_ativos": "patrimonio_ativos",
    "passivos_ativos": "passivos_ativos",
    "giro_ativos": "giro_ativos",
    "giro_de_ativos": "giro_ativos",
    "cagr_rec_5a": "cagr_rec_5a",
    "cagr_receita_5a": "cagr_rec_5a",
    "cagr_lucro_5a": "cagr_lucro_5a",
    "peg": "peg_ratio",
    "peg_ratio": "peg_ratio",
}

# Banco/seguradora: resultado operacional industrial (EBIT/EBITDA, dívida
# líquida operacional, capital de giro e ROIC) não descreve o negócio de
# intermediação/reservas. Múltiplos de lucro/patrimônio e rentabilidade
# sobre equity/ativos permanecem aplicáveis.
_NA_INTERMEDIACAO = frozenset({
    "ebitda",
    "marg_ebitda",
    "ev_ebitda",
    "div_liq_ebitda",
    "p_ebit",
    "marg_ebit",
    "ebit_ltm",
    "ev_ebit",
    "div_liq_ebit",
    "p_cap_giro",
    "p_at_circ_liq",
    "liq_corrente",
    "roic",
})

MATRIZ_NAO_APLICAVEL = {
    NATUREZA_BANCO: _NA_INTERMEDIACAO,
    NATUREZA_SEGURADORA: _NA_INTERMEDIACAO,
    NATUREZA_INDUSTRIAL: frozenset(),
}

_NATUREZAS_EXPLICITAS = {
    "BANCO": NATUREZA_BANCO,
    "BANCOS": NATUREZA_BANCO,
    "SEGURADORA": NATUREZA_SEGURADORA,
    "SEGURADORAS": NATUREZA_SEGURADORA,
    "SEGUROS E RESSEGUROS": NATUREZA_SEGURADORA,
    "INDUSTRIAL": NATUREZA_INDUSTRIAL,
}


def _chave_indicador(indicador) -> str:
    if indicador is None:
        return ""
    bruto = unicodedata.normalize("NFD", str(indicador))
    texto = "".join(c for c in bruto if unicodedata.category(c) != "Mn").strip().lower()
    if not texto:
        return ""
    for antigo, novo in (("%", ""), ("-", "_"), ("/", "_"), (" ", "_")):
        texto = texto.replace(antigo, novo)
    return "_".join(p for p in texto.split("_") if p)


def _canonizar_indicador(indicador) -> str:
    chave = _chave_indicador(indicador)
    return _ALIAS_INDICADOR.get(chave, chave)


def _mapa_b3() -> dict[str, tuple[str, str]]:
    mapa = {}
    for macro, subsetores in config.MAPA_SETORES_B3.items():
        for subsetor, tickers in subsetores.items():
            for ticker in tickers:
                mapa[str(ticker).strip().upper()] = (macro, subsetor)
    return mapa


def _rotulo_ausente(valor) -> bool:
    if valor is None:
        return True
    texto = str(valor).strip()
    if not texto:
        return True
    if texto == SETOR_NAO_CLASSIFICADO:
        return True
    if not setor_confiavel(texto) and texto.upper() in {
        "AUSENTE", "OUTROS", "NAO_CLASSIFICADO", "NÃO CLASSIFICADO",
        "NAO CLASSIFICADO", "INDETERMINADO",
    }:
        return True
    return texto in {"Outros", "Não Classificado"}


def _natureza_de_subsetor(subsetor) -> str | None:
    if not subsetor:
        return None
    texto = str(subsetor).strip()
    if texto == SUBSETOR_BANCO:
        return NATUREZA_BANCO
    if texto == SUBSETOR_SEGURO:
        return NATUREZA_SEGURADORA
    if setor_confiavel(texto):
        return NATUREZA_INDUSTRIAL
    return None


def resolver_natureza(*, classificacao=None, setor=None, subsetor=None, ticker=None) -> str:
    """BANCO / SEGURADORA / INDUSTRIAL / AUSENTE. Não inventa setor."""
    for candidato in (classificacao, subsetor, setor):
        if candidato is None:
            continue
        chave = " ".join(str(candidato).strip().upper().replace("_", " ").split())
        if chave in _NATUREZAS_EXPLICITAS:
            return _NATUREZAS_EXPLICITAS[chave]
        natureza_sub = _natureza_de_subsetor(candidato)
        if natureza_sub is not None and str(candidato).strip() in {SUBSETOR_BANCO, SUBSETOR_SEGURO}:
            return natureza_sub

    par = None
    if ticker:
        par = _mapa_b3().get(str(ticker).strip().upper())
    if par is not None:
        return _natureza_de_subsetor(par[1]) or NATUREZA_INDUSTRIAL

    if subsetor:
        natureza_sub = _natureza_de_subsetor(subsetor)
        if natureza_sub is not None:
            return natureza_sub
        if _rotulo_ausente(subsetor):
            return AUSENTE

    if classificacao:
        if _rotulo_ausente(classificacao):
            return AUSENTE
        if setor_confiavel(classificacao):
            if str(classificacao).strip() == MACRO_FINANCEIRO:
                return AUSENTE
            return NATUREZA_INDUSTRIAL

    if setor:
        if _rotulo_ausente(setor):
            return AUSENTE
        if setor_confiavel(setor):
            if str(setor).strip() == MACRO_FINANCEIRO:
                return AUSENTE
            return NATUREZA_INDUSTRIAL
        return AUSENTE

    return AUSENTE


def consultar_aplicabilidade(
    indicador,
    classificacao=None,
    *,
    tipo=None,
    setor=None,
    subsetor=None,
    ticker=None,
) -> str:
    """APLICAVEL, NAO_APLICAVEL ou AUSENTE. Não altera valores."""
    tipo_norm = tipo_canonico(tipo)
    if tipo_norm is not None and not indicador_aplicavel(tipo_norm, indicador):
        return NAO_APLICAVEL

    natureza = resolver_natureza(
        classificacao=classificacao, setor=setor, subsetor=subsetor, ticker=ticker,
    )
    if natureza == AUSENTE:
        return AUSENTE

    canonico = _canonizar_indicador(indicador)
    if not canonico:
        return APLICAVEL
    if canonico in MATRIZ_NAO_APLICAVEL.get(natureza, ()):
        return NAO_APLICAVEL
    return APLICAVEL


def blank_se_nao_aplicavel(
    indicador,
    valor,
    *,
    tipo=None,
    setor=None,
    subsetor=None,
    ticker=None,
    classificacao=None,
):
    """Camada numérica: NAO_APLICAVEL vira None; demais valores intactos.

    Não converte AUSENTE/APLICAVEL. Não inventa número. ZERO permanece ZERO.
    """
    status = consultar_aplicabilidade(
        indicador,
        classificacao,
        tipo=tipo,
        setor=setor,
        subsetor=subsetor,
        ticker=ticker,
    )
    if status == NAO_APLICAVEL:
        return None
    return valor
