"""Fase 8.4: cobertura por ativo, fora da coleta e execução parcial."""
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import config
from pipeline_dados.banco_dados import Ativo, Base, SnapshotFii, TipoAtivo
from pipeline_dados.catalogo_ativos import registrar_no_catalogo, seed_catalogo
from pipeline_dados.cobertura import (
    capacidade_por_execucao,
    cobertura_catalogo,
    cobertura_tipo,
    contar_universo,
    registrar_execucao,
)
from pipeline_dados.freshness import PRECO
from services import mercado


def _sessao():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_universo_catalogo_e_mensuravel():
    session = _sessao()
    seed_catalogo(session)
    universo = contar_universo(session)
    assert universo["fiis_catalogo"] == len(config.MAPA_ISCAS_MASTER)
    assert universo["acoes_catalogo"] == len(config.MAPA_CNPJ_B3)
    assert universo["mapa_iscas"] == len(config.MAPA_ISCAS_MASTER)
    assert universo["mapa_cnpj_b3"] == len(config.MAPA_CNPJ_B3)
    assert universo["fiis_fixas"] == len(config.FIXAS_FIIS)
    assert universo["acoes_fixas"] == len(config.FIXAS_ACOES)
    session.close()


def test_ativos_nao_coletados_sao_identificaveis():
    session = _sessao()
    seed_catalogo(session)
    mxrf = Ativo(ticker="MXRF11", cnpj=None, tipo=TipoAtivo.FII)
    session.add(mxrf)
    session.flush()
    session.add(
        SnapshotFii(
            ativo_id=mxrf.id,
            data_referencia=date(2026, 9, 3),
            data_coleta=datetime(2026, 9, 3, 10, 0, 0),
            preco=Decimal("9.87"),
        )
    )
    session.commit()
    rel = cobertura_tipo(session, "FII", PRECO)
    assert "MXRF11" in rel["coletados"]
    assert "HGLG11" in rel["fora"]
    assert rel["fora_total"] == rel["universo_total"] - 1
    assert rel["cobertura_total"] is False
    session.close()


def test_execucao_parcial_nao_e_cobertura_total():
    session = _sessao()
    seed_catalogo(session)
    rel = cobertura_tipo(session, "FII", PRECO, coletados=["MXRF11", "GARE11"])
    assert rel["coletados"] == ["GARE11", "MXRF11"]
    assert rel["execucao_parcial"] is True
    assert rel["cobertura_total"] is False
    capacidade = capacidade_por_execucao()
    assert capacidade["fiis_por_execucao_max"] < len(config.MAPA_ISCAS_MASTER)
    assert capacidade["acoes_por_execucao_max"] < len(config.MAPA_CNPJ_B3)
    session.close()


def test_cobertura_por_ativo_e_calculavel():
    session = _sessao()
    registrar_no_catalogo(session, "MXRF11", TipoAtivo.FII)
    registrar_no_catalogo(session, "GARE11", TipoAtivo.FII)
    agora = datetime(2026, 9, 3, 12, 0, 0)
    mxrf = Ativo(ticker="MXRF11", cnpj=None, tipo=TipoAtivo.FII)
    session.add(mxrf)
    session.flush()
    session.add(
        SnapshotFii(
            ativo_id=mxrf.id,
            data_referencia=date(2026, 9, 3),
            data_coleta=agora - timedelta(minutes=10),
            preco=Decimal("9.87"),
        )
    )
    session.commit()
    estado = mercado.obter_freshness(ticker="MXRF11", session=session, agora=agora)
    assert estado["ticker"] == "MXRF11"
    assert estado["categorias"][PRECO]["status"] == "FRESH"
    rel = cobertura_catalogo(session, agora=agora)
    assert rel["execucao_parcial"] is True
    session.close()


def test_registrar_execucao_marca_amostra():
    execucao = registrar_execucao(["mxrf11", "GARE11", ""], "FII")
    assert execucao["coletados"] == ["GARE11", "MXRF11"]
    assert execucao["coletados_total"] == 2
    assert execucao["execucao_parcial"] is True


def test_servico_universo_nao_expande_coleta():
    session = _sessao()
    seed_catalogo(session)
    universo = mercado.obter_universo(session=session)
    assert universo["total_catalogo"] == (
        len(config.MAPA_ISCAS_MASTER) + len(config.MAPA_CNPJ_B3)
    )
    session.close()
