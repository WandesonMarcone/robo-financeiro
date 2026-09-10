"""Fase 8.4: FRESH / STALE / MISSING, SLA e distinção das datas."""
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline_dados.banco_dados import (
    Ativo,
    Base,
    DadosFinanceirosFiis,
    DocumentosQualitativos,
    SnapshotAcao,
    SnapshotFii,
    TipoAtivo,
)
from pipeline_dados.freshness import (
    CONTABIL,
    DOCUMENTOS,
    FRESH,
    INDICADORES_MERCADO,
    MISSING,
    PRECO,
    SLA_CONTABIL_ACOES,
    SLA_CONTABIL_FIIS,
    SLA_DOCUMENTOS,
    SLA_PRECO,
    STALE,
    avaliar_ativo,
    avaliar_contabil,
    avaliar_preco,
    classificar,
    dado_utilizavel,
    sla_da_categoria,
)


def _sessao():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_dentro_do_sla_e_fresh():
    agora = datetime(2026, 9, 3, 12, 0, 0)
    assert classificar(agora - timedelta(hours=1), SLA_PRECO, agora) == FRESH


def test_fora_do_sla_e_stale():
    agora = datetime(2026, 9, 3, 12, 0, 0)
    assert classificar(agora - timedelta(hours=3), SLA_PRECO, agora) == STALE


def test_inexistente_e_missing():
    assert classificar(None, SLA_PRECO, datetime.now(), utilizavel=False) == MISSING
    assert avaliar_preco(None)["status"] == MISSING


def test_zero_real_continua_utilizavel_e_fresh():
    agora = datetime(2026, 9, 3, 12, 0, 0)
    session = _sessao()
    ativo = Ativo(ticker="MXRF11", cnpj=None, tipo=TipoAtivo.FII)
    session.add(ativo)
    session.flush()
    snap = SnapshotFii(
        ativo_id=ativo.id,
        data_referencia=date(2026, 9, 3),
        data_coleta=agora - timedelta(minutes=30),
        preco=Decimal("0.0"),
        dy=Decimal("0.0"),
    )
    session.add(snap)
    session.commit()
    assert dado_utilizavel(0.0) is True
    assert dado_utilizavel(Decimal("0.0")) is True
    estado = avaliar_preco(snap, "FII", agora)
    assert estado["status"] == FRESH
    assert estado["valor"] == Decimal("0.0")
    session.close()


def test_ausencia_continua_null_e_missing():
    agora = datetime(2026, 9, 3, 12, 0, 0)
    session = _sessao()
    ativo = Ativo(ticker="GARE11", cnpj=None, tipo=TipoAtivo.FII)
    session.add(ativo)
    session.flush()
    snap = SnapshotFii(
        ativo_id=ativo.id,
        data_referencia=date(2026, 9, 3),
        data_coleta=agora,
        preco=None,
        pvp=None,
        dy=None,
    )
    session.add(snap)
    session.commit()
    assert dado_utilizavel(None) is False
    assert avaliar_preco(snap, "FII", agora)["status"] == MISSING
    session.close()


def test_data_referencia_nao_e_confundida_com_coleta():
    agora = datetime(2026, 9, 3, 12, 0, 0)
    session = _sessao()
    ativo = Ativo(ticker="PETR4", cnpj=None, tipo=TipoAtivo.ACAO)
    session.add(ativo)
    session.flush()
    snap = SnapshotAcao(
        ativo_id=ativo.id,
        data_referencia=date(2026, 9, 1),
        data_coleta=agora - timedelta(minutes=10),
        preco=Decimal("37.50"),
    )
    session.add(snap)
    session.commit()
    estado = avaliar_preco(snap, "ACAO", agora)
    assert estado["data_referencia"] == date(2026, 9, 1)
    assert estado["data_coleta"] == agora - timedelta(minutes=10)
    assert estado["status"] == FRESH
    session.close()


def test_categorias_independentes_no_mesmo_ativo():
    agora = datetime(2026, 9, 3, 12, 0, 0)
    session = _sessao()
    ativo = Ativo(ticker="HGLG11", cnpj=None, tipo=TipoAtivo.FII)
    session.add(ativo)
    session.flush()
    session.add(
        SnapshotFii(
            ativo_id=ativo.id,
            data_referencia=date(2026, 9, 3),
            data_coleta=agora - timedelta(minutes=20),
            preco=Decimal("160.0"),
            pvp=Decimal("0.95"),
        )
    )
    session.add(
        DadosFinanceirosFiis(
            ativo_id=ativo.id,
            data_referencia=date(2026, 1, 31),
            data_coleta=agora - timedelta(days=90),
            patrimonio_liquido=1000.0,
        )
    )
    session.add(
        DocumentosQualitativos(
            ativo_id=ativo.id,
            data_publicacao=date(2026, 8, 1),
            tipo_documento="Informe Mensal",
            data_atualizacao=agora - timedelta(days=1),
        )
    )
    session.commit()
    estado = avaliar_ativo(session, ativo, agora=agora)
    assert estado["categorias"][PRECO]["status"] == FRESH
    assert estado["categorias"][INDICADORES_MERCADO]["status"] == FRESH
    assert estado["categorias"][CONTABIL]["status"] == STALE
    assert estado["categorias"][DOCUMENTOS]["status"] == FRESH
    session.close()


def test_sla_contabil_diferencia_acao_e_fii():
    assert sla_da_categoria(CONTABIL, "ACAO") == SLA_CONTABIL_ACOES
    assert sla_da_categoria(CONTABIL, "FII") == SLA_CONTABIL_FIIS
    assert sla_da_categoria(DOCUMENTOS) == SLA_DOCUMENTOS


def test_contabil_sem_coleta_com_valor_e_stale():
    registro = DadosFinanceirosFiis(
        ativo_id=1,
        data_referencia=date(2026, 6, 30),
        patrimonio_liquido=10.0,
    )
    estado = avaliar_contabil(registro, "FII", datetime(2026, 9, 3))
    assert estado["status"] == STALE
    assert estado["data_referencia"] == date(2026, 6, 30)
