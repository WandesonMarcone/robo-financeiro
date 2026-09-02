"""Testes do catálogo central de ativos — Fase 7, Etapa 7.2 (aditivo).

Cobre: seed idempotente a partir de config, consulta central (por ticker/CNPJ),
resolução de CNPJ sem inventar identificadores, tipos ACAO/FII/ETF/CRIPTO e a
estratégia "catálogo PostgreSQL primeiro, Google Sheets como fallback" nos dois
consumidores adaptados (coletor_cvm e atualizador_documentos).
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import config
from pipeline_dados.banco_dados import AtivoCatalogo, Base, TipoAtivo
from pipeline_dados.catalogo_ativos import (
    consultar_por_cnpj,
    consultar_por_ticker,
    listar_tickers_catalogo,
    obter_tickers_com_fallback,
    registrar_no_catalogo,
    resolver_cnpj,
    seed_catalogo,
)
from pipeline_dados.normalizacao import normalizar_cnpj


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessao = sessionmaker(bind=engine)()
    yield sessao
    sessao.close()


@pytest.fixture()
def mapa_config_vazio(monkeypatch):
    """Esvazia os mapas de catálogo do config para simular catálogo vazio."""
    monkeypatch.setattr(config, "MAPA_CNPJ_B3", {})
    monkeypatch.setattr(config, "MAPA_ISCAS_MASTER", {})


# ==========================================
# SEED IDEMPOTENTE
# ==========================================

def test_seed_catalogo_acao_tem_cnpj_real(db_session):
    criados = seed_catalogo(db_session)
    assert criados == len(config.MAPA_CNPJ_B3) + len(config.MAPA_ISCAS_MASTER)

    petr4 = consultar_por_ticker(db_session, "PETR4")
    assert petr4 is not None
    assert petr4.tipo == "ACAO"
    assert petr4.cnpj == "33.000.167/0001-01"
    assert petr4.fonte == "config"
    assert petr4.setor is not None


def test_seed_catalogo_fii_nao_inventa_cnpj(db_session):
    seed_catalogo(db_session)
    mxrf11 = consultar_por_ticker(db_session, "MXRF11")
    assert mxrf11 is not None
    assert mxrf11.tipo == "FII"
    assert mxrf11.nome_emissor == "MAXI RENDA"
    assert mxrf11.cnpj is None


def test_seed_catalogo_idempotente(db_session):
    seed_catalogo(db_session)
    total = db_session.query(AtivoCatalogo).count()
    seed_catalogo(db_session)
    assert db_session.query(AtivoCatalogo).count() == total


def test_seed_catalogo_nao_duplica_em_segunda_chamada(db_session):
    seed_catalogo(db_session)
    segunda = seed_catalogo(db_session)
    assert segunda == 0
    assert len(listar_tickers_catalogo(db_session, "ACAO")) == len(config.MAPA_CNPJ_B3)
    assert len(listar_tickers_catalogo(db_session, "FII")) == len(config.MAPA_ISCAS_MASTER)


def test_seed_preserva_registro_manual_existente(db_session):
    registrar_no_catalogo(db_session, "XXAX11", "FII", nome_emissor="MANUAL")
    seed_catalogo(db_session)
    registro = consultar_por_ticker(db_session, "XXAX11")
    assert registro is not None
    assert registro.nome_emissor == "MANUAL"
    assert registro.fonte is None or registro.fonte != "config"


# ==========================================
# CONSULTA CENTRAL POR TICKER / CNPJ
# ==========================================

def test_consultar_por_ticker_normaliza_maiusculas(db_session):
    seed_catalogo(db_session)
    assert consultar_por_ticker(db_session, "petr4").ticker == "PETR4"
    assert consultar_por_ticker(db_session, "  vale3  ").ticker == "VALE3"
    assert consultar_por_ticker(db_session, None) is None
    assert consultar_por_ticker(db_session, "ZZZZ11") is None


def test_consultar_por_cnpj_ignora_mascara(db_session):
    seed_catalogo(db_session)
    registro = consultar_por_cnpj(db_session, "33000167000101")
    assert registro is not None
    assert registro.ticker == "PETR4"
    assert consultar_por_cnpj(db_session, "00.000.000/0001-91").ticker == "BBAS3"
    assert consultar_por_cnpj(db_session, "123") is None


# ==========================================
# RESOLUÇÃO DE CNPJ (NUNCA INVENTA IDENTIFICADOR)
# ==========================================

def test_resolver_cnpj_acao_pelo_catalogo(db_session):
    seed_catalogo(db_session)
    assert resolver_cnpj(db_session, "PETR4") == "33.000.167/0001-01"
    assert resolver_cnpj(db_session, "BBAS3") == "00.000.000/0001-91"


def test_resolver_cnpj_fii_sem_cnpj_retorna_none(db_session):
    seed_catalogo(db_session)
    assert resolver_cnpj(db_session, "MXRF11", TipoAtivo.FII) is None


def test_resolver_cnpj_ticker_desconhecido_retorna_none(db_session):
    seed_catalogo(db_session)
    assert resolver_cnpj(db_session, "ZZZZ3") is None
    assert resolver_cnpj(db_session, "ZZZZ11") is None


# ==========================================
# TIPOS ACAO / FII / ETF / CRIPTO
# ==========================================

def test_tipos_suportados_pelo_catalogo(db_session):
    assert {t.value for t in TipoAtivo} == {"ACAO", "FII", "ETF", "CRIPTO"}
    assert listar_tickers_catalogo(db_session, "ETF") == []
    assert listar_tickers_catalogo(db_session, "CRIPTO") == []
    assert listar_tickers_catalogo(db_session, TipoAtivo.ACAO)


def test_listar_tickers_iguala_mapas_de_config(db_session):
    seed_catalogo(db_session)
    assert set(listar_tickers_catalogo(db_session, "ACAO")) == set(config.MAPA_CNPJ_B3.values())
    assert set(listar_tickers_catalogo(db_session, "FII")) == set(config.MAPA_ISCAS_MASTER.keys())


def test_listar_tickers_catalogo_vazio_quando_sem_seed(db_session, mapa_config_vazio):
    assert listar_tickers_catalogo(db_session, "ACAO") == []
    assert listar_tickers_catalogo(db_session, "FII") == []


def test_todo_cnpj_acao_do_catalogo_tem_14_digitos(db_session):
    seed_catalogo(db_session)
    for ticker in listar_tickers_catalogo(db_session, "ACAO"):
        cnpj = resolver_cnpj(db_session, ticker)
        assert cnpj is not None
        assert normalizar_cnpj(cnpj) is not None
        assert len(normalizar_cnpj(cnpj)) == 14


# ==========================================
# ESTRATÉGIA CATÁLOGO PRIMEIRO, FALLBACK DEPOIS
# ==========================================

def test_obter_tickers_com_fallback_usa_catalogo(db_session):
    seed_catalogo(db_session)
    chamado = []

    def fallback():
        chamado.append(True)
        return ["FALLBACK11"]

    resultado = obter_tickers_com_fallback(db_session, "FII", fallback)
    assert not chamado
    assert resultado == listar_tickers_catalogo(db_session, "FII")


def test_obter_tickers_com_fallback_cai_no_fallback(db_session, mapa_config_vazio):
    def fallback():
        return ["FALLBACK11", "MXRF11"]

    resultado = obter_tickers_com_fallback(db_session, "FII", fallback)
    assert resultado == ["FALLBACK11", "MXRF11"]


def test_obter_tickers_com_fallback_sem_callable_retorna_vazio(db_session, mapa_config_vazio):
    assert obter_tickers_com_fallback(db_session, "FII", None) == []


def test_obter_tickers_com_fallback_catalogo_falha_usa_fallback(db_session, monkeypatch):
    from pipeline_dados import catalogo_ativos

    def quebra_catalogo(*args, **kwargs):
        raise RuntimeError("banco indisponível")

    monkeypatch.setattr(catalogo_ativos, "listar_tickers_catalogo", quebra_catalogo)
    resultado = obter_tickers_com_fallback(db_session, "FII", lambda: ["FALLBACK11"])
    assert resultado == ["FALLBACK11"]


# ==========================================
# REGISTRO MANUAL NO CATÁLOGO
# ==========================================

def test_registrar_no_catalogo_cria_e_atualiza(db_session):
    registro = registrar_no_catalogo(
        db_session, "XXAX11", "FII", nome_emissor="XAXA", fonte="manual"
    )
    assert registro.ticker == "XXAX11"
    assert registro.tipo == "FII"

    atualizado = registrar_no_catalogo(
        db_session, "xxax11", "FII", cnpj="12.345.678/0001-99", nome_emissor="XAXA 2"
    )
    assert atualizado.id == registro.id
    assert atualizado.nome_emissor == "XAXA 2"
    assert atualizado.cnpj == "12.345.678/0001-99"
    assert db_session.query(AtivoCatalogo).count() == 1


def test_registrar_no_catalogo_cnpj_invalido_vira_none(db_session):
    registro = registrar_no_catalogo(db_session, "YYAX11", "ETF", cnpj="123")
    assert registro.cnpj is None


# ==========================================
# CONSUMIDOR 1: coletor_cvm._obter_tickers
# ==========================================

def _fake_gspread(abas):
    class _Aba:
        def __init__(self, tickers):
            self._tickers = tickers

        def col_values(self, indice):
            return ["Ticker"] + self._tickers

    class _Planilha:
        def __init__(self):
            self._abas = {nome: _Aba(tickers) for nome, tickers in abas.items()}

        def worksheet(self, nome):
            return self._abas[nome]

    class _Cliente:
        def open_by_url(self, url):
            return _Planilha()

    return _Cliente()


def test_acoescvmreader_usa_catalogo_em_vez_da_planilha(db_session, monkeypatch):
    from pipeline_dados import coletor_cvm

    def falha_sheets():
        raise AssertionError("Sheets não deveria ser consultado com catálogo disponível")

    monkeypatch.setattr(coletor_cvm, "conectar_gspread", falha_sheets)
    leitor = coletor_cvm.AcoesCVMReader(db_session)
    assert leitor.meus_tickers == listar_tickers_catalogo(db_session, "ACAO")
    assert leitor.meus_tickers


def test_acoescvmreader_cai_no_sheets_quando_catalogo_vazio(
    db_session, monkeypatch, mapa_config_vazio
):
    from pipeline_dados import coletor_cvm

    tickers_sheets = ["PETR4", "vale3", "  ", "MGLU3"]
    monkeypatch.setattr(
        coletor_cvm,
        "conectar_gspread",
        lambda: _fake_gspread({"BD_Acoes": tickers_sheets}),
    )
    leitor = coletor_cvm.AcoesCVMReader(db_session)
    assert set(leitor.meus_tickers) == {"MGLU3", "PETR4", "VALE3"}
    assert len(leitor.meus_tickers) == 3


# ==========================================
# CONSUMIDOR 2: atualizador_documentos.obter_tickers_da_planilha
# ==========================================

@pytest.fixture()
def session_factory_memory():
    def _factory():
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        return sessionmaker(bind=engine)()

    return _factory


def test_atualizador_obter_tickers_usa_catalogo(db_session, monkeypatch):
    from atualizador_documentos import obter_tickers_da_planilha

    seed_catalogo(db_session)
    monkeypatch.setattr("atualizador_documentos.SessionDB", lambda: db_session)

    def falha_sheets():
        raise AssertionError("Sheets não deveria ser consultado com catálogo disponível")

    monkeypatch.setattr("atualizador_documentos.conectar_gspread", falha_sheets)
    assert obter_tickers_da_planilha() == listar_tickers_catalogo(db_session, "FII")


def test_atualizador_obter_tickers_cai_no_sheets_quando_catalogo_vazio(
    monkeypatch, session_factory_memory, mapa_config_vazio
):
    from atualizador_documentos import obter_tickers_da_planilha

    sessao = session_factory_memory()
    monkeypatch.setattr("atualizador_documentos.SessionDB", lambda: sessao)
    tickers_sheets = ["MXRF11", "gare11", ""]
    monkeypatch.setattr(
        "atualizador_documentos.conectar_gspread",
        lambda: _fake_gspread({"BD_FIIs": tickers_sheets}),
    )
    assert set(obter_tickers_da_planilha()) == {"GARE11", "MXRF11"}
    sessao.close()
