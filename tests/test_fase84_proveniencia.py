"""Fase 8.4: proveniência real não é perdida; URL nunca é inventada."""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from pipeline_dados.banco_dados import (
    Ativo,
    Base,
    DadosFinanceirosAcoes,
    SnapshotFii,
    TipoAtivo,
    garantir_colunas_freshness,
)
from pipeline_dados.espelhamento_mercado_5c import gravar_snapshot_fii
from pipeline_dados.freshness import FONTE_SHEETS, proveniencia, url_origem_segura
from pipeline_dados.mapeamento_sheets import ORIGEM_GOOGLE_SHEETS


def _sessao():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)(), engine


def test_origem_real_preservada_quando_disponivel():
    estado = proveniencia(
        fonte_primaria="yfinance",
        fonte_intermediaria=FONTE_SHEETS,
        url_origem="https://finance.yahoo.com/quote/PETR4.SA",
        fonte=FONTE_SHEETS,
    )
    assert estado["fonte"] == FONTE_SHEETS
    assert estado["fonte_primaria"] == "yfinance"
    assert estado["fonte_intermediaria"] == FONTE_SHEETS
    assert estado["url_origem"].startswith("https://")


def test_url_origem_nao_e_inventada():
    assert url_origem_segura(None) is None
    assert url_origem_segura("") is None
    assert url_origem_segura("   ") is None
    assert url_origem_segura("fundamentus.com.br") is None
    assert url_origem_segura("ftp://x") is None
    assert url_origem_segura("https://dados.cvm.gov.br/x.zip") == (
        "https://dados.cvm.gov.br/x.zip"
    )


def test_5c_nao_inventa_url_e_marca_sheets_como_intermediaria():
    session, _ = _sessao()
    ativo = Ativo(ticker="MXRF11", cnpj=None, tipo=TipoAtivo.FII)
    session.add(ativo)
    session.flush()
    dados = {
        "ticker": "MXRF11",
        "preco": 9.87,
        "pvp": 0.95,
        "dy": 0.12,
        "qtd_imoveis": 0,
        "liquidez": 1500000.0,
        "vpa": 10.39,
        "lucro_12m": 1.0,
        "dividendo_mensal": 0.09,
        "walt": None,
        "alavancagem": None,
    }
    snap, _, status = gravar_snapshot_fii(session, ativo, dados, date(2026, 9, 3))
    session.commit()
    assert status in ("CRIADO", "ATUALIZADO")
    assert snap.fonte == ORIGEM_GOOGLE_SHEETS
    assert snap.fonte_intermediaria == FONTE_SHEETS
    assert snap.fonte_primaria is None
    assert snap.url_origem is None
    session.close()


def test_5c_preserva_fonte_primaria_e_url_quando_vierem_do_scraper():
    session, _ = _sessao()
    ativo = Ativo(ticker="HGLG11", cnpj=None, tipo=TipoAtivo.FII)
    session.add(ativo)
    session.flush()
    dados = {
        "ticker": "HGLG11",
        "preco": 160.0,
        "pvp": 0.9,
        "dy": 0.08,
        "fonte_primaria": "yfinance",
        "url_origem": "https://finance.yahoo.com/quote/HGLG11.SA",
    }
    snap, _, _ = gravar_snapshot_fii(session, ativo, dados, date(2026, 9, 3))
    session.commit()
    assert snap.fonte_primaria == "yfinance"
    assert snap.fonte_intermediaria == FONTE_SHEETS
    assert snap.url_origem == "https://finance.yahoo.com/quote/HGLG11.SA"
    session.close()


def test_5c_descarta_url_invalida():
    session, _ = _sessao()
    ativo = Ativo(ticker="XPML11", cnpj=None, tipo=TipoAtivo.FII)
    session.add(ativo)
    session.flush()
    dados = {
        "ticker": "XPML11",
        "preco": 100.0,
        "url_origem": "nao-e-url",
        "fonte_primaria": "StatusInvest",
    }
    snap, _, _ = gravar_snapshot_fii(session, ativo, dados, date(2026, 9, 3))
    assert snap.url_origem is None
    assert snap.fonte_primaria == "StatusInvest"
    session.close()


def test_migracao_aditiva_de_colunas_freshness():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    assert garantir_colunas_freshness(engine) == 0
    insp = inspect(engine)
    for tabela in ("snapshots_fiis", "snapshots_acoes"):
        nomes = {c["name"] for c in insp.get_columns(tabela)}
        assert "fonte_primaria" in nomes
        assert "fonte_intermediaria" in nomes
    for tabela in ("dados_financeiros_acoes", "dados_financeiros_fiis"):
        nomes = {c["name"] for c in insp.get_columns(tabela)}
        assert "data_coleta" in nomes
        assert "fonte" in nomes
        assert "fonte_primaria" in nomes
        assert "url_origem" in nomes


def test_data_referencia_nao_muda_na_migracao():
    session, engine = _sessao()
    ativo = Ativo(ticker="PETR4", cnpj=None, tipo=TipoAtivo.ACAO)
    session.add(ativo)
    session.flush()
    session.add(
        DadosFinanceirosAcoes(
            ativo_id=ativo.id,
            data_referencia=date(2026, 6, 30),
            tipo_doc="ITR",
            lucro_liquido=1000.0,
        )
    )
    session.add(
        SnapshotFii(
            ativo_id=ativo.id,
            data_referencia=date(2026, 8, 20),
            data_coleta=datetime(2026, 8, 20, 10, 0, 0),
            preco=Decimal("9.87"),
            fonte=ORIGEM_GOOGLE_SHEETS,
        )
    )
    session.commit()
    garantir_colunas_freshness(engine)
    session.expire_all()
    contabil = session.query(DadosFinanceirosAcoes).one()
    snap = session.query(SnapshotFii).one()
    assert contabil.data_referencia == date(2026, 6, 30)
    assert snap.data_referencia == date(2026, 8, 20)
    assert snap.fonte == ORIGEM_GOOGLE_SHEETS
    session.close()
