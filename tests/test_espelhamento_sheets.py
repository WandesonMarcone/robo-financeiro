import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline_dados.banco_dados import Ativo, AtivoCatalogo, Base, TipoAtivo
from pipeline_dados.catalogo_ativos import registrar_no_catalogo
from pipeline_dados.espelhamento_sheets import (
    ORIGEM_GOOGLE_SHEETS,
    STATUS_ATUALIZADO,
    STATUS_CRIADO,
    STATUS_INALTERADO,
    STATUS_INVALIDO,
    _criar_sessao,
    espelhar_ativo,
    espelhar_planilha,
)
from pipeline_dados.qualidade_dados import INVALID, VALID, WARNING


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessao = sessionmaker(bind=engine)()
    yield sessao
    sessao.close()


# ==========================================
# HELPER DE SESSÃO (HARDENING OPERACIONAL)
# ==========================================

def test_criar_sessao_configura_pool_para_neon():
    # Fase 7, Etapa 7.4: _criar_sessao delega para o engine central único de
    # services/db (não cria mais engine local a cada chamada). O teste valida
    # que a sessão vem do engine central com os parâmetros de pool do legado.
    sessao = _criar_sessao()
    try:
        pool = sessao.get_bind().pool
        assert pool._pre_ping is True
        assert pool._recycle == 1800
    finally:
        sessao.close()


def matriz_fiis():
    cabecalho = ["Ticker", "Tipo", "Setor", "Preço", "Cotas", "P/VP", "DY", "Vacância",
                 "Imóveis", "Inquilinos", "WALT", "Alavancagem", "Liquidez",
                 "Valor Mercado", "VPA", "Lucro 12M", "Div Mensal", "Carimbo"]
    linhas = [
        ["MXRF11", "Papel", "CRI", 9.87, 500000000.0, 0.95, 0.12, 0.0, 0,
         "Não informado", "Pendente de IA", "Pendente de IA", 1500000.0,
         4800000000.0, 10.39, 576000000.0, 0.0987, "19/08 10:00"],
        ["GARE11", "Tijolo", "Logística", 12.30, 200000000.0, 0.90, 0.10, 0.05, 3,
         "Inquilino A (50%), Inquilino B (50%)", "Pendente de IA", "Pendente de IA",
         800000.0, 2400000000.0, 13.67, 240000000.0, 0.1025, "19/08 10:00"],
        ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""],
    ]
    return [cabecalho] + linhas


def matriz_acoes():
    cabecalho = ["Ticker", "Setor", "Preço", "DY", "Qtd Ações", "P/L", "P/VP", "P/Ativo",
                 "Marg. Bruta", "Marg. EBIT", "Marg. Líq", "P/EBIT", "EV/EBIT",
                 "Dív/EBIT", "Dív/Patrim", "PSR", "P/Cap.Giro", "P/At.Circ.Liq",
                 "Liq. Corr", "ROE", "ROA", "ROIC", "Reservado", "Reservado",
                 "Reservado", "CAGR 5a", "Reservado", "Liq. Média", "VPA", "LPA",
                 "PEG", "Valor Mercado", "Carimbo"]
    linhas = [
        ["PETR4", "Petróleo, Gás & Biocombustíveis", 37.52, 0.14, 12300000000.0,
         4.5, 1.2, 0.8, 0.55, 0.30, 0.12, 8.0, 5.0, 0.5, 0.8, 0.9, 1.2, 1.1, 1.5,
         0.18, 0.12, 0.16, 0, 0, 0, 0.10, 0, 85000000.0, 31.0, 8.3, 1.1,
         400000000000.0, "19/08 10:00"],
        ["VALE3", "Materiais Básicos", 65.10, 0.11, 5100000000.0,
         6.0, 1.5, 1.0, 0.60, 0.40, 0.25, 9.0, 6.0, 0.7, 1.0, 1.1, 1.3, 1.2, 1.8,
         0.22, 0.15, 0.19, 0, 0, 0, 0.12, 0, 120000000.0, 44.0, 10.8, 1.4,
         600000000000.0, "19/08 10:00"],
    ]
    return [cabecalho] + linhas


# ==========================================
# ESPELHAR ATIVO
# ==========================================

def test_espelhar_ativo_cria_registro_fii(db_session):
    ativo, resultado, status = espelhar_ativo(db_session, "MXRF11", TipoAtivo.FII)
    assert status == STATUS_CRIADO
    assert resultado.status == VALID
    assert ativo.ticker == "MXRF11"
    assert ativo.tipo == TipoAtivo.FII
    assert ativo.cnpj == "PENDENTE-MXRF11"
    assert db_session.query(Ativo).count() == 1


def test_espelhar_ativo_acao_usa_cnpj_do_catalogo(db_session):
    ativo, _, status = espelhar_ativo(db_session, "PETR4", TipoAtivo.ACAO)
    assert status == STATUS_CRIADO
    assert ativo.cnpj == "33.000.167/0001-01"


def test_espelhar_ativo_idempotente(db_session):
    ativo, resultado, status = espelhar_ativo(db_session, "MXRF11", TipoAtivo.FII)
    assert status == STATUS_CRIADO
    assert resultado.status == VALID

    _, resultado2, status2 = espelhar_ativo(db_session, "MXRF11", TipoAtivo.FII)
    assert status2 == STATUS_INALTERADO
    assert db_session.query(Ativo).count() == 1


def test_espelhar_ativo_ticker_invalido_bloqueado(db_session):
    ativo, resultado, status = espelhar_ativo(db_session, "   ", TipoAtivo.FII)
    assert status == STATUS_INVALIDO
    assert resultado.status == INVALID
    assert ativo is None
    assert db_session.query(Ativo).count() == 0


def test_espelhar_ativo_atualiza_placeholder_para_cnpj_real(db_session):
    ativo = Ativo(ticker="PETR4", cnpj="PENDENTE-PETR4", tipo=TipoAtivo.ACAO)
    db_session.add(ativo)
    db_session.flush()

    _, _, status = espelhar_ativo(db_session, "PETR4", TipoAtivo.ACAO)
    assert status == STATUS_ATUALIZADO
    assert ativo.cnpj == "33.000.167/0001-01"
    assert db_session.query(Ativo).count() == 1


def test_espelhar_ativo_nao_sobrescreve_cnpj_real_existente(db_session):
    ativo = Ativo(ticker="PETR4", cnpj="33.000.167/0001-01", tipo=TipoAtivo.ACAO)
    db_session.add(ativo)
    db_session.flush()

    _, _, status = espelhar_ativo(db_session, "PETR4", TipoAtivo.ACAO)
    assert status == STATUS_INALTERADO
    assert ativo.cnpj == "33.000.167/0001-01"


def test_cnpj_invalido_do_catalogo_gera_warning_mas_nao_bloqueia(db_session):
    ativo, resultado, status = espelhar_ativo(db_session, "CXSE3", TipoAtivo.ACAO)
    assert status == STATUS_CRIADO
    assert resultado.status == WARNING
    assert ativo is not None
    assert ativo.cnpj == "22.180.207/0001-72"
    assert any(a.campo == "cnpj" for a in resultado.achados)


# ==========================================
# IDENTIDADE VIA CATÁLOGO DA FASE 7, ETAPA 7.2
# ==========================================

def test_espelhar_ativo_prefere_cnpj_do_catalogo_ao_placeholder(db_session):
    registrar_no_catalogo(
        db_session, "MXRF11", TipoAtivo.FII,
        cnpj="29.265.280/0001-40", nome_emissor="MXRF11 Fundo", fonte="teste",
    )
    ativo, _, status = espelhar_ativo(db_session, "MXRF11", TipoAtivo.FII)
    assert status == STATUS_CRIADO
    assert ativo.cnpj == "29.265.280/0001-40"


def test_espelhar_ativo_catalogo_tem_prioridade_sobre_config(db_session):
    registrar_no_catalogo(
        db_session, "PETR4", TipoAtivo.ACAO,
        cnpj="33.000.167/0001-01", fonte="teste",
    )
    ativo, _, status = espelhar_ativo(db_session, "PETR4", TipoAtivo.ACAO)
    assert status == STATUS_CRIADO
    assert ativo.cnpj == "33.000.167/0001-01"


def test_espelhar_ativo_fii_sem_catalogo_mantem_placeholder(db_session):
    ativo, _, status = espelhar_ativo(db_session, "MXRF11", TipoAtivo.FII)
    assert status == STATUS_CRIADO
    assert ativo.cnpj == "PENDENTE-MXRF11"
    assert db_session.query(AtivoCatalogo).count() == 0


# ==========================================
# ESPELHAR PLANILHA
# ==========================================

def test_espelhar_planilha_fiis(db_session):
    relatorio = espelhar_planilha(db_session, "BD_FIIs", matriz_fiis())
    assert relatorio["linhas"] == 2
    assert relatorio["criados"] == 2
    assert relatorio["invalidos"] == 0
    assert sorted(relatorio["tickers"]) == ["GARE11", "MXRF11"]
    assert db_session.query(Ativo).count() == 2
    assert "vacancia" in relatorio["lacunas"]
    assert "numero_cotas" in relatorio["lacunas"]


def test_espelhar_planilha_acoes(db_session):
    relatorio = espelhar_planilha(db_session, "BD_Acoes", matriz_acoes())
    assert relatorio["criados"] == 2
    assert db_session.query(Ativo).count() == 2
    assert sorted(relatorio["tickers"]) == ["PETR4", "VALE3"]
    assert all(a.tipo == TipoAtivo.ACAO for a in db_session.query(Ativo).all())


def test_espelhar_planilha_repetida_nao_duplica(db_session):
    espelhar_planilha(db_session, "BD_FIIs", matriz_fiis())
    relatorio = espelhar_planilha(db_session, "BD_FIIs", matriz_fiis())
    assert relatorio["criados"] == 0
    assert relatorio["inalterados"] == 2
    assert db_session.query(Ativo).count() == 2


def test_espelhar_planilha_preserva_ativos_existentes(db_session):
    wege = Ativo(ticker="WEGE3", cnpj="84.683.601/0001-74", tipo=TipoAtivo.ACAO)
    db_session.add(wege)
    db_session.flush()

    matriz = matriz_acoes()
    matriz.append(["WEGE3", "Bens Industriais", 40.0, 0.08, 3900000000.0,
                   30.0, 5.0, 2.0, 0.30, 0.15, 0.10, 25.0, 15.0, 0.3, 0.5, 2.0,
                   1.5, 1.4, 2.0, 0.25, 0.10, 0.20, 0, 0, 0, 0.15, 0, 60000000.0,
                   20.0, 1.3, 3.0, 150000000000.0, "19/08 10:00"])
    relatorio = espelhar_planilha(db_session, "BD_Acoes", matriz)
    assert relatorio["criados"] == 2
    assert relatorio["inalterados"] == 1
    assert db_session.query(Ativo).filter(Ativo.ticker == "WEGE3").one().cnpj == "84.683.601/0001-74"


def test_espelhar_planilha_aba_desconhecida_levanta_erro(db_session):
    with pytest.raises(ValueError):
        espelhar_planilha(db_session, "BD_Logs", [["a"], ["b"]])


def test_espelhar_planilha_vazia(db_session):
    relatorio = espelhar_planilha(db_session, "BD_FIIs", None)
    assert relatorio["linhas"] == 0
    relatorio = espelhar_planilha(db_session, "BD_FIIs", [["cabecalho"]])
    assert relatorio["linhas"] == 0


# ==========================================
# RASTREABILIDADE / ORIGEM
# ==========================================

def test_origem_registrada_no_resultado(db_session):
    _, resultado, _ = espelhar_ativo(db_session, "MXRF11", TipoAtivo.FII)
    assert resultado.origem == ORIGEM_GOOGLE_SHEETS
    assert resultado.ativo == "MXRF11"


def test_origem_registrada_no_relatorio(db_session):
    relatorio = espelhar_planilha(db_session, "BD_Acoes", matriz_acoes())
    assert relatorio["origem"] == ORIGEM_GOOGLE_SHEETS
