"""Etapa 8.9: CAGR CVM no fluxo de producao (BD_Acoes Z/AA) sem pipeline paralelo."""
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modules.scraper_acoes import montar_linha_acao, priorizar_cagr_cvm
from pipeline_dados.banco_dados import (
    Base,
    DadosFinanceirosAcoes,
    IndicadorCvmAcao,
    TipoAtivo,
)
from pipeline_dados.catalogo_ativos import garantir_ativo, registrar_no_catalogo
from pipeline_dados.coletor_cvm import AcoesCVMReader
from pipeline_dados.indicadores_cvm_acoes import (
    calcular_cagr,
    calcular_indicadores_ticker,
    cagr_lucro_5a,
    cagr_receita_5a,
    mapa_cagr_cvm_producao,
    persistir_indicadores_cvm,
)
from pipeline_dados.semantica_indicadores import AUSENTE, PRESENTE
from tests.test_indicadores_cvm_acoes import _por_indicador, _reg


def _sessao():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)(), engine


def _dfp_completo(ticker="BBAS3"):
    return [
        _reg(date(2019, 12, 31), "DFP", receita=100.0, lucro=50.0),
        _reg(date(2020, 12, 31), "DFP", receita=110.0, lucro=55.0),
        _reg(date(2021, 12, 31), "DFP", receita=120.0, lucro=60.0),
        _reg(date(2022, 12, 31), "DFP", receita=130.0, lucro=65.0),
        _reg(date(2023, 12, 31), "DFP", receita=140.0, lucro=70.0),
        _reg(date(2024, 12, 31), "DFP", receita=161.051, lucro=80.526, pl=50.0, ativo=200.0),
    ]


def test_priorizar_cagr_cvm_valido_vence_fundamentus():
    assert priorizar_cagr_cvm(0.12, 0.08) == 0.12
    assert priorizar_cagr_cvm(0.0, 0.08) == 0.0


def test_priorizar_cagr_cvm_ausente_cai_no_fundamentus():
    assert priorizar_cagr_cvm(None, 0.08) == 0.08
    assert priorizar_cagr_cvm("", 0.08) == 0.08
    assert priorizar_cagr_cvm("abc", 0.08) == 0.08
    assert priorizar_cagr_cvm(None, None) is None


def test_cagr_receita_cvm_bbas3_prioridade_na_coluna_z():
    registros = _dfp_completo()
    cvm = cagr_receita_5a(registros, "BBAS3", date(2024, 12, 31))
    fundamentus = 0.03
    escolhido = priorizar_cagr_cvm(cvm["valor"], fundamentus)
    assert abs(escolhido - 0.10) < 1e-4
    linha = montar_linha_acao(
        "Financeiro", 28.0, 0.08, 1.0, 6.0, 0.9, None, None, None, None,
        None, None, None, None, None, None, None, None, 0.18, None, None,
        escolhido, None, None, None, None, None, "10/09 10:00",
        cagr_lucro_5a=None,
    )
    assert abs(linha[24] - 0.10) < 1e-4
    assert linha[24] != fundamentus


def test_cagr_receita_cvm_ausente_preserva_fundamentus():
    registros = [_reg(date(2024, 12, 31), "DFP", receita=50.0, lucro=10.0)]
    cvm = cagr_receita_5a(registros, "BBAS3", date(2024, 12, 31))
    assert cvm["semantica"] == AUSENTE
    assert cvm["valor"] is None
    fundamentus = 0.07
    escolhido = priorizar_cagr_cvm(cvm["valor"], fundamentus)
    linha = montar_linha_acao(
        "Financeiro", 28.0, None, None, None, None, None, None, None, None,
        None, None, None, None, None, None, None, None, None, None, None,
        escolhido, None, None, None, None, None, "10/09 10:00",
    )
    assert linha[24] == 0.07


def test_cagr_lucro_cvm_valido_vai_para_coluna_aa():
    registros = _dfp_completo()
    lucro = cagr_lucro_5a(registros, "BBAS3", date(2024, 12, 31))
    esperado = calcular_cagr([50.0, 80.526], anos=5)
    assert lucro["semantica"] == PRESENTE
    assert abs(lucro["valor"] - esperado) < 1e-9
    linha = montar_linha_acao(
        "Financeiro", 28.0, None, None, None, None, None, None, None, None,
        None, None, None, None, None, None, None, None, None, None, None,
        0.10, None, None, None, None, None, "10/09 10:00",
        cagr_lucro_5a=lucro["valor"],
    )
    assert linha[25] == lucro["valor"]
    assert linha[25] != 0
    assert linha[25] != ""


def test_cagr_lucro_exige_extremos_positivos():
    registros = [
        _reg(date(2019, 12, 31), "DFP", lucro=50.0),
        _reg(date(2024, 12, 31), "DFP", lucro=80.0, pl=10.0, ativo=20.0),
    ]
    ok = cagr_lucro_5a(registros, "BBAS3", date(2024, 12, 31))
    assert ok["semantica"] == PRESENTE
    assert ok["valor"] > 0


def test_cagr_lucro_zero_nao_calculavel_nunca_zero():
    for lucro_ini, lucro_fim in ((0.0, 80.0), (50.0, 0.0), (0.0, 0.0)):
        registros = [
            _reg(date(2019, 12, 31), "DFP", lucro=lucro_ini),
            _reg(date(2024, 12, 31), "DFP", lucro=lucro_fim, pl=10.0, ativo=20.0),
        ]
        resultado = cagr_lucro_5a(registros, "BBAS3", date(2024, 12, 31))
        assert resultado["semantica"] == AUSENTE, (lucro_ini, lucro_fim)
        assert resultado["valor"] is None
        assert "NAO CALCULAVEL" in resultado["observacao"]
        linha = montar_linha_acao(
            "Financeiro", 28.0, None, None, None, None, None, None, None, None,
            None, None, None, None, None, None, None, None, None, None, None,
            None, None, None, None, None, None, "10/09 10:00",
            cagr_lucro_5a=resultado["valor"],
        )
        assert linha[25] == ""
        assert linha[25] != 0


def test_cagr_lucro_negativo_nao_calculavel_nunca_zero():
    for lucro_ini, lucro_fim in ((-10.0, 80.0), (50.0, -5.0), (-10.0, -5.0)):
        registros = [
            _reg(date(2019, 12, 31), "DFP", lucro=lucro_ini),
            _reg(date(2024, 12, 31), "DFP", lucro=lucro_fim, pl=10.0, ativo=20.0),
        ]
        resultado = cagr_lucro_5a(registros, "BBAS3", date(2024, 12, 31))
        assert resultado["semantica"] == AUSENTE, (lucro_ini, lucro_fim)
        assert resultado["valor"] is None
        assert "NAO CALCULAVEL" in resultado["observacao"]


def test_cagr_historico_insuficiente_nao_calculavel():
    registros = [_reg(date(2024, 12, 31), "DFP", receita=50.0, lucro=10.0, pl=10.0, ativo=20.0)]
    rec = cagr_receita_5a(registros, "BBAS3", date(2024, 12, 31))
    luc = cagr_lucro_5a(registros, "BBAS3", date(2024, 12, 31))
    assert rec["semantica"] == AUSENTE
    assert luc["semantica"] == AUSENTE
    assert rec["valor"] is None
    assert luc["valor"] is None
    assert "NAO CALCULAVEL" in rec["observacao"]
    assert "NAO CALCULAVEL" in luc["observacao"]
    mapa = _por_indicador(calcular_indicadores_ticker("BBAS3", registros))
    assert mapa["cagr_rec_5a"]["valor"] is None
    assert mapa["cagr_lucro_5a"]["valor"] is None


def test_persistir_cagr_lucro_em_indicadores_cvm_acoes():
    session, _ = _sessao()
    registrar_no_catalogo(session, "BBAS3", TipoAtivo.ACAO, cnpj="00.000.000/0001-91")
    ativo = garantir_ativo(session, "BBAS3", TipoAtivo.ACAO, cnpj="00.000.000/0001-91")
    for reg in _dfp_completo():
        session.add(DadosFinanceirosAcoes(
            ativo_id=ativo.id,
            data_referencia=reg.data_referencia,
            tipo_doc=reg.tipo_doc,
            receita=reg.receita,
            lucro_liquido=reg.lucro_liquido,
            patrimonio_liquido=reg.patrimonio_liquido,
            ativo_total=reg.ativo_total,
            dt_ini_exerc=reg.dt_ini_exerc,
        ))
    session.commit()
    gravados = persistir_indicadores_cvm(session, ["BBAS3"])
    assert gravados > 0
    rec = (
        session.query(IndicadorCvmAcao)
        .filter_by(ticker="BBAS3", indicador="cagr_rec_5a")
        .one()
    )
    luc = (
        session.query(IndicadorCvmAcao)
        .filter_by(ticker="BBAS3", indicador="cagr_lucro_5a")
        .one()
    )
    assert rec.semantica == PRESENTE
    assert luc.semantica == PRESENTE
    assert abs(rec.valor - 0.10) < 1e-4
    assert luc.valor is not None
    assert luc.valor != 0
    mapa = mapa_cagr_cvm_producao(session, ["BBAS3"])
    assert abs(mapa["BBAS3"]["cagr_rec_5a"] - 0.10) < 1e-4
    assert mapa["BBAS3"]["cagr_lucro_5a"] == luc.valor
    session.close()


def test_mapa_producao_omite_cagr_ausente():
    session, _ = _sessao()
    registrar_no_catalogo(session, "BBAS3", TipoAtivo.ACAO, cnpj="00.000.000/0001-91")
    ativo = garantir_ativo(session, "BBAS3", TipoAtivo.ACAO, cnpj="00.000.000/0001-91")
    session.add(DadosFinanceirosAcoes(
        ativo_id=ativo.id,
        data_referencia=date(2024, 12, 31),
        tipo_doc="DFP",
        receita=50.0,
        lucro_liquido=10.0,
        patrimonio_liquido=20.0,
        ativo_total=40.0,
        dt_ini_exerc=date(2024, 1, 1),
    ))
    session.commit()
    persistir_indicadores_cvm(session, ["BBAS3"])
    mapa = mapa_cagr_cvm_producao(session, ["BBAS3"])
    assert "cagr_rec_5a" not in mapa.get("BBAS3", {})
    assert "cagr_lucro_5a" not in mapa.get("BBAS3", {})
    session.close()


def test_dfp_t_menos_5_ja_persistido_nao_baixa_de_novo(monkeypatch):
    session, _ = _sessao()
    registrar_no_catalogo(session, "BBAS3", TipoAtivo.ACAO, cnpj="00.000.000/0001-91")
    ativo = garantir_ativo(session, "BBAS3", TipoAtivo.ACAO, cnpj="00.000.000/0001-91")
    session.add(DadosFinanceirosAcoes(
        ativo_id=ativo.id,
        data_referencia=date(2020, 12, 31),
        tipo_doc="DFP",
        receita=100.0,
        lucro_liquido=40.0,
        dt_ini_exerc=date(2020, 1, 1),
    ))
    session.commit()
    leitor = AcoesCVMReader(session)
    leitor.meus_tickers = ["BBAS3"]
    leitor.cnpjs_alvo = {"00000000000191"}
    chamadas = []

    def fake_atualizar(ano, tipo_doc, url_template, prefixo):
        chamadas.append((ano, tipo_doc, prefixo))

    monkeypatch.setattr(leitor, "_atualizar_documento", fake_atualizar)
    monkeypatch.setattr(leitor, "_persistir_indicadores_calculados", lambda: None)
    leitor.atualizar_acoes(2025)
    assert chamadas == [(2025, "ITR", "itr"), (2025, "DFP", "dfp")]
    session.close()


def test_ano_dfp_cagr_nao_usa_ano_corrente_cego():
    from pipeline_dados.coletor_cvm import ano_dfp_cagr_producao

    hoje = date(2026, 9, 12)
    assert ano_dfp_cagr_producao(hoje=hoje, verificar=lambda ano: ano == 2025) == 2025
    assert ano_dfp_cagr_producao(hoje=hoje, verificar=lambda ano: ano == 2026) == 2026
    assert ano_dfp_cagr_producao(hoje=hoje, verificar=lambda ano: False) is None


def test_coletar_cvm_acoes_producao_usa_ultimo_dfp_anual(monkeypatch):
    from pipeline_dados import coletor_cvm as modulo_cvm

    chamadas = []

    class _LeitorFake:
        def __init__(self, session):
            self.session = session

        def atualizar_acoes(self, ano):
            chamadas.append(ano)

    monkeypatch.setattr(modulo_cvm, "AcoesCVMReader", _LeitorFake)
    session, _ = _sessao()
    ano = modulo_cvm.coletar_cvm_acoes_producao(
        session, hoje=date(2026, 9, 12), verificar_dfp=lambda a: a == 2025,
    )
    assert ano == 2025
    assert chamadas == [2025]
    session.close()


def test_app_chama_cvm_antes_do_garimpo(monkeypatch):
    import app as app_module
    import config

    eventos = []

    class _Aba:
        def batch_update(self, updates):
            eventos.append("update")

        def get_all_values(self):
            return [["h"]]

    class _Planilha:
        def __init__(self):
            self.aba_fiis = _Aba()
            self.aba_acoes = _Aba()

        def worksheet(self, nome):
            return self.aba_fiis if nome == "BD_FIIs" else self.aba_acoes

    class _Gc:
        def open_by_url(self, url):
            return planilha

    planilha = _Planilha()
    monkeypatch.setattr(app_module, "conectar_gspread", lambda: _Gc())
    monkeypatch.setattr(
        app_module, "rodar_garimpo_fiis",
        lambda *a, **k: ([["A1"]], "", planilha.aba_fiis),
    )
    monkeypatch.setattr(
        app_module, "coletar_cvm_acoes_producao",
        lambda: eventos.append("cvm") or 2025,
    )
    monkeypatch.setattr(
        app_module, "rodar_garimpo_acoes",
        lambda *a, **k: (eventos.append("garimpo") or [["A1"]], "", planilha.aba_acoes),
    )
    monkeypatch.setattr(app_module, "disparar_alertas", lambda msg: None)
    monkeypatch.setattr(config, "ESPELHAMENTO_PG_ATIVO", False)

    app_module.executar_auditoria_carteira()
    assert eventos.index("cvm") < eventos.index("garimpo")


def test_bbas3_dfp_2020_2025_cvm_vence_fundamentus():
    registros = [
        _reg(date(2020, 12, 31), "DFP", receita=98659704.0, lucro=13292883.0),
        _reg(date(2025, 12, 31), "DFP", receita=319462104.0, lucro=16781938.0, pl=1.0, ativo=1.0),
    ]
    rec = cagr_receita_5a(registros, "BBAS3", date(2025, 12, 31))
    luc = cagr_lucro_5a(registros, "BBAS3", date(2025, 12, 31))
    assert abs(rec["valor"] - 0.26489917) < 1e-6
    assert abs(luc["valor"] - 0.04771844) < 1e-6
    fundamentus = -0.0961
    z = priorizar_cagr_cvm(rec["valor"], fundamentus)
    assert abs(z - 0.26489917) < 1e-6
    assert z != fundamentus
    linha = montar_linha_acao(
        "Financeiro", 28.0, None, None, None, None, None, None, None, None,
        None, None, None, None, None, None, None, None, None, None, None,
        z, None, None, None, None, None, "10/09 10:00",
        cagr_lucro_5a=luc["valor"],
    )
    assert abs(linha[24] - 0.26489917) < 1e-6
    assert abs(linha[25] - 0.04771844) < 1e-6


def test_sem_cvm_valido_fundamentus_permanece_em_z():
    z = priorizar_cagr_cvm(None, -0.0961)
    assert z == -0.0961
    linha = montar_linha_acao(
        "Financeiro", 28.0, None, None, None, None, None, None, None, None,
        None, None, None, None, None, None, None, None, None, None, None,
        z, None, None, None, None, None, "10/09 10:00",
        cagr_lucro_5a=None,
    )
    assert linha[24] == -0.0961
    assert linha[25] == ""
