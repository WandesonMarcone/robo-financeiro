"""Testes da dupla escrita Ações -> PostgreSQL (Fase 3, Bloco 5C).

Cobre: criação inicial; idempotência (segunda execução não duplica);
data_referencia diferente cria nova linha; INVALID não persiste; WARNING
persiste; perfil 1:1 (setor); valores NUMERIC preservados; ``div_liq_ebit``
não é persistido (origem duplicada com Dív.Líq/Patrimônio); Google Sheets
nunca é alterado; ausência de PostgreSQL não mascara erro.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from pipeline_dados import espelhamento_mercado_5c as modulo_5c
from pipeline_dados.banco_dados import (
    Ativo,
    AtivoPerfil,
    Base,
    SnapshotAcao,
    TipoAtivo,
)
from pipeline_dados.espelhamento_mercado_5c import espelhar_mercado_acoes
from pipeline_dados.mapeamento_sheets import ORIGEM_GOOGLE_SHEETS


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessao = sessionmaker(bind=engine)()
    yield sessao
    sessao.close()


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
        ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "",
         "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""],
    ]
    return [cabecalho] + linhas


def matriz_com_preco_negativo():
    matriz = matriz_acoes()
    matriz.append(["ITUB4", "Financeiro", -10.0, 0.05, 10000000000.0,
                   8.0, 1.0, 0.5, 0.40, 0.25, 0.15, 10.0, 7.0, 0.6, 0.9, 1.0, 1.1,
                   1.0, 1.3, 0.15, 0.08, 0.12, 0, 0, 0, 0.08, 0, 90000000.0,
                   25.0, 3.1, 1.5, 300000000000.0, "19/08 10:00"])
    return matriz


def matriz_com_roe_negativo():
    matriz = matriz_acoes()
    matriz.append(["BBDC4", "Financeiro", 20.0, 0.05, 10000000000.0,
                   10.0, 1.5, 0.8, 0.50, 0.30, -0.04, 12.0, 8.0, 0.5, 0.7, 1.2,
                   1.0, 0.9, 1.1, -0.05, 0.06, 0.09, 0, 0, 0, 0.05, 0, 60000000.0,
                   15.0, 2.0, 2.0, 150000000000.0, "19/08 10:00"])
    return matriz


# ==========================================
# PRIMEIRA EXECUÇÃO / IDEMPOTÊNCIA
# ==========================================

def test_primeira_execucao_cria_snapshots_e_perfis(db_session):
    rel = espelhar_mercado_acoes(db_session, matriz_acoes(), data_referencia=date(2026, 8, 20))
    assert rel["aba"] == "BD_Acoes"
    assert rel["linhas"] == 2
    assert rel["criados"] == 2
    assert rel["atualizados"] == 0
    assert rel["invalidos"] == 0
    assert rel["perfis_criados"] == 2
    assert sorted(rel["tickers"]) == ["PETR4", "VALE3"]
    assert db_session.query(SnapshotAcao).count() == 2
    assert db_session.query(AtivoPerfil).count() == 2


def test_segunda_execucao_nao_duplica(db_session):
    espelhar_mercado_acoes(db_session, matriz_acoes(), data_referencia=date(2026, 8, 20))
    rel = espelhar_mercado_acoes(db_session, matriz_acoes(), data_referencia=date(2026, 8, 20))
    assert rel["criados"] == 0
    assert rel["atualizados"] == 2
    assert rel["perfis_criados"] == 0
    assert db_session.query(SnapshotAcao).count() == 2
    assert db_session.query(AtivoPerfil).count() == 2


def test_data_referencia_diferente_cria_nova_linha(db_session):
    espelhar_mercado_acoes(db_session, matriz_acoes(), data_referencia=date(2026, 8, 19))
    rel = espelhar_mercado_acoes(db_session, matriz_acoes(), data_referencia=date(2026, 8, 20))
    assert rel["criados"] == 2
    assert db_session.query(SnapshotAcao).count() == 4


# ==========================================
# DATA QUALITY: INVALID / WARNING
# ==========================================

def test_dado_invalido_nao_persiste_snapshot(db_session):
    rel = espelhar_mercado_acoes(db_session, matriz_com_preco_negativo(), data_referencia=date(2026, 8, 20))
    assert rel["invalidos"] == 1
    assert rel["criados"] == 2
    assert db_session.query(SnapshotAcao).count() == 2
    itub = db_session.query(Ativo).filter_by(ticker="ITUB4").first()
    assert itub is not None
    assert db_session.query(SnapshotAcao).filter_by(ativo_id=itub.id).count() == 0


def test_dado_warning_persiste(db_session):
    rel = espelhar_mercado_acoes(db_session, matriz_com_roe_negativo(), data_referencia=date(2026, 8, 20))
    assert rel["warnings"] == 1
    assert rel["criados"] == 3
    assert db_session.query(SnapshotAcao).count() == 3


# ==========================================
# PERFIL E VALORES PERSISTIDOS
# ==========================================

def test_perfil_setor_guardado(db_session):
    espelhar_mercado_acoes(db_session, matriz_acoes(), data_referencia=date(2026, 8, 20))
    perfil = db_session.query(AtivoPerfil).join(Ativo).filter(Ativo.ticker == "PETR4").one()
    assert perfil.setor == "Petróleo, Gás & Biocombustíveis"
    assert perfil.tipo_fii is None


def test_valores_numeric_preservados(db_session):
    espelhar_mercado_acoes(db_session, matriz_acoes(), data_referencia=date(2026, 8, 20))
    snap = db_session.query(SnapshotAcao).join(Ativo).filter(Ativo.ticker == "PETR4").one()
    assert snap.preco == Decimal("37.52")
    assert snap.dy == Decimal("0.14")
    assert snap.pl == Decimal("4.5")
    assert snap.pvp == Decimal("1.2")
    assert snap.p_ativo == Decimal("0.8")
    assert snap.marg_bruta == Decimal("0.55")
    assert snap.marg_ebit == Decimal("0.30")
    assert snap.marg_liquida == Decimal("0.12")
    assert snap.p_ebit == Decimal("8.0")
    assert snap.ev_ebit == Decimal("5.0")
    assert snap.div_liq_patrimonio == Decimal("0.8")
    assert snap.psr == Decimal("0.9")
    assert snap.p_cap_giro == Decimal("1.2")
    assert snap.p_at_circ_liq == Decimal("1.1")
    assert snap.liq_corrente == Decimal("1.5")
    assert snap.roe == Decimal("0.18")
    assert snap.roa == Decimal("0.12")
    assert snap.roic == Decimal("0.16")
    assert snap.cagr_rec_5a == Decimal("0.10")
    assert snap.liq_media == Decimal("85000000.0")
    assert snap.vpa == Decimal("31.0")
    assert snap.lpa == Decimal("8.3")
    assert snap.peg_ratio == Decimal("1.1")
    assert snap.valor_mercado == Decimal("400000000000.0")


def test_div_liq_ebit_nao_persistido(db_session):
    espelhar_mercado_acoes(db_session, matriz_acoes(), data_referencia=date(2026, 8, 20))
    snap = db_session.query(SnapshotAcao).join(Ativo).filter(Ativo.ticker == "PETR4").one()
    assert snap.div_liq_ebit is None
    assert snap.div_liq_patrimonio == Decimal("0.8")


def test_fonte_e_data_coleta_registradas(db_session):
    espelhar_mercado_acoes(db_session, matriz_acoes(), data_referencia=date(2026, 8, 20))
    snap = db_session.query(SnapshotAcao).first()
    assert snap.fonte == ORIGEM_GOOGLE_SHEETS
    assert snap.url_origem is None
    assert snap.data_coleta is not None
    assert snap.data_referencia == date(2026, 8, 20)


# ==========================================
# GOOGLE SHEETS INTACTO / AUSÊNCIA DE POSTGRES
# ==========================================

def test_matriz_de_entrada_nao_e_alterada(db_session):
    matriz = matriz_acoes()
    copia = [list(linha) for linha in matriz]
    espelhar_mercado_acoes(db_session, matriz, data_referencia=date(2026, 8, 20))
    assert matriz == copia


def test_origem_registrada_no_relatorio(db_session):
    rel = espelhar_mercado_acoes(db_session, matriz_acoes(), data_referencia=date(2026, 8, 20))
    assert rel["origem"] == ORIGEM_GOOGLE_SHEETS


def test_sem_postgres_erro_nao_e_mascarado(monkeypatch):
    def _falhar():
        raise OperationalError("fail", None, "banco indisponível")

    monkeypatch.setattr(modulo_5c, "_criar_sessao", _falhar)
    matriz = matriz_acoes()
    with pytest.raises(OperationalError):
        espelhar_mercado_acoes(matriz=matriz, data_referencia=date(2026, 8, 20))
    assert matriz[1][0] == "PETR4"


def test_matriz_vazia_retorna_relatorio_vazio(db_session):
    rel = espelhar_mercado_acoes(db_session, [], data_referencia=date(2026, 8, 20))
    assert rel["linhas"] == 0
    assert rel["criados"] == 0
    rel = espelhar_mercado_acoes(db_session, [["cabecalho"]], data_referencia=date(2026, 8, 20))
    assert rel["linhas"] == 0


def test_cnpj_acao_resolvido_via_catalogo(db_session):
    espelhar_mercado_acoes(db_session, matriz_acoes(), data_referencia=date(2026, 8, 20))
    ativo = db_session.query(Ativo).filter_by(ticker="PETR4").one()
    assert ativo.tipo == TipoAtivo.ACAO
    assert ativo.cnpj == "33.000.167/0001-01"
