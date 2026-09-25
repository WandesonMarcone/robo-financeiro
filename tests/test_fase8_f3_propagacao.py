"""PARTE F.3: NAO_APLICAVEL permanece nas camadas de dados.

Nao altera formulas. Nao cria matriz nova. Nao converte NAO_APLICAVEL
em 0, AUSENTE ou PRESENTE.
"""
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.serializadores import serializar_dados_financeiros_acoes, serializar_snapshot_acao
from modules.scraper_acoes import montar_linha_acao
from pipeline_dados.banco_dados import (
    Ativo,
    Base,
    DadosFinanceirosAcoes,
    IndicadorCvmAcao,
    SnapshotAcao,
    TipoAtivo,
)
from pipeline_dados.catalogo_ativos import garantir_ativo, registrar_no_catalogo
from pipeline_dados.espelhamento_mercado_5c import gravar_snapshot_acao
from pipeline_dados.indicadores_cvm_acoes import (
    calcular_indicadores_ticker,
    persistir_indicadores_cvm,
    resultado_ausente,
    resultado_invalido,
    resultado_nao_aplicavel,
    resultado_nao_calculavel,
)
from pipeline_dados.matriz_aplicabilidade import blank_se_nao_aplicavel, consultar_aplicabilidade
from pipeline_dados.semantica_indicadores import (
    AUSENTE,
    INVALIDO,
    NAO_APLICAVEL,
    NAO_CALCULAVEL,
    PRESENTE,
    ZERO,
    classificar_semantica,
    interpretar_valor,
)
from services.mercado import interpretar_indicador
from tests.test_indicadores_cvm_acoes import _por_indicador, _reg


def _sessao():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)(), engine


BANCO_NA = (
    "ebitda_ltm", "marg_ebit", "p_ebit", "ev_ebit", "div_liq_ebit",
    "roic", "liq_corrente",
)


def test_nao_aplicavel_nunca_vira_zero():
    assert blank_se_nao_aplicavel("ebitda", 40.0, ticker="BBAS3") is None
    assert blank_se_nao_aplicavel("ebitda", 40.0, ticker="BBAS3") != 0
    assert blank_se_nao_aplicavel("marg_ebit", 0.3, ticker="ITUB4") is None
    assert blank_se_nao_aplicavel("p_ebit", 8.0, ticker="BBAS3") != 0
    interpretacao = interpretar_valor("ACAO", "marg_ebit", 0.30, ticker="BBAS3")
    assert interpretacao["semantica"] == NAO_APLICAVEL
    assert interpretacao["valor_numerico"] is None
    assert interpretacao["valor_numerico"] != 0


def test_presente_continua_numerico():
    assert blank_se_nao_aplicavel("pl", 6.5, ticker="BBAS3") == 6.5
    assert blank_se_nao_aplicavel("roe", 0.18, ticker="BBAS3") == 0.18
    assert blank_se_nao_aplicavel("ebitda", 40.0, ticker="PETR4") == 40.0
    interpretacao = interpretar_valor("ACAO", "pl", 6.5, ticker="BBAS3")
    assert interpretacao["semantica"] == PRESENTE
    assert interpretacao["valor_numerico"] == 6.5


def test_zero_continua_zero():
    assert blank_se_nao_aplicavel("roe", 0.0, ticker="BBAS3") == 0.0
    assert blank_se_nao_aplicavel("pl", 0, ticker="PETR4") == 0
    assert classificar_semantica(0) == ZERO
    interpretacao = interpretar_valor("ACAO", "roe", 0.0, ticker="BBAS3")
    assert interpretacao["semantica"] == ZERO
    assert interpretacao["valor_numerico"] == 0.0


def test_ausente_preservado():
    interpretacao = interpretar_valor("ACAO", "roe", None, ticker="PETR4")
    assert interpretacao["semantica"] == AUSENTE
    assert interpretacao["valor_numerico"] is None
    item = resultado_ausente("roe", "PETR4", date(2024, 12, 31), "LTM", "faltou")
    assert item["semantica"] == AUSENTE
    assert item["valor"] is None
    assert item["valor"] != 0


def test_nao_calculavel_preservado():
    item = resultado_nao_calculavel(
        "peg_ratio", "PETR4", date(2024, 12, 31), "PEG", "divisor zero",
    )
    assert item["semantica"] == NAO_CALCULAVEL
    assert item["valor"] is None
    assert item["valor"] != 0


def test_invalido_preservado():
    interpretacao = interpretar_valor("ACAO", "pl", "abc", ticker="PETR4")
    assert interpretacao["semantica"] == INVALIDO
    assert interpretacao["valor_numerico"] is None
    item = resultado_invalido("pl", "PETR4", date(2024, 12, 31), "LTM", "ilegivel")
    assert item["semantica"] == INVALIDO
    assert item["valor"] is None


def test_banco_ebitda_nao_aplicavel_nas_camadas():
    item = resultado_nao_aplicavel("ebitda_ltm", "BBAS3", date(2024, 12, 31), "LTM")
    assert item["semantica"] == NAO_APLICAVEL
    assert item["valor"] is None
    assert item["status"] == NAO_APLICAVEL
    linha = montar_linha_acao(
        "Financeiro", 28.0, 0.08, 1.0, 6.0, 0.9, 0.5, 0.4, 0.3, 0.2,
        8.0, 7.0, 1.2, 0.8, 1.1, 1.0, 0.9, 1.5, 0.18, 0.08, 0.12,
        0.10, 1000.0, 20.0, 4.0, 1.1, 100.0, "10/09 10:00",
        ticker="BBAS3",
    )
    assert linha[7] == 0.4
    assert linha[8] == ""
    assert linha[10] == ""
    assert linha[11] == ""
    assert linha[12] == ""
    assert 0 not in (linha[8], linha[10], linha[11], linha[12])
    api = interpretar_indicador("ACAO", "marg_ebit", None, ticker="BBAS3")
    assert api["semantica"] == NAO_APLICAVEL
    assert api["aplicavel"] is False
    assert api["valor_numerico"] is None


def test_banco_pl_pvp_roe_roa_numericos():
    linha = montar_linha_acao(
        "Financeiro", 28.0, 0.08, 1.0, 6.0, 0.9, 0.5, 0.4, 0.3, 0.2,
        8.0, 7.0, 1.2, 0.8, 1.1, 1.0, 0.9, 1.5, 0.18, 0.08, 0.12,
        0.10, 1000.0, 20.0, 4.0, 1.1, 100.0, "10/09 10:00",
        ticker="BBAS3",
    )
    assert linha[4] == 6.0
    assert linha[5] == 0.9
    assert linha[18] == 0.18
    assert linha[19] == 0.08
    mapa = _por_indicador(calcular_indicadores_ticker("BBAS3", [
        _reg(date(2024, 12, 31), "DFP", receita=100.0, lucro=20.0, ebit=30.0,
             ebitda=40.0, pl=50.0, ativo=200.0),
    ]))
    assert mapa["roe"]["valor"] == 0.4
    assert mapa["roa"]["valor"] == 0.1
    assert mapa["pl"]["semantica"] != NAO_APLICAVEL
    assert mapa["pvp"]["semantica"] != NAO_APLICAVEL


def test_industrial_ebitda_continua_calculavel():
    mapa = _por_indicador(calcular_indicadores_ticker("PETR4", [
        _reg(date(2024, 12, 31), "DFP", receita=100.0, lucro=20.0, ebit=30.0,
             ebitda=40.0, pl=50.0, ativo=200.0, lucro_bruto=50.0),
    ]))
    assert mapa["ebitda_ltm"]["valor"] == 40.0
    assert mapa["ebitda_ltm"]["semantica"] != NAO_APLICAVEL
    linha = montar_linha_acao(
        "Petroleo", 37.0, 0.14, 1.0, 4.5, 1.2, 0.8, 0.55, 0.30, 0.12,
        8.0, 5.0, None, 0.8, 0.9, 1.2, 1.1, 1.5, 0.18, 0.12, 0.16,
        0.10, 850.0, 31.0, 8.3, 1.1, 400.0, "10/09 10:00",
        ticker="PETR4",
    )
    assert linha[8] == 0.30
    assert linha[10] == 8.0
    assert blank_se_nao_aplicavel("ebitda", 40.0, ticker="PETR4") == 40.0


def test_sem_classificacao_nao_vira_nao_aplicavel():
    assert consultar_aplicabilidade("ebitda", ticker="EMBR3") != NAO_APLICAVEL
    assert blank_se_nao_aplicavel("ebitda", 40.0, ticker="EMBR3") == 40.0
    interpretacao = interpretar_valor("ACAO", "ebitda", None, ticker="EMBR3")
    assert interpretacao["semantica"] != NAO_APLICAVEL
    mapa = _por_indicador(calcular_indicadores_ticker("EMBR3", [
        _reg(date(2024, 12, 31), "DFP", receita=100.0, lucro=20.0, ebitda=40.0,
             pl=50.0, ativo=200.0),
    ]))
    assert mapa["ebitda_ltm"]["semantica"] != NAO_APLICAVEL
    assert mapa["ebitda_ltm"]["valor"] == 40.0


def test_sheets_nao_escreve_zero_para_nao_aplicavel():
    linha = montar_linha_acao(
        "Financeiro", 28.0, None, None, 6.0, 0.9, None, 0.0, 0.25, None,
        0, 0.0, 1.5, None, None, 2.0, 3.0, 1.1, 0.18, 0.08, 0.10,
        None, None, None, None, None, None, "10/09 10:00",
        ticker="BBAS3",
    )
    assert linha[7] == 0.0
    assert linha[8] == ""
    assert linha[10] == ""
    assert linha[11] == ""
    assert linha[15] == ""
    assert linha[16] == ""
    assert linha[17] == ""
    assert linha[20] == ""
    for indice in (8, 10, 11, 15, 16, 17, 20):
        assert linha[indice] != 0
        assert linha[indice] != 0.0
    assert linha[4] == 6.0
    assert linha[18] == 0.18


def test_snapshot_persiste_none_para_nao_aplicavel():
    session, _ = _sessao()
    registrar_no_catalogo(session, "BBAS3", TipoAtivo.ACAO, cnpj="00.000.000/0001-91")
    ativo = garantir_ativo(session, "BBAS3", TipoAtivo.ACAO, cnpj="00.000.000/0001-91")
    dados = {
        "ticker": "BBAS3",
        "preco": 28.0,
        "pl": 6.0,
        "pvp": 0.9,
        "roe": 0.18,
        "roa": 0.08,
        "marg_ebit": 0.30,
        "p_ebit": 8.0,
        "ev_ebit": 7.0,
        "roic": 0.12,
        "liq_corrente": 1.5,
        "p_cap_giro": 1.0,
        "p_at_circ_liq": 0.9,
        "dy": 0.05,
    }
    snap, _, status = gravar_snapshot_acao(session, ativo, dados, date(2026, 8, 20))
    session.commit()
    assert status in ("CRIADO", "ATUALIZADO")
    assert snap.marg_ebit is None
    assert snap.p_ebit is None
    assert snap.ev_ebit is None
    assert snap.roic is None
    assert snap.liq_corrente is None
    assert snap.p_cap_giro is None
    assert snap.p_at_circ_liq is None
    assert snap.pl == Decimal("6.0")
    assert snap.pvp == Decimal("0.9")
    assert snap.roe == Decimal("0.18")
    assert snap.roa == Decimal("0.08")
    assert snap.preco == Decimal("28.0")
    session.close()


def test_cvm_persiste_semantica_nao_aplicavel():
    session, _ = _sessao()
    registrar_no_catalogo(session, "BBAS3", TipoAtivo.ACAO, cnpj="00.000.000/0001-91")
    ativo = garantir_ativo(session, "BBAS3", TipoAtivo.ACAO, cnpj="00.000.000/0001-91")
    session.add(DadosFinanceirosAcoes(
        ativo_id=ativo.id,
        data_referencia=date(2024, 12, 31),
        tipo_doc="DFP",
        receita=100.0,
        lucro_liquido=20.0,
        ebit=30.0,
        ebitda=40.0,
        patrimonio_liquido=50.0,
        ativo_total=200.0,
        dt_ini_exerc=date(2024, 1, 1),
    ))
    session.commit()
    persistir_indicadores_cvm(session, ["BBAS3"])
    for indicador in BANCO_NA:
        linha = (
            session.query(IndicadorCvmAcao)
            .filter_by(ticker="BBAS3", indicador=indicador)
            .one()
        )
        assert linha.semantica == NAO_APLICAVEL, indicador
        assert linha.valor is None, indicador
        assert linha.status == NAO_APLICAVEL, indicador
        assert linha.valor != 0
    roe = session.query(IndicadorCvmAcao).filter_by(ticker="BBAS3", indicador="roe").one()
    assert roe.semantica == PRESENTE
    assert roe.valor == 0.4
    session.close()


def test_api_snapshot_preserva_nao_aplicavel():
    snap = SimpleNamespace(
        id=1,
        ativo_id=1,
        ativo=SimpleNamespace(ticker="BBAS3"),
        data_referencia=date(2026, 8, 20),
        data_coleta=datetime(2026, 8, 20, 10, 0, 0),
        data_publicacao=None,
        fonte="teste",
        fonte_primaria=None,
        fonte_intermediaria=None,
        url_origem=None,
        preco=Decimal("28.0"),
        dy=Decimal("0.05"),
        pvp=Decimal("0.9"),
        vpa=Decimal("20.0"),
        pl=Decimal("6.0"),
        p_ativo=Decimal("0.5"),
        marg_bruta=None,
        marg_ebit=None,
        marg_liquida=Decimal("0.2"),
        p_ebit=None,
        ev_ebit=None,
        div_liq_ebit=None,
        div_liq_patrimonio=Decimal("0.8"),
        psr=Decimal("1.1"),
        p_cap_giro=None,
        p_at_circ_liq=None,
        liq_corrente=None,
        roe=Decimal("0.18"),
        roa=Decimal("0.08"),
        roic=None,
        cagr_rec_5a=Decimal("0.10"),
        liq_media=None,
        lpa=Decimal("4.0"),
        peg_ratio=Decimal("1.1"),
        valor_mercado=Decimal("100.0"),
    )
    payload = serializar_snapshot_acao(snap)
    assert payload["marg_ebit"] is None
    assert payload["p_ebit"] is None
    assert payload["ev_ebit"] is None
    assert payload["roic"] is None
    assert payload["campos"]["marg_ebit"]["semantica"] == NAO_APLICAVEL
    assert payload["campos"]["p_ebit"]["semantica"] == NAO_APLICAVEL
    assert payload["campos"]["ev_ebit"]["semantica"] == NAO_APLICAVEL
    assert payload["campos"]["roic"]["aplicavel"] is False
    assert payload["campos"]["pl"]["semantica"] == PRESENTE
    assert payload["campos"]["roe"]["semantica"] == PRESENTE
    assert payload["pl"] == 6.0
    assert payload["roe"] == 0.18
    assert payload["marg_ebit"] != 0


def test_api_dados_cvm_banco_ebitda_nao_aplicavel():
    registro = SimpleNamespace(
        id=1,
        ativo_id=1,
        ativo=SimpleNamespace(ticker="BBAS3"),
        data_referencia=date(2024, 12, 31),
        data_coleta=None,
        fonte="CVM",
        fonte_primaria=None,
        url_origem=None,
        tipo_doc="DFP",
        ativo_total=200.0,
        patrimonio_liquido=50.0,
        caixa=5.0,
        passivo_total=150.0,
        divida_bruta=15.0,
        divida_curto_prazo=None,
        divida_longo_prazo=None,
        divida_liquida=10.0,
        receita=100.0,
        lucro_bruto=50.0,
        ebitda=40.0,
        ebit=30.0,
        depreciacao=10.0,
        ativo_circulante=80.0,
        passivo_circulante=40.0,
        resultado_financeiro=None,
        lucro_liquido=20.0,
        fco=12.0,
    )
    payload = serializar_dados_financeiros_acoes(registro)
    assert payload["ebitda"] == 40.0
    assert payload["campos"]["ebitda"]["semantica"] == NAO_APLICAVEL
    assert payload["campos"]["ebitda"]["aplicavel"] is False
    assert payload["campos"]["ebitda"]["semantica"] != ZERO
    assert payload["lucro_liquido"] == 20.0
    assert payload["campos"]["lucro_liquido"]["semantica"] == PRESENTE


def test_api_industrial_ebitda_presente():
    registro = SimpleNamespace(
        id=1,
        ativo_id=1,
        ativo=SimpleNamespace(ticker="PETR4"),
        data_referencia=date(2024, 12, 31),
        data_coleta=None,
        fonte="CVM",
        fonte_primaria=None,
        url_origem=None,
        tipo_doc="DFP",
        ativo_total=200.0,
        patrimonio_liquido=50.0,
        caixa=5.0,
        passivo_total=150.0,
        divida_bruta=15.0,
        divida_curto_prazo=None,
        divida_longo_prazo=None,
        divida_liquida=10.0,
        receita=100.0,
        lucro_bruto=50.0,
        ebitda=40.0,
        ebit=30.0,
        depreciacao=10.0,
        ativo_circulante=80.0,
        passivo_circulante=40.0,
        resultado_financeiro=None,
        lucro_liquido=20.0,
        fco=12.0,
    )
    payload = serializar_dados_financeiros_acoes(registro)
    assert payload["ebitda"] == 40.0
    assert payload["campos"]["ebitda"]["semantica"] == PRESENTE
    assert payload["campos"]["ebitda"]["aplicavel"] is True


def test_regressao_f1_f2_matriz():
    assert consultar_aplicabilidade("ebitda", ticker="BBAS3") == NAO_APLICAVEL
    assert consultar_aplicabilidade("pl", ticker="BBAS3") != NAO_APLICAVEL
    assert consultar_aplicabilidade("ebitda", ticker="PETR4") != NAO_APLICAVEL
    assert consultar_aplicabilidade("ebitda", ticker="EMBR3") != NAO_APLICAVEL
    mapa = _por_indicador(calcular_indicadores_ticker("BBAS3", [
        _reg(date(2024, 12, 31), "DFP", receita=100.0, lucro=20.0, ebit=30.0,
             ebitda=40.0, pl=50.0, ativo=200.0, divida_liquida=10.0),
    ]))
    for indicador in BANCO_NA:
        assert mapa[indicador]["semantica"] == NAO_APLICAVEL, indicador
        assert mapa[indicador]["valor"] is None, indicador
