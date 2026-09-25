"""PARTE F.1/F.2: matriz central de aplicabilidade e integracao no calculo."""
from datetime import date
from types import SimpleNamespace

from pipeline_dados.catalogo_ativos import SETOR_NAO_CLASSIFICADO
from pipeline_dados.indicadores_cvm_acoes import (
    calcular_indicadores_ticker,
    indicador_aplicavel_setor,
)
from pipeline_dados.matriz_aplicabilidade import (
    APLICAVEL,
    NATUREZA_BANCO,
    NATUREZA_INDUSTRIAL,
    NATUREZA_SEGURADORA,
    consultar_aplicabilidade,
    resolver_natureza,
)
from pipeline_dados.semantica_indicadores import (
    AUSENTE,
    NAO_APLICAVEL,
    PRESENTE,
    ZERO,
    classificar_semantica,
    indicador_aplicavel,
    interpretar_valor,
)


def test_banco_ebitda_nao_aplicavel():
    assert consultar_aplicabilidade("EBITDA", NATUREZA_BANCO) == NAO_APLICAVEL
    assert consultar_aplicabilidade("ebitda_ltm", subsetor="Bancos") == NAO_APLICAVEL
    assert consultar_aplicabilidade("ebitda", ticker="BBAS3") == NAO_APLICAVEL
    assert consultar_aplicabilidade("marg_ebitda", ticker="BBAS3") == NAO_APLICAVEL
    assert consultar_aplicabilidade("ev_ebitda", ticker="ITUB4") == NAO_APLICAVEL
    assert consultar_aplicabilidade("div_liq_ebitda", ticker="BBAS3") == NAO_APLICAVEL


def test_banco_pl_aplicavel():
    assert consultar_aplicabilidade("P/L", NATUREZA_BANCO) == APLICAVEL
    assert consultar_aplicabilidade("pl", ticker="BBAS3") == APLICAVEL
    assert consultar_aplicabilidade("pvp", ticker="BBAS3") == APLICAVEL
    assert consultar_aplicabilidade("roe", ticker="BBAS3") == APLICAVEL
    assert consultar_aplicabilidade("roa", ticker="BBAS3") == APLICAVEL
    assert consultar_aplicabilidade("cagr_rec_5a", ticker="BBAS3") == APLICAVEL
    assert consultar_aplicabilidade("cagr_lucro_5a", ticker="BBAS3") == APLICAVEL
    assert consultar_aplicabilidade("peg_ratio", ticker="BBAS3") == APLICAVEL


def test_empresa_nao_classificada_nao_assume_nao_aplicavel():
    assert consultar_aplicabilidade("ebitda") == AUSENTE
    assert consultar_aplicabilidade("ebitda", SETOR_NAO_CLASSIFICADO) != NAO_APLICAVEL
    assert consultar_aplicabilidade("ebitda", "AUSENTE") == AUSENTE
    assert consultar_aplicabilidade("ebitda", "Outros") == AUSENTE
    assert consultar_aplicabilidade("ebitda", ticker="EMBR3") == AUSENTE
    assert consultar_aplicabilidade("ebitda", setor="Financeiro") == AUSENTE
    assert consultar_aplicabilidade("ebitda", SETOR_NAO_CLASSIFICADO) == AUSENTE


def test_empresa_industrial_ebitda_aplicavel():
    assert consultar_aplicabilidade("ebitda", NATUREZA_INDUSTRIAL) == APLICAVEL
    assert consultar_aplicabilidade("EBITDA", ticker="PETR4") == APLICAVEL
    assert consultar_aplicabilidade("marg_ebit", ticker="VALE3") == APLICAVEL
    assert consultar_aplicabilidade("roic", ticker="WEGE3") == APLICAVEL
    assert consultar_aplicabilidade("liq_corrente", setor="Materiais Básicos") == APLICAVEL


def test_indicador_desconhecido_nao_inventa_nao_aplicavel():
    assert consultar_aplicabilidade("indicador_inventado", NATUREZA_BANCO) == APLICAVEL
    assert consultar_aplicabilidade(None, NATUREZA_INDUSTRIAL) == APLICAVEL
    assert consultar_aplicabilidade("", ticker="PETR4") == APLICAVEL


def test_matriz_nao_altera_valores_financeiros():
    interpretacao = interpretar_valor("ACAO", "roe", 0.20)
    assert interpretacao["semantica"] == PRESENTE
    assert interpretacao["valor_numerico"] == 0.20
    consultar_aplicabilidade("roe", ticker="PETR4")
    assert interpretar_valor("ACAO", "roe", 0.20)["valor_numerico"] == 0.20
    assert classificar_semantica(0) == ZERO
    assert classificar_semantica(None) == AUSENTE


def test_seguradora_mesma_matriz_operacional():
    assert resolver_natureza(ticker="BBSE3") == NATUREZA_SEGURADORA
    assert consultar_aplicabilidade("roic", ticker="BBSE3") == NAO_APLICAVEL
    assert consultar_aplicabilidade("pl", ticker="BBSE3") == APLICAVEL
    assert consultar_aplicabilidade("roe", subsetor="Seguros e Resseguros") == APLICAVEL


def test_tipo_fii_continua_nao_aplicavel_por_tipo():
    assert indicador_aplicavel("FII", "roe") is False
    assert consultar_aplicabilidade("roe", tipo="FII") == NAO_APLICAVEL


def _reg_calc(**kwargs):
    data = kwargs.pop("data", date(2024, 12, 31))
    base = {
        "data_referencia": data,
        "tipo_doc": "DFP",
        "receita": 100.0,
        "lucro_liquido": 20.0,
        "ebit": 30.0,
        "ebitda": 40.0,
        "lucro_bruto": 50.0,
        "patrimonio_liquido": 50.0,
        "ativo_total": 200.0,
        "caixa": 5.0,
        "divida_bruta": 15.0,
        "divida_liquida": 10.0,
        "ativo_circulante": 80.0,
        "passivo_circulante": 40.0,
        "fco": 12.0,
        "dt_ini_exerc": date(data.year, 1, 1),
        "passivo_total": 150.0,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def _mapa(ticker):
    return {item["indicador"]: item for item in calcular_indicadores_ticker(ticker, [_reg_calc()])}


def test_integracao_matriz_banco_ebitda_nao_calcula_nem_vira_zero():
    mapa = _mapa("BBAS3")
    for indicador in ("ebitda_ltm", "marg_ebit", "p_ebit", "ev_ebit", "div_liq_ebit", "roic", "liq_corrente"):
        assert mapa[indicador]["semantica"] == NAO_APLICAVEL, indicador
        assert mapa[indicador]["valor"] is None, indicador
        assert mapa[indicador]["valor"] != 0


def test_integracao_matriz_banco_pl_roe_roa_continuam_calculando():
    mapa = _mapa("BBAS3")
    assert mapa["roe"]["valor"] == 0.4
    assert mapa["roa"]["valor"] == 0.1
    assert mapa["roe"]["semantica"] != NAO_APLICAVEL
    assert mapa["pl"]["semantica"] != NAO_APLICAVEL
    assert mapa["pvp"]["semantica"] != NAO_APLICAVEL


def test_integracao_matriz_industrial_ebitda_calcula():
    mapa = _mapa("PETR4")
    assert mapa["ebitda_ltm"]["valor"] == 40.0
    assert mapa["ebitda_ltm"]["semantica"] != NAO_APLICAVEL
    assert mapa["marg_ebit"]["valor"] == 0.3


def test_integracao_classificacao_ausente_nao_vira_nao_aplicavel():
    mapa = _mapa("EMBR3")
    assert mapa["ebitda_ltm"]["semantica"] != NAO_APLICAVEL
    assert mapa["ebitda_ltm"]["valor"] == 40.0
    assert indicador_aplicavel_setor("EMBR3", "ebitda_ltm") is True


def test_cvm_nao_foi_alterada_pela_matriz():
    assert indicador_aplicavel_setor("BBAS3", "ebitda_ltm") is False
    assert indicador_aplicavel_setor("BBAS3", "roe") is True
    assert indicador_aplicavel_setor("PETR4", "ebitda_ltm") is True
    assert callable(calcular_indicadores_ticker)


def test_matriz_prioritaria_banco_vs_industrial():
    banco_na = (
        "EBITDA", "Margem EBITDA", "EV/EBITDA", "Dívida Líquida/EBITDA",
        "P/EBIT", "Margem EBIT", "P/Capital de Giro",
        "P/Ativo Circulante Líquido", "Liquidez Corrente", "ROIC",
    )
    sempre_aplicavel = (
        "P/L", "P/VP", "P/Ativos", "PSR", "ROE", "ROA",
        "Patrimônio/Ativos", "Passivos/Ativos", "Giro de Ativos",
        "CAGR Receita 5A", "CAGR Lucro 5A", "PEG",
    )
    for indicador in banco_na:
        assert consultar_aplicabilidade(indicador, NATUREZA_BANCO) == NAO_APLICAVEL, indicador
        assert consultar_aplicabilidade(indicador, NATUREZA_INDUSTRIAL) == APLICAVEL, indicador
    for indicador in sempre_aplicavel:
        assert consultar_aplicabilidade(indicador, NATUREZA_BANCO) == APLICAVEL, indicador
        assert consultar_aplicabilidade(indicador, NATUREZA_INDUSTRIAL) == APLICAVEL, indicador
