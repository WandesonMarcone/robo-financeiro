"""Camada CVM DFP/ITR de acoes: parse, LTM, CAGR, setor e ausencia."""
from datetime import date
from types import SimpleNamespace

import pandas as pd
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from pipeline_dados.banco_dados import (
    Base,
    DadosFinanceirosAcoes,
    IndicadorCvmAcao,
    TipoAtivo,
    garantir_colunas_cvm_acoes,
)
from pipeline_dados.catalogo_ativos import garantir_ativo, registrar_no_catalogo
from pipeline_dados.coletor_cvm import AcoesCVMReader, derivar_indicadores_cvm
from pipeline_dados.indicadores_cvm_acoes import (
    NAO_APLICAVEL,
    calcular_cagr,
    calcular_indicadores_ticker,
    calcular_ltm,
    cagr_lucro_5a,
    cagr_receita_5a,
    comparar_benchmark_externo,
    indicador_aplicavel_setor,
    mapa_cagr_cvm_producao,
    natureza_financeira,
    persistir_indicadores_cvm,
)
from pipeline_dados.qualidade_dados import WARNING, regra_coerencia_dfp_itr
from pipeline_dados.semantica_indicadores import AUSENTE, ZERO


def _sessao():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)(), engine


def _reg(
    data, tipo_doc, receita=None, lucro=None, ebit=None, ebitda=None,
    lucro_bruto=None, pl=None, ativo=None, caixa=None, divida_bruta=None,
    divida_liquida=None, ativo_circ=None, passivo_circ=None, fco=None,
    dt_ini=None, **kwargs
):
    base = {
        "data_referencia": data,
        "tipo_doc": tipo_doc,
        "receita": receita,
        "lucro_liquido": lucro,
        "ebit": ebit,
        "ebitda": ebitda,
        "lucro_bruto": lucro_bruto,
        "patrimonio_liquido": pl,
        "ativo_total": ativo,
        "caixa": caixa,
        "divida_bruta": divida_bruta,
        "divida_liquida": divida_liquida,
        "ativo_circulante": ativo_circ,
        "passivo_circulante": passivo_circ,
        "fco": fco,
        "dt_ini_exerc": dt_ini or date(data.year, 1, 1),
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def _por_indicador(resultados):
    return {item["indicador"]: item for item in resultados}


def test_derivar_preserva_ebit_e_depreciacao():
    reg = derivar_indicadores_cvm({
        "divida_curto_prazo": 40.0,
        "divida_longo_prazo": 60.0,
        "caixa": 15.0,
        "ebit": 100.0,
        "depreciacao": -20.0,
    })
    assert reg["ebitda"] == 120.0
    assert reg["ebit"] == 100.0
    assert reg["depreciacao"] == -20.0


def test_processar_preserva_ebit_circulante_e_versao():
    session, _ = _sessao()
    registrar_no_catalogo(session, "PETR4", TipoAtivo.ACAO, cnpj="33.000.167/0001-01")
    garantir_ativo(session, "PETR4", TipoAtivo.ACAO, cnpj="33.000.167/0001-01")
    session.commit()
    leitor = AcoesCVMReader(session)
    leitor.meus_tickers = ["PETR4"]
    leitor.cnpjs_alvo = {"33000167000101"}
    df = pd.DataFrame(
        [
            {"CNPJ_CIA": "33.000.167/0001-01", "DT_REFER": "2025-12-31",
             "DT_INI_EXERC": "2025-01-01", "ORDEM_EXERC": "ÚLTIMO",
             "CD_CONTA": "1", "VL_CONTA": 100.0, "VERSAO": 1},
            {"CNPJ_CIA": "33.000.167/0001-01", "DT_REFER": "2025-12-31",
             "DT_INI_EXERC": "2025-01-01", "ORDEM_EXERC": "ÚLTIMO",
             "CD_CONTA": "1.01", "VL_CONTA": 30.0, "VERSAO": 1},
            {"CNPJ_CIA": "33.000.167/0001-01", "DT_REFER": "2025-12-31",
             "DT_INI_EXERC": "2025-01-01", "ORDEM_EXERC": "ÚLTIMO",
             "CD_CONTA": "2.01", "VL_CONTA": 20.0, "VERSAO": 1},
            {"CNPJ_CIA": "33.000.167/0001-01", "DT_REFER": "2025-12-31",
             "DT_INI_EXERC": "2025-01-01", "ORDEM_EXERC": "ÚLTIMO",
             "CD_CONTA": "3.05", "VL_CONTA": 12.0, "VERSAO": 1},
            {"CNPJ_CIA": "33.000.167/0001-01", "DT_REFER": "2025-12-31",
             "DT_INI_EXERC": "2025-01-01", "ORDEM_EXERC": "ÚLTIMO",
             "CD_CONTA": "6.01.01.04", "VL_CONTA": 2.0, "VERSAO": 1},
        ]
    )
    regs = leitor._processar_itr_dfp({"dre": df}, tipo_doc="DFP")
    assert len(regs) == 1
    assert regs[0]["ebit"] == 12000.0
    assert regs[0]["depreciacao"] == 2000.0
    assert regs[0]["ebitda"] == 14000.0
    assert regs[0]["ativo_circulante"] == 30000.0
    assert regs[0]["passivo_circulante"] == 20000.0
    assert regs[0]["versao"] == 1
    assert regs[0]["dt_ini_exerc"] == date(2025, 1, 1)
    session.close()


def test_reapresentacao_usa_maior_versao():
    session, _ = _sessao()
    registrar_no_catalogo(session, "PETR4", TipoAtivo.ACAO, cnpj="33.000.167/0001-01")
    garantir_ativo(session, "PETR4", TipoAtivo.ACAO, cnpj="33.000.167/0001-01")
    session.commit()
    leitor = AcoesCVMReader(session)
    leitor.cnpjs_alvo = {"33000167000101"}
    df = pd.DataFrame(
        [
            {"CNPJ_CIA": "33.000.167/0001-01", "DT_REFER": "2025-12-31",
             "ORDEM_EXERC": "ÚLTIMO", "CD_CONTA": "3.01", "VL_CONTA": 80.0, "VERSAO": 1},
            {"CNPJ_CIA": "33.000.167/0001-01", "DT_REFER": "2025-12-31",
             "ORDEM_EXERC": "ÚLTIMO", "CD_CONTA": "3.01", "VL_CONTA": 90.0, "VERSAO": 2},
        ]
    )
    regs = leitor._processar_itr_dfp({"dre": df}, tipo_doc="DFP")
    assert len(regs) == 1
    assert regs[0]["receita"] == 90000.0
    assert regs[0]["versao"] == 2
    session.close()


def test_nan_nao_vira_zero():
    session, _ = _sessao()
    registrar_no_catalogo(session, "PETR4", TipoAtivo.ACAO, cnpj="33.000.167/0001-01")
    session.commit()
    leitor = AcoesCVMReader(session)
    leitor.cnpjs_alvo = {"33000167000101"}
    df = pd.DataFrame(
        [
            {"CNPJ_CIA": "33.000.167/0001-01", "DT_REFER": "2025-12-31",
             "ORDEM_EXERC": "ÚLTIMO", "CD_CONTA": "3.01", "VL_CONTA": float("nan")},
            {"CNPJ_CIA": "33.000.167/0001-01", "DT_REFER": "2025-12-31",
             "ORDEM_EXERC": "ÚLTIMO", "CD_CONTA": "3.11", "VL_CONTA": 12.0},
        ]
    )
    regs = leitor._processar_itr_dfp({"dre": df}, tipo_doc="DFP")
    assert regs[0]["receita"] is None
    assert regs[0]["lucro_liquido"] == 12000.0
    session.close()


def test_ltm_ytd_completo():
    registros = [
        _reg(date(2024, 12, 31), "DFP", receita=100.0),
        _reg(date(2024, 9, 30), "ITR", receita=70.0),
        _reg(date(2025, 9, 30), "ITR", receita=80.0),
    ]
    assert calcular_ltm(registros, "receita", date(2025, 9, 30)) == 110.0


def test_ltm_dfp_dezembro_e_o_proprio_ano():
    registros = [_reg(date(2025, 12, 31), "DFP", receita=200.0)]
    assert calcular_ltm(registros, "receita", date(2025, 12, 31)) == 200.0


def test_ltm_ausente_nao_vira_zero():
    registros = [_reg(date(2025, 9, 30), "ITR", receita=80.0)]
    assert calcular_ltm(registros, "receita", date(2025, 9, 30)) is None


def test_divisao_por_zero_ausente():
    registros = [
        _reg(date(2024, 12, 31), "DFP", receita=100.0, lucro=10.0, pl=0.0, ativo=50.0),
        _reg(date(2024, 9, 30), "ITR", receita=70.0, lucro=7.0, pl=0.0),
        _reg(date(2025, 9, 30), "ITR", receita=80.0, lucro=8.0, pl=0.0, ativo=50.0),
    ]
    mapa = _por_indicador(calcular_indicadores_ticker("PETR4", registros))
    assert mapa["roe"]["semantica"] == AUSENTE
    assert mapa["roe"]["valor"] is None
    assert "zero" in mapa["roe"]["observacao"].lower()


def test_cagr_5a_bbas3_usa_dfp():
    registros = [
        _reg(date(2019, 12, 31), "DFP", receita=100.0, lucro=50.0),
        _reg(date(2020, 12, 31), "DFP", receita=110.0, lucro=55.0),
        _reg(date(2021, 12, 31), "DFP", receita=120.0, lucro=60.0),
        _reg(date(2022, 12, 31), "DFP", receita=130.0, lucro=65.0),
        _reg(date(2023, 12, 31), "DFP", receita=140.0, lucro=70.0),
        _reg(date(2024, 12, 31), "DFP", receita=161.051, lucro=80.526, pl=50.0, ativo=200.0),
    ]
    resultado = cagr_receita_5a(registros, "BBAS3", date(2024, 12, 31))
    esperado = calcular_cagr([100.0, 161.051], anos=5)
    assert abs(resultado["valor"] - esperado) < 1e-9
    assert abs(resultado["valor"] - 0.10) < 1e-4
    assert resultado["fonte_primaria"] == "CVM/DFP"
    assert "CVM" in (resultado["observacao"] or "")
    lucro = cagr_lucro_5a(registros, "BBAS3", date(2024, 12, 31))
    esperado_lucro = calcular_cagr([50.0, 80.526], anos=5)
    assert abs(lucro["valor"] - esperado_lucro) < 1e-9
    assert lucro["indicador"] == "cagr_lucro_5a"
    assert lucro["fonte_primaria"] == "CVM/DFP"
    assert lucro["valor"] is not None
    assert lucro["valor"] != 0


def test_cagr_empresa_nova_ausente():
    registros = [_reg(date(2024, 12, 31), "DFP", receita=50.0, pl=10.0, ativo=20.0)]
    resultado = cagr_receita_5a(registros, "ASAI3", date(2024, 12, 31))
    assert resultado["semantica"] == AUSENTE
    assert resultado["valor"] is None
    assert "NAO CALCULAVEL" in resultado["observacao"]


def test_banco_marca_nao_aplicavel():
    assert natureza_financeira("BBAS3") == "BANCO"
    assert indicador_aplicavel_setor("BBAS3", "ebitda_ltm") is False
    assert indicador_aplicavel_setor("BBAS3", "roe") is True
    registros = [
        _reg(date(2024, 12, 31), "DFP", receita=100.0, lucro=20.0, ebit=30.0,
             ebitda=40.0, pl=50.0, ativo=200.0, divida_liquida=10.0),
    ]
    mapa = _por_indicador(calcular_indicadores_ticker("BBAS3", registros))
    assert mapa["ebitda_ltm"]["semantica"] == NAO_APLICAVEL
    assert mapa["ebitda_ltm"]["valor"] is None
    assert mapa["marg_bruta"]["semantica"] == NAO_APLICAVEL
    assert mapa["div_liq_ebit"]["semantica"] == NAO_APLICAVEL
    assert mapa["roe"]["valor"] == 0.4


def test_seguradora_nao_aplicavel():
    assert natureza_financeira("BBSE3") == "SEGURADORA"
    assert indicador_aplicavel_setor("BBSE3", "roic") is False


def test_zero_real_preservado_em_indicador():
    registros = [
        _reg(date(2024, 12, 31), "DFP", receita=100.0, lucro=0.0, pl=50.0, ativo=200.0),
    ]
    mapa = _por_indicador(calcular_indicadores_ticker("PETR4", registros))
    assert mapa["lucro_liquido_ltm"]["semantica"] == ZERO
    assert mapa["lucro_liquido_ltm"]["valor"] == 0.0
    assert mapa["marg_liquida"]["semantica"] == ZERO


def test_benchmark_nunca_sobrescreve_cvm():
    divergencia = comparar_benchmark_externo(0.10, 0.50)
    assert divergencia["regra"] == "DIVERGENCIA_BENCHMARK"
    assert divergencia["valor_cvm"] == 0.10
    assert comparar_benchmark_externo(0.10, 0.11) is None


def test_coerencia_dfp_itr_warning():
    achados = regra_coerencia_dfp_itr(
        {"receita": 80.0, "lucro_liquido": 10.0},
        {"receita": 100.0, "lucro_liquido": 10.0},
    )
    assert any(a.regra == "INCOERENCIA_DFP_ITR" and a.severidade == WARNING for a in achados)


def test_persistencia_indicadores_nao_toca_snapshot():
    session, engine = _sessao()
    registrar_no_catalogo(session, "PETR4", TipoAtivo.ACAO, cnpj="33.000.167/0001-01")
    ativo = garantir_ativo(session, "PETR4", TipoAtivo.ACAO, cnpj="33.000.167/0001-01")
    session.add(DadosFinanceirosAcoes(
        ativo_id=ativo.id,
        data_referencia=date(2024, 12, 31),
        tipo_doc="DFP",
        receita=100.0,
        lucro_liquido=20.0,
        patrimonio_liquido=50.0,
        ativo_total=200.0,
        dt_ini_exerc=date(2024, 1, 1),
    ))
    session.commit()
    gravados = persistir_indicadores_cvm(session, ["PETR4"])
    assert gravados > 0
    assert session.query(IndicadorCvmAcao).count() > 0
    nomes = {c["name"] for c in inspect(engine).get_columns("snapshots_acoes")}
    assert "preco" in nomes
    session.close()


def test_garantir_colunas_cvm_acoes_idempotente():
    _, engine = _sessao()
    assert garantir_colunas_cvm_acoes(engine) == 0
    nomes = {c["name"] for c in inspect(engine).get_columns("dados_financeiros_acoes")}
    assert "ebit" in nomes
    assert "ativo_circulante" in nomes
    assert "versao" in nomes
