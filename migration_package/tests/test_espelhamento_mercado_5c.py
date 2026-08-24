"""Testes da dupla escrita FIIs -> PostgreSQL (Fase 3, Bloco 5C, PoC).

Cobre: primeira execução cria snapshots/perfis; segunda execução não duplica
(idempotência por ativo_id+data_referencia); data_referencia diferente cria
nova linha; dado INVALID não é persistido; dado WARNING é persistido; perfil
1:1; Google Sheets nunca é alterado; ausência de PostgreSQL não mascara erro
nem corrompe o caminho legado do Sheets.
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
    SnapshotFii,
    TipoAtivo,
)
from pipeline_dados.espelhamento_mercado_5c import espelhar_mercado_fiis
from pipeline_dados.mapeamento_sheets import ORIGEM_GOOGLE_SHEETS


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessao = sessionmaker(bind=engine)()
    yield sessao
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


def matriz_com_preco_negativo():
    matriz = matriz_fiis()
    matriz.append(["HGCR11", "Papel", "CRI", -1.00, 0, 1.5, 0.12, 0.0, 0,
                   "Não informado", "Pendente de IA", "Pendente de IA", 1000.0,
                   1000000000.0, 1.0, 120000000.0, 0.01, "19/08 10:00"])
    return matriz


def matriz_com_qtd_imoveis_decimal():
    matriz = matriz_fiis()
    matriz.append(["BTLG11", "Tijolo", "Logística", 40.0, 0, 0.8, 0.09, 0.02, 2.5,
                   "Não informado", "Pendente de IA", "Pendente de IA", 500000.0,
                   2000000000.0, 50.0, 180000000.0, 0.30, "19/08 10:00"])
    return matriz


# ==========================================
# PRIMEIRA EXECUÇÃO / IDEMPOTÊNCIA
# ==========================================

def test_primeira_execucao_cria_snapshots_e_perfis(db_session):
    rel = espelhar_mercado_fiis(db_session, matriz_fiis(), data_referencia=date(2026, 8, 20))
    assert rel["linhas"] == 2
    assert rel["criados"] == 2
    assert rel["atualizados"] == 0
    assert rel["invalidos"] == 0
    assert rel["perfis_criados"] == 2
    assert sorted(rel["tickers"]) == ["GARE11", "MXRF11"]
    assert db_session.query(SnapshotFii).count() == 2
    assert db_session.query(AtivoPerfil).count() == 2


def test_segunda_execucao_nao_duplica(db_session):
    espelhar_mercado_fiis(db_session, matriz_fiis(), data_referencia=date(2026, 8, 20))
    rel = espelhar_mercado_fiis(db_session, matriz_fiis(), data_referencia=date(2026, 8, 20))
    assert rel["criados"] == 0
    assert rel["atualizados"] == 2
    assert rel["perfis_criados"] == 0
    assert db_session.query(SnapshotFii).count() == 2
    assert db_session.query(AtivoPerfil).count() == 2


def test_data_referencia_diferente_cria_nova_linha(db_session):
    espelhar_mercado_fiis(db_session, matriz_fiis(), data_referencia=date(2026, 8, 19))
    rel = espelhar_mercado_fiis(db_session, matriz_fiis(), data_referencia=date(2026, 8, 20))
    assert rel["criados"] == 2
    assert db_session.query(SnapshotFii).count() == 4


def test_snapshot_ja_existente_e_atualizado(db_session):
    espelhar_mercado_fiis(db_session, matriz_fiis(), data_referencia=date(2026, 8, 20))
    snap = db_session.query(SnapshotFii).filter_by(
        ativo_id=db_session.query(Ativo).filter_by(ticker="MXRF11").one().id,
        data_referencia=date(2026, 8, 20),
    ).one()
    assert snap.preco == Decimal("9.87")


# ==========================================
# DATA QUALITY: INVALID / WARNING
# ==========================================

def test_dado_invalido_nao_persiste_snapshot(db_session):
    rel = espelhar_mercado_fiis(db_session, matriz_com_preco_negativo(), data_referencia=date(2026, 8, 20))
    assert rel["invalidos"] == 1
    assert rel["criados"] == 2
    assert db_session.query(SnapshotFii).count() == 2
    hgcr = db_session.query(Ativo).filter_by(ticker="HGCR11").first()
    assert hgcr is not None
    assert db_session.query(SnapshotFii).filter_by(ativo_id=hgcr.id).count() == 0


def test_dado_warning_persiste(db_session):
    rel = espelhar_mercado_fiis(db_session, matriz_com_qtd_imoveis_decimal(), data_referencia=date(2026, 8, 20))
    assert rel["warnings"] == 1
    assert rel["criados"] == 3
    assert db_session.query(SnapshotFii).count() == 3


def test_carimbo_nao_e_usado_como_data_referencia(db_session):
    rel = espelhar_mercado_fiis(db_session, matriz_fiis(), data_referencia=date(2026, 8, 20))
    assert rel["data_referencia"] == "2026-08-20"
    datas = {s.data_referencia for s in db_session.query(SnapshotFii).all()}
    assert datas == {date(2026, 8, 20)}


# ==========================================
# PERFIL 1:1 E VALORES PERSISTIDOS
# ==========================================

def test_perfil_guardado_com_setor_e_tipo_fii(db_session):
    espelhar_mercado_fiis(db_session, matriz_fiis(), data_referencia=date(2026, 8, 20))
    perfil = db_session.query(AtivoPerfil).join(Ativo).filter(Ativo.ticker == "GARE11").one()
    assert perfil.setor == "Logística"
    assert perfil.tipo_fii == "Tijolo"


def test_perfil_nao_apaga_valores_existentes(db_session):
    ativo = Ativo(ticker="MXRF11", cnpj="PENDENTE-MXRF11", tipo=TipoAtivo.FII)
    db_session.add(ativo)
    db_session.flush()
    db_session.add(AtivoPerfil(ativo_id=ativo.id, setor="Papel"))
    db_session.commit()

    matriz = matriz_fiis()
    matriz[1] = ["MXRF11", "", "", 9.87, 500000000.0, 0.95, 0.12, 0.0, 0,
                 "Não informado", "Pendente de IA", "Pendente de IA", 1500000.0,
                 4800000000.0, 10.39, 576000000.0, 0.0987, "19/08 10:00"]
    espelhar_mercado_fiis(db_session, matriz, data_referencia=date(2026, 8, 20))
    perfil = db_session.query(AtivoPerfil).filter_by(ativo_id=ativo.id).one()
    assert perfil.setor == "Papel"
    assert db_session.query(AtivoPerfil).count() == 2


def test_valores_numeric_e_strings_persistidos(db_session):
    espelhar_mercado_fiis(db_session, matriz_fiis(), data_referencia=date(2026, 8, 20))
    snap = db_session.query(SnapshotFii).join(Ativo).filter(Ativo.ticker == "MXRF11").one()
    assert snap.preco == Decimal("9.87")
    assert snap.pvp == Decimal("0.95")
    assert snap.dy == Decimal("0.12")
    assert snap.liquidez == Decimal("1500000.0")
    assert snap.vpa == Decimal("10.39")
    assert snap.lucro_12m == Decimal("576000000.0")
    assert snap.dividendo_mensal == Decimal("0.0987")
    assert snap.qtd_imoveis == 0
    assert snap.walt == "Pendente de IA"
    assert snap.alavancagem == "Pendente de IA"
    assert snap.fonte == ORIGEM_GOOGLE_SHEETS
    assert snap.url_origem is None
    assert snap.data_coleta is not None


def test_qtd_imoveis_decimal_nao_persistido(db_session):
    espelhar_mercado_fiis(db_session, matriz_com_qtd_imoveis_decimal(), data_referencia=date(2026, 8, 20))
    snap = db_session.query(SnapshotFii).join(Ativo).filter(Ativo.ticker == "BTLG11").one()
    assert snap.qtd_imoveis is None


# ==========================================
# GOOGLE SHEETS INTACTO / AUSÊNCIA DE POSTGRES
# ==========================================

def test_matriz_de_entrada_nao_e_alterada(db_session):
    matriz = matriz_fiis()
    copia = [list(linha) for linha in matriz]
    espelhar_mercado_fiis(db_session, matriz, data_referencia=date(2026, 8, 20))
    assert matriz == copia


def test_origem_registrada_no_relatorio(db_session):
    rel = espelhar_mercado_fiis(db_session, matriz_fiis(), data_referencia=date(2026, 8, 20))
    assert rel["origem"] == ORIGEM_GOOGLE_SHEETS


def test_sem_postgres_erro_nao_e_mascarado(db_session, monkeypatch):
    def _falhar():
        raise OperationalError("fail", None, "banco indisponível")

    monkeypatch.setattr(modulo_5c, "_criar_sessao", _falhar)
    matriz = matriz_fiis()
    with pytest.raises(OperationalError):
        espelhar_mercado_fiis(matriz=matriz, data_referencia=date(2026, 8, 20))
    assert matriz[1][0] == "MXRF11"


def test_matriz_vazia_retorna_relatorio_vazio(db_session):
    rel = espelhar_mercado_fiis(db_session, [], data_referencia=date(2026, 8, 20))
    assert rel["linhas"] == 0
    assert rel["criados"] == 0
    rel = espelhar_mercado_fiis(db_session, [["cabecalho"]], data_referencia=date(2026, 8, 20))
    assert rel["linhas"] == 0
