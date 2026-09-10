"""Semantica, unidades e escalas dos indicadores — Fase 8, Etapa 8.5.

Camada unica para distinguir:

- ZERO -> valor realmente zero (0 / 0.0);
- AUSENTE -> dado nao encontrado/indisponivel (NULL);
- NAO_APLICAVEL -> indicador nao se aplica ao ativo (N/A);
- INVALIDO -> valor presente e ilegivel/nao-finito (NaN, Inf, texto);
- PRESENTE -> valor numerico utilizavel diferente de zero.

Percentuais persistidos sao fracao (0.12 = 12%). Multiplos sao x.
Esta camada nao inventa valor nem converte escala por heuristica: um 12.0
sem o simbolo % permanece 12.0; a faixa de plausibilidade (Fase 4)
e quem sinaliza inconsistencia de fonte/escala.

Nao implementa WALT, alavancagem, ETF/cripto.
Bancos/seguradoras: aplicabilidade setorial em indicadores_cvm_acoes.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from pipeline_dados.numerico import (
    NAO_FINITO,
    NAO_NUMERO,
    coerir_numero,
    parsear_percentual,
)

ZERO = "ZERO"
AUSENTE = "AUSENTE"
NAO_APLICAVEL = "NAO_APLICAVEL"
INVALIDO = "INVALIDO"
PRESENTE = "PRESENTE"

STATUS_VALIDOS = (ZERO, AUSENTE, NAO_APLICAVEL, INVALIDO, PRESENTE)

FRACAO = "fracao"
MULTIPLO = "multiplo"
MONETARIO = "monetario"
QUANTIDADE = "quantidade"
RAZAO = "razao"
DATA = "data"
TEXTO = "texto"
SEM_UNIDADE = "sem_unidade"

UNIDADE_PCT = "%"
UNIDADE_X = "x"
UNIDADE_BRL = "R$"
UNIDADE_UN = "un."

FII = "FII"
ACAO = "ACAO"

_NA_CANONICOS = frozenset(
    {
        "n/a",
        "na",
        "nao aplicavel",
        "nao-aplicavel",
        "nao_aplicavel",
    }
)
_AUSENTES_CANONICOS = frozenset({"-", "--", "—", "n/d", "nd"})


def _sem_acento(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", texto)
    return "".join(ch for ch in normalizado if not unicodedata.combining(ch))


def tipo_canonico(tipo_ativo) -> str | None:
    if tipo_ativo is None:
        return None
    valor = tipo_ativo.value if hasattr(tipo_ativo, "value") else tipo_ativo
    texto = str(valor).strip().upper()
    if not texto:
        return None
    if texto.startswith("TIPOATIVO."):
        texto = texto.split(".", 1)[-1]
    return texto


def eh_nao_aplicavel(valor) -> bool:
    """True so para sentinela explicita de N/A. Nao trata vazio nem '-'."""
    if valor is None or isinstance(valor, (int, float, bool)):
        return False
    if not isinstance(valor, str):
        return False
    texto = _sem_acento(valor).strip().lower()
    if not texto:
        return False
    return texto in _NA_CANONICOS


def classificar_semantica(valor) -> str:
    """Classifica o valor bruto sem alterar o numero original."""
    if eh_nao_aplicavel(valor):
        return NAO_APLICAVEL
    if isinstance(valor, str):
        texto = _sem_acento(valor).strip().lower()
        if texto in _AUSENTES_CANONICOS:
            return AUSENTE
        if "%" in valor:
            numero = parsear_percentual(valor)
            if numero is None:
                return INVALIDO
            if numero == 0:
                return ZERO
            return PRESENTE
    numero, motivo = coerir_numero(valor)
    if motivo in (NAO_NUMERO, NAO_FINITO):
        return INVALIDO
    if numero is None:
        return AUSENTE
    if numero == 0:
        return ZERO
    return PRESENTE


@dataclass(frozen=True)
class DefinicaoIndicador:
    """Unidade/escala canonica de um indicador persistido."""

    indicador: str
    nome_exibicao: str
    escala: str
    unidade: str
    tipos: tuple[str, ...]
    persistido: str
    observacao: str = ""


def _def(
    indicador,
    nome,
    escala,
    unidade,
    tipos,
    persistido,
    observacao="",
):
    return DefinicaoIndicador(
        indicador=indicador,
        nome_exibicao=nome,
        escala=escala,
        unidade=unidade,
        tipos=tipos,
        persistido=persistido,
        observacao=observacao,
    )


CATALOGO: dict[str, DefinicaoIndicador] = {
    "preco": _def("preco", "Preco", MONETARIO, UNIDADE_BRL, (FII, ACAO), "snapshots_*.preco"),
    "dy": _def(
        "dy", "Dividend Yield", FRACAO, UNIDADE_PCT, (FII, ACAO), "snapshots_*.dy",
        "fracao 0-1 (0.12 = 12%)",
    ),
    "pvp": _def("pvp", "P/VP", MULTIPLO, UNIDADE_X, (FII, ACAO), "snapshots_*.pvp"),
    "vpa": _def("vpa", "VPA", MONETARIO, UNIDADE_BRL, (FII, ACAO), "snapshots_*.vpa"),
    "liquidez": _def("liquidez", "Liquidez", MONETARIO, UNIDADE_BRL, (FII,), "snapshots_fiis.liquidez"),
    "lucro_12m": _def("lucro_12m", "Lucro 12M", MONETARIO, UNIDADE_BRL, (FII,), "snapshots_fiis.lucro_12m"),
    "dividendo_mensal": _def(
        "dividendo_mensal", "Dividendo Mensal", MONETARIO, UNIDADE_BRL, (FII,),
        "snapshots_fiis.dividendo_mensal",
    ),
    "qtd_imoveis": _def(
        "qtd_imoveis", "Qtd. Imoveis", QUANTIDADE, UNIDADE_UN, (FII,),
        "snapshots_fiis.qtd_imoveis",
    ),
    "pl": _def("pl", "P/L", MULTIPLO, UNIDADE_X, (ACAO,), "snapshots_acoes.pl"),
    "p_ativo": _def("p_ativo", "P/Ativo", MULTIPLO, UNIDADE_X, (ACAO,), "snapshots_acoes.p_ativo"),
    "marg_bruta": _def(
        "marg_bruta", "Margem Bruta", FRACAO, UNIDADE_PCT, (ACAO,), "snapshots_acoes.marg_bruta",
        "fracao 0-1",
    ),
    "marg_ebit": _def(
        "marg_ebit", "Margem EBIT", FRACAO, UNIDADE_PCT, (ACAO,), "snapshots_acoes.marg_ebit",
        "fracao 0-1",
    ),
    "marg_liquida": _def(
        "marg_liquida", "Margem Liquida", FRACAO, UNIDADE_PCT, (ACAO,),
        "snapshots_acoes.marg_liquida", "fracao 0-1",
    ),
    "p_ebit": _def("p_ebit", "P/EBIT", MULTIPLO, UNIDADE_X, (ACAO,), "snapshots_acoes.p_ebit"),
    "ev_ebit": _def("ev_ebit", "EV/EBIT", MULTIPLO, UNIDADE_X, (ACAO,), "snapshots_acoes.ev_ebit"),
    "div_liq_ebit": _def(
        "div_liq_ebit", "Div. Liq./EBIT", MULTIPLO, UNIDADE_X, (ACAO,),
        "snapshots_acoes.div_liq_ebit",
        "PENDENTE: origem do Sheets duplica Div.Liq/Patrimonio; 5C persiste NULL",
    ),
    "div_liq_patrimonio": _def(
        "div_liq_patrimonio", "Div. Liq./Patrimonio", RAZAO, UNIDADE_X, (ACAO,),
        "snapshots_acoes.div_liq_patrimonio",
    ),
    "psr": _def("psr", "PSR", MULTIPLO, UNIDADE_X, (ACAO,), "snapshots_acoes.psr"),
    "p_cap_giro": _def("p_cap_giro", "P/Cap. Giro", MULTIPLO, UNIDADE_X, (ACAO,), "snapshots_acoes.p_cap_giro"),
    "p_at_circ_liq": _def(
        "p_at_circ_liq", "P/Ativ. Circ. Liq.", MULTIPLO, UNIDADE_X, (ACAO,),
        "snapshots_acoes.p_at_circ_liq",
    ),
    "liq_corrente": _def(
        "liq_corrente", "Liquidez Corrente", RAZAO, UNIDADE_X, (ACAO,),
        "snapshots_acoes.liq_corrente",
    ),
    "roe": _def(
        "roe", "ROE", FRACAO, UNIDADE_PCT, (ACAO,), "snapshots_acoes.roe",
        "fracao 0-1 (0.20 = 20%)",
    ),
    "roa": _def(
        "roa", "ROA", FRACAO, UNIDADE_PCT, (ACAO,), "snapshots_acoes.roa",
        "fracao 0-1; yfinance returnOnAssets ja chega como fracao",
    ),
    "roic": _def(
        "roic", "ROIC", FRACAO, UNIDADE_PCT, (ACAO,), "snapshots_acoes.roic",
        "fracao 0-1",
    ),
    "cagr_rec_5a": _def(
        "cagr_rec_5a", "CAGR Rec. 5a", FRACAO, UNIDADE_PCT, (ACAO,),
        "snapshots_acoes.cagr_rec_5a", "fracao 0-1",
    ),
    "liq_media": _def("liq_media", "Liquidez Media", MONETARIO, UNIDADE_BRL, (ACAO,), "snapshots_acoes.liq_media"),
    "lpa": _def("lpa", "LPA", MONETARIO, UNIDADE_BRL, (ACAO,), "snapshots_acoes.lpa"),
    "peg_ratio": _def("peg_ratio", "PEG Ratio", MULTIPLO, UNIDADE_X, (ACAO,), "snapshots_acoes.peg_ratio"),
    "valor_mercado": _def(
        "valor_mercado", "Valor de Mercado", MONETARIO, UNIDADE_BRL, (ACAO,),
        "snapshots_acoes.valor_mercado",
    ),
}


def obter_definicao(indicador) -> DefinicaoIndicador | None:
    if indicador is None:
        return None
    return CATALOGO.get(str(indicador).strip())


def indicador_aplicavel(tipo_ativo, indicador) -> bool:
    """False quando o indicador nao se aplica ao tipo (N/A, nunca 0).

    Tipo ausente nao inventa N/A: so classifica quando o tipo e conhecido.
    """
    definicao = obter_definicao(indicador)
    if definicao is None:
        return True
    tipo = tipo_canonico(tipo_ativo)
    if tipo is None:
        return True
    return tipo in definicao.tipos


def unidade_do_indicador(indicador, tipo_ativo=None) -> str | None:
    definicao = obter_definicao(indicador)
    if definicao is None:
        return None
    if tipo_ativo is not None and not indicador_aplicavel(tipo_ativo, indicador):
        return None
    return definicao.unidade


def escala_do_indicador(indicador) -> str | None:
    definicao = obter_definicao(indicador)
    return None if definicao is None else definicao.escala


def indicadores_pendentes() -> tuple[str, ...]:
    """Indicadores cuja origem/significado permanece PENDENTE (não inventar)."""
    return tuple(
        nome
        for nome, definicao in CATALOGO.items()
        if definicao.observacao.startswith("PENDENTE")
    )


def interpretar_valor(tipo_ativo, indicador, valor) -> dict:
    """Interpreta um valor ja coletado. Nao inventa numero nem escala.

    valor_numerico e o parse canonico (zero real permanece 0.0). N/A e
    INVALID nunca viram 0. Indicador nao aplicavel ignora o valor recebido.
    """
    definicao = obter_definicao(indicador)
    tipo = tipo_canonico(tipo_ativo)
    if definicao is not None and not indicador_aplicavel(tipo_ativo, indicador):
        return {
            "indicador": indicador,
            "tipo": tipo,
            "semantica": NAO_APLICAVEL,
            "valor_numerico": None,
            "unidade": definicao.unidade,
            "escala": definicao.escala,
            "aplicavel": False,
        }

    semantica = classificar_semantica(valor)
    numero = None if semantica in (AUSENTE, NAO_APLICAVEL, INVALIDO) else parsear_percentual(valor)
    if semantica == ZERO:
        numero = 0.0
    return {
        "indicador": indicador,
        "tipo": tipo,
        "semantica": semantica,
        "valor_numerico": numero,
        "unidade": definicao.unidade if definicao else None,
        "escala": definicao.escala if definicao else None,
        "aplicavel": True if definicao is None else indicador_aplicavel(tipo_ativo, indicador),
    }
