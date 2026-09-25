"""Indicadores contabeis de acoes a partir de DFP/ITR CVM (aditivo).

Nao substitui Fundamentus/Yahoo nem snapshots_acoes. Persistencia propria
em indicadores_cvm_acoes. Ausencia nunca vira 0. Bancos/seguradoras recebem
NAO_APLICAVEL nos indicadores industrialmente inadequados.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable

from sqlalchemy.orm import Session

from pipeline_dados.banco_dados import DadosFinanceirosAcoes, IndicadorCvmAcao, SnapshotAcao
from pipeline_dados.catalogo_ativos import consultar_por_ticker
from pipeline_dados.matriz_aplicabilidade import consultar_aplicabilidade
from pipeline_dados.numerico import derivar_divisao, parsear_numero
from pipeline_dados.semantica_indicadores import (
    AUSENTE,
    INVALIDO,
    NAO_APLICAVEL,
    NAO_CALCULAVEL,
    PRESENTE,
    ZERO,
    classificar_semantica,
    escala_do_indicador,
    obter_definicao,
    unidade_do_indicador,
)

FONTE_CVM = "CVM"
ORIGEM_CALCULO = "CVM/CALCULADO"
PERIODO_LTM = "LTM"
PERIODO_PONTO = "PONTO"
PERIODO_CAGR_5A = "CAGR_5A"
PERIODO_PEG = "PEG"

SETORES_BANCO = frozenset({"Bancos"})
SETORES_SEGURO = frozenset({"Seguros e Resseguros"})

INDICADORES_NAO_APLICAVEIS_FINANCEIRO = frozenset({
    "ebitda",
    "ebitda_ltm",
    "ebit_ltm",
    "marg_bruta",
    "marg_ebit",
    "p_ebit",
    "ev_ebit",
    "div_liq_ebit",
    "div_liq_patrimonio",
    "roic",
    "liq_corrente",
    "p_cap_giro",
    "p_at_circ_liq",
    "lucro_bruto_ltm",
    "divida_bruta",
    "divida_liquida",
})

FORMULAS = {
    "receita_ltm": "LTM(receita DFP/ITR YTD)",
    "lucro_liquido_ltm": "LTM(lucro_liquido DFP/ITR YTD)",
    "ebit_ltm": "LTM(ebit DFP/ITR YTD)",
    "ebitda_ltm": "LTM(ebitda DFP/ITR YTD)",
    "lucro_bruto_ltm": "LTM(lucro_bruto DFP/ITR YTD)",
    "fco_ltm": "LTM(fco DFP/ITR YTD)",
    "marg_bruta": "lucro_bruto_ltm / receita_ltm",
    "marg_ebit": "ebit_ltm / receita_ltm",
    "marg_liquida": "lucro_liquido_ltm / receita_ltm",
    "roe": "lucro_liquido_ltm / patrimonio_liquido",
    "roa": "lucro_liquido_ltm / ativo_total",
    "patrimonio_ativos": "patrimonio_liquido / ativo_total",
    "passivos_ativos": "passivo_total / ativo_total",
    "giro_ativos": "receita_ltm / ativo_total",
    "roic": "ebit_ltm / (patrimonio_liquido + divida_bruta - caixa)",
    "liq_corrente": "ativo_circulante / passivo_circulante",
    "div_liq_patrimonio": "divida_liquida / patrimonio_liquido",
    "div_liq_ebit": "divida_liquida / ebit_ltm",
    "cagr_rec_5a": "(receita_dfp_t / receita_dfp_t-5) ** (1/5) - 1",
    "cagr_lucro_5a": "(lucro_dfp_t / lucro_dfp_t-5) ** (1/5) - 1",
    "lpa": "lucro_liquido_ltm / qtd_acoes",
    "vpa": "patrimonio_liquido / qtd_acoes",
    "pl": "valor_mercado / lucro_liquido_ltm",
    "pvp": "valor_mercado / patrimonio_liquido",
    "psr": "valor_mercado / receita_ltm",
    "p_ebit": "valor_mercado / ebit_ltm",
    "p_ativo": "valor_mercado / ativo_total",
    "ev_ebit": "(valor_mercado + divida_liquida) / ebit_ltm",
    "peg_ratio": "pl / (cagr_lucro_5a * 100)",
}


def _subsetor_por_ticker() -> dict[str, str]:
    import config

    mapa = {}
    for _macro, subsetores in config.MAPA_SETORES_B3.items():
        for subsetor, tickers in subsetores.items():
            for ticker in tickers:
                mapa[str(ticker).strip().upper()] = subsetor
    return mapa


def natureza_financeira(ticker, session=None) -> str:
    """BANCO, SEGURADORA ou INDUSTRIAL. Nao inventa setor."""
    ticker_norm = str(ticker).strip().upper() if ticker else ""
    if not ticker_norm:
        return "INDUSTRIAL"
    subsetor = _subsetor_por_ticker().get(ticker_norm)
    if subsetor in SETORES_BANCO:
        return "BANCO"
    if subsetor in SETORES_SEGURO:
        return "SEGURADORA"
    if session is not None:
        registro = consultar_por_ticker(session, ticker_norm)
        if registro is not None and registro.setor:
            setor = str(registro.setor).strip()
            if setor == "Financeiro":
                sub = _subsetor_por_ticker().get(ticker_norm)
                if sub in SETORES_BANCO:
                    return "BANCO"
                if sub in SETORES_SEGURO:
                    return "SEGURADORA"
    return "INDUSTRIAL"


def _setor_catalogo(ticker, session=None) -> str | None:
    if session is None or not ticker:
        return None
    registro = consultar_por_ticker(session, ticker)
    if registro is None:
        return None
    return registro.setor


def indicador_aplicavel_setor(ticker, indicador, session=None) -> bool:
    """Compatibilidade: False só quando a matriz F.1 retorna NAO_APLICAVEL.

    AUSENTE/indeterminado não presume inaplicável (continua calculável).
    """
    status = consultar_aplicabilidade(
        indicador,
        _setor_catalogo(ticker, session),
        ticker=ticker,
    )
    return status != NAO_APLICAVEL


def eh_ytd(registro) -> bool:
    inicio = getattr(registro, "dt_ini_exerc", None)
    if isinstance(registro, dict):
        inicio = registro.get("dt_ini_exerc")
    if inicio is None:
        return True
    return inicio.month == 1 and inicio.day == 1


def _attr(registro, campo):
    if isinstance(registro, dict):
        return registro.get(campo)
    return getattr(registro, campo, None)


def _data_ref(registro) -> date | None:
    valor = _attr(registro, "data_referencia")
    return valor if isinstance(valor, date) else None


def _tipo_doc(registro) -> str:
    return str(_attr(registro, "tipo_doc") or "").upper()


def _numero_campo(registro, campo) -> float | None:
    return parsear_numero(_attr(registro, campo))


def montar_resultado(
    indicador: str,
    valor,
    *,
    ticker: str,
    data_referencia: date,
    periodo: str,
    formula: str | None = None,
    fonte: str = FONTE_CVM,
    fonte_primaria: str = ORIGEM_CALCULO,
    origem: str = ORIGEM_CALCULO,
    observacao: str | None = None,
    semantica: str | None = None,
    data_coleta: datetime | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    definicao = obter_definicao(indicador)
    if semantica is None:
        semantica = classificar_semantica(valor)
    numero = None if semantica in (AUSENTE, NAO_CALCULAVEL, NAO_APLICAVEL, INVALIDO) else parsear_numero(valor)
    if semantica == ZERO:
        numero = 0.0
    return {
        "ticker": ticker,
        "indicador": indicador,
        "valor": numero,
        "semantica": semantica,
        "unidade": unidade_do_indicador(indicador, "ACAO") or (definicao.unidade if definicao else None),
        "escala": escala_do_indicador(indicador) or (definicao.escala if definicao else None),
        "fonte": fonte,
        "fonte_primaria": fonte_primaria,
        "periodo": periodo,
        "formula": formula or FORMULAS.get(indicador),
        "data_referencia": data_referencia,
        "data_coleta": data_coleta or datetime.now(),
        "status": status or semantica,
        "origem": origem,
        "observacao": observacao,
    }


def resultado_nao_aplicavel(indicador, ticker, data_referencia, periodo, **kwargs) -> dict[str, Any]:
    return montar_resultado(
        indicador,
        None,
        ticker=ticker,
        data_referencia=data_referencia,
        periodo=periodo,
        semantica=NAO_APLICAVEL,
        observacao=kwargs.pop("observacao", "Indicador nao aplicavel a bancos/seguradoras."),
        **kwargs,
    )


def resultado_ausente(indicador, ticker, data_referencia, periodo, observacao, **kwargs) -> dict[str, Any]:
    return montar_resultado(
        indicador,
        None,
        ticker=ticker,
        data_referencia=data_referencia,
        periodo=periodo,
        semantica=AUSENTE,
        observacao=observacao,
        **kwargs,
    )


def resultado_nao_calculavel(indicador, ticker, data_referencia, periodo, observacao, **kwargs) -> dict[str, Any]:
    return montar_resultado(
        indicador,
        None,
        ticker=ticker,
        data_referencia=data_referencia,
        periodo=periodo,
        semantica=NAO_CALCULAVEL,
        observacao=observacao,
        **kwargs,
    )


def resultado_invalido(indicador, ticker, data_referencia, periodo, observacao, **kwargs) -> dict[str, Any]:
    return montar_resultado(
        indicador,
        None,
        ticker=ticker,
        data_referencia=data_referencia,
        periodo=periodo,
        semantica=INVALIDO,
        observacao=observacao,
        **kwargs,
    )


def _pontos_anuais_dfp(registros: list, campo: str) -> list[tuple[date, float]]:
    pontos = []
    for reg in registros:
        if _tipo_doc(reg) != "DFP":
            continue
        data = _data_ref(reg)
        valor = _numero_campo(reg, campo)
        if data is None or valor is None:
            continue
        if data.month != 12 or data.day != 31:
            continue
        pontos.append((data, valor))
    pontos.sort(key=lambda item: item[0])
    por_ano = {}
    for data, valor in pontos:
        por_ano[data.year] = (data, valor)
    return [por_ano[ano] for ano in sorted(por_ano)]


def calcular_cagr(valores: Iterable[float], anos: int = 5) -> float | None:
    serie = [parsear_numero(v) for v in valores]
    if any(v is None for v in serie):
        return None
    if len(serie) < 2 or anos <= 0:
        return None
    inicio, fim = serie[0], serie[-1]
    if inicio is None or fim is None or inicio <= 0 or fim < 0:
        return None
    return (fim / inicio) ** (1.0 / anos) - 1.0


def _anos_cagr_dfp(por_ano: dict[int, float], data_ref: date) -> tuple[int | None, str | None]:
    ano_fim = data_ref.year if data_ref.month == 12 else data_ref.year - 1
    if ano_fim not in por_ano:
        anos_disponiveis = [ano for ano in por_ano if ano <= data_ref.year]
        if not anos_disponiveis:
            return None, "sem_dfp_anual"
        ano_fim = max(anos_disponiveis)
    ano_ini = ano_fim - 5
    if ano_ini not in por_ano:
        return None, "sem_t_menos_5"
    return ano_fim, None


def _cagr_dfp_5a(
    registros: list,
    ticker: str,
    data_ref: date,
    *,
    indicador: str,
    campo: str,
    rotulo: str,
    exigir_extremos_positivos: bool,
) -> dict[str, Any]:
    pontos = _pontos_anuais_dfp(registros, campo)
    if len(pontos) < 2:
        return resultado_ausente(
            indicador, ticker, data_ref, PERIODO_CAGR_5A,
            "NAO CALCULAVEL: serie DFP insuficiente (empresa nova ou historico ausente).",
        )
    por_ano = {data.year: valor for data, valor in pontos}
    ano_fim, motivo = _anos_cagr_dfp(por_ano, data_ref)
    if motivo == "sem_dfp_anual":
        return resultado_ausente(
            indicador, ticker, data_ref, PERIODO_CAGR_5A,
            f"NAO CALCULAVEL: sem DFP anual de {rotulo}.",
        )
    if motivo == "sem_t_menos_5":
        return resultado_ausente(
            indicador, ticker, data_ref, PERIODO_CAGR_5A,
            f"NAO CALCULAVEL: sem DFP de {rotulo} ha 5 anos.",
        )
    ano_ini = ano_fim - 5
    inicio = por_ano[ano_ini]
    fim = por_ano[ano_fim]
    if exigir_extremos_positivos:
        if inicio <= 0 or fim <= 0:
            return resultado_ausente(
                indicador, ticker, data_ref, PERIODO_CAGR_5A,
                f"NAO CALCULAVEL: {rotulo} inicial/final nao positivo.",
            )
    elif inicio <= 0:
        return resultado_ausente(
            indicador, ticker, data_ref, PERIODO_CAGR_5A,
            f"NAO CALCULAVEL: {rotulo} inicial nao positiva.",
        )
    valor = calcular_cagr([inicio, fim], anos=5)
    if valor is None:
        return resultado_ausente(
            indicador, ticker, data_ref, PERIODO_CAGR_5A,
            "NAO CALCULAVEL: CAGR indefinido.",
        )
    return montar_resultado(
        indicador, valor, ticker=ticker, data_referencia=data_ref,
        periodo=PERIODO_CAGR_5A, fonte_primaria="CVM/DFP",
        observacao=f"DFP {ano_ini} -> {ano_fim}; fonte CVM.",
    )


def cagr_receita_5a(registros: list, ticker: str, data_ref: date) -> dict[str, Any]:
    return _cagr_dfp_5a(
        registros, ticker, data_ref,
        indicador="cagr_rec_5a", campo="receita", rotulo="receita",
        exigir_extremos_positivos=False,
    )


def cagr_lucro_5a(registros: list, ticker: str, data_ref: date) -> dict[str, Any]:
    return _cagr_dfp_5a(
        registros, ticker, data_ref,
        indicador="cagr_lucro_5a", campo="lucro_liquido", rotulo="lucro",
        exigir_extremos_positivos=True,
    )


def calcular_peg(
    pl_result: dict[str, Any],
    cagr_lucro_result: dict[str, Any],
    ticker: str,
    data_ref: date,
    **kwargs,
) -> dict[str, Any]:
    """PEG deterministico: P/L dividido pelo CAGR do lucro em percentual.

    Yahoo ``trailingPegRatio`` e apenas benchmark externo; nunca substitui
    este valor. Regras explicitas de semantica:

    - CAGR do lucro ausente/nao calculavel -> AUSENTE;
    - P/L ausente -> AUSENTE;
    - P/L nao positivo -> NAO_CALCULAVEL;
    - CAGR do lucro nao positivo -> NAO_CALCULAVEL;
    - valor ilegivel -> INVALIDO.
    """
    sem_pl = pl_result.get("semantica")
    sem_cagr = cagr_lucro_result.get("semantica")
    if sem_pl == INVALIDO or sem_cagr == INVALIDO:
        return resultado_invalido(
            "peg_ratio", ticker, data_ref, PERIODO_PEG,
            "PEG INVALIDO: P/L ou CAGR do lucro ilegivel.", **kwargs,
        )
    if sem_cagr == NAO_APLICAVEL:
        return resultado_nao_aplicavel(
            "peg_ratio", ticker, data_ref, PERIODO_PEG,
            observacao="PEG NAO APLICAVEL: CAGR do lucro nao aplicavel.",
            **kwargs,
        )
    if sem_cagr in (AUSENTE, NAO_CALCULAVEL):
        return resultado_ausente(
            "peg_ratio", ticker, data_ref, PERIODO_PEG,
            "PEG AUSENTE: CAGR do lucro 5a indisponivel.",
            **kwargs,
        )
    if sem_pl in (AUSENTE, NAO_CALCULAVEL, NAO_APLICAVEL):
        return resultado_ausente(
            "peg_ratio", ticker, data_ref, PERIODO_PEG,
            "PEG AUSENTE: P/L indisponivel.",
            **kwargs,
        )
    pl = parsear_numero(pl_result.get("valor"))
    cagr = parsear_numero(cagr_lucro_result.get("valor"))
    if pl is None or cagr is None:
        return resultado_ausente(
            "peg_ratio", ticker, data_ref, PERIODO_PEG,
            "PEG AUSENTE: P/L ou CAGR do lucro sem valor.",
            **kwargs,
        )
    if pl <= 0:
        return resultado_nao_calculavel(
            "peg_ratio", ticker, data_ref, PERIODO_PEG,
            "PEG NAO CALCULAVEL: P/L nao positivo.",
            **kwargs,
        )
    if cagr <= 0:
        return resultado_nao_calculavel(
            "peg_ratio", ticker, data_ref, PERIODO_PEG,
            "PEG NAO CALCULAVEL: CAGR do lucro 5a nao positivo.",
            **kwargs,
        )
    valor = derivar_divisao(pl, cagr * 100.0)
    if valor is None:
        return resultado_nao_calculavel(
            "peg_ratio", ticker, data_ref, PERIODO_PEG,
            "PEG NAO CALCULAVEL: razao indefinida.", **kwargs,
        )
    return montar_resultado(
        "peg_ratio", valor, ticker=ticker, data_referencia=data_ref,
        periodo=PERIODO_PEG, fonte_primaria=ORIGEM_CALCULO,
        observacao="PEG = P/L / (CAGR Lucro 5a em %); CVM.",
        **kwargs,
    )


def _ytd_por_data(registros: list, campo: str) -> dict[date, float]:
    resultado = {}
    for reg in registros:
        data = _data_ref(reg)
        valor = _numero_campo(reg, campo)
        if data is None or valor is None or not eh_ytd(reg):
            continue
        atual = resultado.get(data)
        if atual is None or _tipo_doc(reg) == "DFP":
            resultado[data] = valor
    return resultado


def calcular_ltm(registros: list, campo: str, na_data: date | None = None) -> float | None:
    """LTM de conta de fluxo YTD. Ausencia/serie incompleta -> None, nunca 0 inventado."""
    ytd = _ytd_por_data(registros, campo)
    if not ytd:
        return None
    datas = sorted(d for d in ytd if na_data is None or d <= na_data)
    if not datas:
        return None
    atual = datas[-1]
    valor_atual = ytd[atual]
    if atual.month == 12 and atual.day == 31:
        return valor_atual
    mesmo_ano_anterior = date(atual.year - 1, atual.month, atual.day)
    dfp_anterior = date(atual.year - 1, 12, 31)
    if mesmo_ano_anterior in ytd and dfp_anterior in ytd:
        return valor_atual + (ytd[dfp_anterior] - ytd[mesmo_ano_anterior])
    return None


def _ultimo_balanco(registros: list, ate: date | None = None):
    candidatos = []
    for reg in registros:
        data = _data_ref(reg)
        if data is None:
            continue
        if ate is not None and data > ate:
            continue
        candidatos.append(reg)
    if not candidatos:
        return None
    candidatos.sort(key=lambda r: (_data_ref(r), 1 if _tipo_doc(r) == "DFP" else 0))
    return candidatos[-1]


def _divisao_indicador(indicador, numerador, denominador, ticker, data_ref, periodo, formula=None):
    valor = derivar_divisao(numerador, denominador)
    if numerador is None or denominador is None:
        return resultado_ausente(
            indicador, ticker, data_ref, periodo,
            "NAO CALCULAVEL: numerador ou denominador ausente.",
            formula=formula,
        )
    if parsear_numero(denominador) == 0:
        return resultado_ausente(
            indicador, ticker, data_ref, periodo,
            "NAO CALCULAVEL: divisao por zero.",
            formula=formula,
        )
    if valor is None:
        return resultado_ausente(
            indicador, ticker, data_ref, periodo,
            "NAO CALCULAVEL: razao indefinida.",
            formula=formula,
        )
    return montar_resultado(
        indicador, valor, ticker=ticker, data_referencia=data_ref,
        periodo=periodo, formula=formula,
    )


def _mercado_mais_recente(session: Session | None, ativo_id: int):
    if session is None or ativo_id is None:
        return None
    return (
        session.query(SnapshotAcao)
        .filter(SnapshotAcao.ativo_id == ativo_id)
        .order_by(SnapshotAcao.data_referencia.desc())
        .first()
    )


def comparar_benchmark_externo(valor_cvm, valor_externo, tolerancia=0.15) -> dict[str, Any] | None:
    """Compara CVM com fonte externa. Nunca sobrescreve o valor CVM."""
    cvm = parsear_numero(valor_cvm)
    externo = parsear_numero(valor_externo)
    if cvm is None or externo is None:
        return None
    if cvm == 0:
        if externo == 0:
            return None
        return {
            "status": "WARNING",
            "regra": "DIVERGENCIA_BENCHMARK",
            "observacao": "Benchmark externo diverge da CVM; CVM preservada.",
            "valor_cvm": cvm,
            "valor_externo": externo,
        }
    if abs(externo - cvm) / abs(cvm) > tolerancia:
        return {
            "status": "WARNING",
            "regra": "DIVERGENCIA_BENCHMARK",
            "observacao": "Benchmark externo diverge da CVM; CVM preservada.",
            "valor_cvm": cvm,
            "valor_externo": externo,
        }
    return None


def calcular_indicadores_ticker(
    ticker: str,
    registros: list,
    *,
    session: Session | None = None,
    ativo_id: int | None = None,
    mercado=None,
    data_coleta: datetime | None = None,
) -> list[dict[str, Any]]:
    if not registros:
        return []
    registros = sorted(registros, key=lambda r: (_data_ref(r) or date.min, _tipo_doc(r)))
    ultimo = _ultimo_balanco(registros)
    if ultimo is None:
        return []
    data_ref = _data_ref(ultimo)
    coletado = data_coleta or datetime.now()
    extras = {"data_coleta": coletado}

    classificacao = _setor_catalogo(ticker, session)

    def na_ou_calc(indicador, periodo, factory):
        status = consultar_aplicabilidade(indicador, classificacao, ticker=ticker)
        if status == NAO_APLICAVEL:
            return resultado_nao_aplicavel(indicador, ticker, data_ref, periodo, **extras)
        return factory()

    receita_ltm = calcular_ltm(registros, "receita", data_ref)
    lucro_ltm = calcular_ltm(registros, "lucro_liquido", data_ref)
    ebit_ltm = calcular_ltm(registros, "ebit", data_ref)
    ebitda_ltm = calcular_ltm(registros, "ebitda", data_ref)
    lucro_bruto_ltm = calcular_ltm(registros, "lucro_bruto", data_ref)
    fco_ltm = calcular_ltm(registros, "fco", data_ref)

    def _ltm_res(nome, valor):
        if valor is None:
            return resultado_ausente(
                nome, ticker, data_ref, PERIODO_LTM,
                "NAO CALCULAVEL: serie trimestral/anual insuficiente para LTM.",
                **extras,
            )
        return montar_resultado(nome, valor, ticker=ticker, data_referencia=data_ref,
                                periodo=PERIODO_LTM, **extras)

    cagr_lucro_result = cagr_lucro_5a(registros, ticker, data_ref)

    resultados = [
        _ltm_res("receita_ltm", receita_ltm),
        _ltm_res("lucro_liquido_ltm", lucro_ltm),
        na_ou_calc("ebit_ltm", PERIODO_LTM, lambda: _ltm_res("ebit_ltm", ebit_ltm)),
        na_ou_calc("ebitda_ltm", PERIODO_LTM, lambda: _ltm_res("ebitda_ltm", ebitda_ltm)),
        na_ou_calc("lucro_bruto_ltm", PERIODO_LTM, lambda: _ltm_res("lucro_bruto_ltm", lucro_bruto_ltm)),
        _ltm_res("fco_ltm", fco_ltm),
        na_ou_calc("marg_bruta", PERIODO_LTM, lambda: _divisao_indicador(
            "marg_bruta", lucro_bruto_ltm, receita_ltm, ticker, data_ref, PERIODO_LTM)),
        na_ou_calc("marg_ebit", PERIODO_LTM, lambda: _divisao_indicador(
            "marg_ebit", ebit_ltm, receita_ltm, ticker, data_ref, PERIODO_LTM)),
        _divisao_indicador("marg_liquida", lucro_ltm, receita_ltm, ticker, data_ref, PERIODO_LTM),
        _divisao_indicador(
            "roe", lucro_ltm, _numero_campo(ultimo, "patrimonio_liquido"),
            ticker, data_ref, PERIODO_LTM, FORMULAS["roe"],
        ),
        _divisao_indicador(
            "roa", lucro_ltm, _numero_campo(ultimo, "ativo_total"),
            ticker, data_ref, PERIODO_LTM, FORMULAS["roa"],
        ),
        _divisao_indicador(
            "patrimonio_ativos", _numero_campo(ultimo, "patrimonio_liquido"),
            _numero_campo(ultimo, "ativo_total"),
            ticker, data_ref, PERIODO_PONTO, FORMULAS["patrimonio_ativos"],
        ),
        _divisao_indicador(
            "passivos_ativos", _numero_campo(ultimo, "passivo_total"),
            _numero_campo(ultimo, "ativo_total"),
            ticker, data_ref, PERIODO_PONTO, FORMULAS["passivos_ativos"],
        ),
        _divisao_indicador(
            "giro_ativos", receita_ltm, _numero_campo(ultimo, "ativo_total"),
            ticker, data_ref, PERIODO_LTM, FORMULAS["giro_ativos"],
        ),
        na_ou_calc("roic", PERIODO_LTM, lambda: _divisao_indicador(
            "roic", ebit_ltm,
            None if None in (
                _numero_campo(ultimo, "patrimonio_liquido"),
                _numero_campo(ultimo, "divida_bruta"),
                _numero_campo(ultimo, "caixa"),
            ) else (
                _numero_campo(ultimo, "patrimonio_liquido")
                + _numero_campo(ultimo, "divida_bruta")
                - _numero_campo(ultimo, "caixa")
            ),
            ticker, data_ref, PERIODO_LTM, FORMULAS["roic"],
        )),
        na_ou_calc("liq_corrente", PERIODO_PONTO, lambda: _divisao_indicador(
            "liq_corrente",
            _numero_campo(ultimo, "ativo_circulante"),
            _numero_campo(ultimo, "passivo_circulante"),
            ticker, data_ref, PERIODO_PONTO,
        )),
        na_ou_calc("div_liq_patrimonio", PERIODO_PONTO, lambda: _divisao_indicador(
            "div_liq_patrimonio",
            _numero_campo(ultimo, "divida_liquida"),
            _numero_campo(ultimo, "patrimonio_liquido"),
            ticker, data_ref, PERIODO_PONTO,
        )),
        na_ou_calc("div_liq_ebit", PERIODO_LTM, lambda: _divisao_indicador(
            "div_liq_ebit",
            _numero_campo(ultimo, "divida_liquida"),
            ebit_ltm, ticker, data_ref, PERIODO_LTM,
        )),
        cagr_receita_5a(registros, ticker, data_ref),
        cagr_lucro_result,
    ]

    snap = mercado if mercado is not None else _mercado_mais_recente(session, ativo_id)
    valor_mercado = parsear_numero(getattr(snap, "valor_mercado", None) if snap is not None else None)
    qtd_acoes = None
    if snap is not None:
        preco = parsear_numero(getattr(snap, "preco", None))
        if valor_mercado is not None and preco not in (None, 0):
            qtd_acoes = derivar_divisao(valor_mercado, preco)

    resultados.append(_divisao_indicador(
        "lpa", lucro_ltm, qtd_acoes, ticker, data_ref, PERIODO_LTM, FORMULAS["lpa"],
    ))
    resultados.append(_divisao_indicador(
        "vpa", _numero_campo(ultimo, "patrimonio_liquido"), qtd_acoes,
        ticker, data_ref, PERIODO_PONTO, FORMULAS["vpa"],
    ))
    pl_result = _divisao_indicador(
        "pl", valor_mercado, lucro_ltm, ticker, data_ref, PERIODO_LTM, FORMULAS["pl"],
    )
    resultados.append(pl_result)
    resultados.append(_divisao_indicador(
        "pvp", valor_mercado, _numero_campo(ultimo, "patrimonio_liquido"),
        ticker, data_ref, PERIODO_PONTO, FORMULAS["pvp"],
    ))
    resultados.append(_divisao_indicador(
        "psr", valor_mercado, receita_ltm, ticker, data_ref, PERIODO_LTM, FORMULAS["psr"],
    ))
    resultados.append(_divisao_indicador(
        "p_ativo", valor_mercado, _numero_campo(ultimo, "ativo_total"),
        ticker, data_ref, PERIODO_PONTO, FORMULAS["p_ativo"],
    ))
    resultados.append(na_ou_calc("p_ebit", PERIODO_LTM, lambda: _divisao_indicador(
        "p_ebit", valor_mercado, ebit_ltm, ticker, data_ref, PERIODO_LTM, FORMULAS["p_ebit"],
    )))
    ev = None
    if valor_mercado is not None and _numero_campo(ultimo, "divida_liquida") is not None:
        ev = valor_mercado + _numero_campo(ultimo, "divida_liquida")
    resultados.append(na_ou_calc("ev_ebit", PERIODO_LTM, lambda: _divisao_indicador(
        "ev_ebit", ev, ebit_ltm, ticker, data_ref, PERIODO_LTM, FORMULAS["ev_ebit"],
    )))
    resultados.append(calcular_peg(pl_result, cagr_lucro_result, ticker, data_ref, **extras))

    for item in resultados:
        item.setdefault("data_coleta", coletado)
    return resultados


def persistir_indicadores_cvm(session: Session, tickers: Iterable[str] | None = None) -> int:
    """Calcula e grava indicadores CVM sem tocar snapshots_acoes."""
    from pipeline_dados.banco_dados import Ativo, TipoAtivo

    query = session.query(Ativo).filter(Ativo.tipo == TipoAtivo.ACAO)
    if tickers:
        alvos = {str(t).strip().upper() for t in tickers if t}
        query = query.filter(Ativo.ticker.in_(alvos))
    gravados = 0
    coletado = datetime.now()
    for ativo in query.all():
        registros = (
            session.query(DadosFinanceirosAcoes)
            .filter(DadosFinanceirosAcoes.ativo_id == ativo.id)
            .all()
        )
        calculados = calcular_indicadores_ticker(
            ativo.ticker, registros, session=session, ativo_id=ativo.id, data_coleta=coletado,
        )
        for item in calculados:
            existente = (
                session.query(IndicadorCvmAcao)
                .filter_by(
                    ativo_id=ativo.id,
                    indicador=item["indicador"],
                    data_referencia=item["data_referencia"],
                    periodo=item["periodo"],
                )
                .first()
            )
            campos = {
                "ticker": ativo.ticker,
                "valor": item["valor"],
                "semantica": item["semantica"],
                "unidade": item["unidade"],
                "escala": item["escala"],
                "fonte": item["fonte"],
                "fonte_primaria": item["fonte_primaria"],
                "formula": item["formula"],
                "data_coleta": item["data_coleta"],
                "status": item["status"],
                "origem": item["origem"],
                "observacao": item["observacao"],
            }
            if existente:
                for chave, valor in campos.items():
                    setattr(existente, chave, valor)
            else:
                session.add(IndicadorCvmAcao(
                    ativo_id=ativo.id,
                    indicador=item["indicador"],
                    data_referencia=item["data_referencia"],
                    periodo=item["periodo"],
                    **campos,
                ))
            gravados += 1
        session.commit()
    return gravados


def mapa_cagr_cvm_producao(
    session: Session | None,
    tickers: Iterable[str] | None = None,
) -> dict[str, dict[str, float]]:
    """CAGR CVM calculavel para o fluxo de producao. Sem valor valido -> omitido."""
    return _mapa_indicadores_producao(session, tickers, ("cagr_rec_5a", "cagr_lucro_5a"))


# Indicadores deterministicos calculados pela CVM que entram no fluxo de
# producao (BD_Acoes -> snapshot -> API). Yahoo/Fundamentus continuam como
# fallback/benchmark, nunca substituindo o valor CVM quando calculavel.
INDICADORES_CVM_PRODUCAO = (
    "cagr_rec_5a",
    "cagr_lucro_5a",
    "patrimonio_ativos",
    "passivos_ativos",
    "giro_ativos",
    "peg_ratio",
)


def mapa_indicadores_cvm_producao(
    session: Session | None,
    tickers: Iterable[str] | None = None,
) -> dict[str, dict[str, float]]:
    """Indicadores CVM deterministicos para o fluxo de producao.

    Inclui os dois CAGR, os tres indicadores contabeis (patrimonio/ativos,
    passivos/ativos, giro do ativo) e o PEG deterministico. Semantica
    diferente de PRESENTE nunca e transportada (ausencia nunca vira zero).
    """
    return _mapa_indicadores_producao(session, tickers, INDICADORES_CVM_PRODUCAO)


def _mapa_indicadores_producao(
    session: Session | None,
    tickers: Iterable[str] | None,
    indicadores: Iterable[str],
) -> dict[str, dict[str, float]]:
    if session is None:
        return {}
    alvos = {str(t).strip().upper() for t in (tickers or []) if t}
    nomes = tuple(indicadores)
    if not nomes:
        return {}
    query = session.query(IndicadorCvmAcao).filter(
        IndicadorCvmAcao.indicador.in_(nomes),
    )
    if alvos:
        query = query.filter(IndicadorCvmAcao.ticker.in_(alvos))
    linhas = query.order_by(IndicadorCvmAcao.data_referencia.desc()).all()
    saida: dict[str, dict[str, float]] = {}
    vistos: set[tuple[str, str]] = set()
    for linha in linhas:
        chave = (linha.ticker, linha.indicador)
        if chave in vistos:
            continue
        vistos.add(chave)
        if linha.semantica != PRESENTE:
            continue
        numero = parsear_numero(linha.valor)
        if numero is None:
            continue
        saida.setdefault(linha.ticker, {})[linha.indicador] = numero
    return saida
