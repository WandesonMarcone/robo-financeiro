"""Fase 8.3: identidade canônica ticker → catálogo → CNPJ real ou None."""
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from pipeline_dados.banco_dados import Ativo, AtivoCatalogo, Base, TipoAtivo
from pipeline_dados.catalogo_ativos import (
    consultar_por_cnpj,
    consultar_por_ticker,
    garantir_ativo,
    registrar_no_catalogo,
    resolver_cnpj,
    resolver_ticker_fii,
    seed_catalogo,
)
from pipeline_dados.espelhamento_sheets import STATUS_CRIADO, espelhar_ativo


def _sessao():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)(), engine


def test_ticker_e_identidade_operacional():
    session, _ = _sessao()
    seed_catalogo(session)
    registro = consultar_por_ticker(session, "mxrf11")
    assert registro.ticker == "MXRF11"
    assert registro.tipo == TipoAtivo.FII.value
    assert resolver_ticker_fii(session, ticker="mxrf11") == "MXRF11"
    session.close()


def test_fii_com_cnpj_real_via_catalogo():
    session, _ = _sessao()
    registrar_no_catalogo(
        session, "MXRF11", TipoAtivo.FII, cnpj="29.265.280/0001-40", nome_emissor="MAXI RENDA"
    )
    assert resolver_cnpj(session, "MXRF11", TipoAtivo.FII) == "29.265.280/0001-40"
    assert consultar_por_cnpj(session, "29265280000140").ticker == "MXRF11"
    session.close()


def test_fii_sem_cnpj_permanece_none():
    session, _ = _sessao()
    seed_catalogo(session)
    assert consultar_por_ticker(session, "MXRF11").cnpj is None
    assert resolver_cnpj(session, "MXRF11", TipoAtivo.FII) is None
    session.close()


def test_ticker_resolve_ativo_correto():
    session, _ = _sessao()
    garantir_ativo(session, "MXRF11", TipoAtivo.FII)
    garantir_ativo(session, "GARE11", TipoAtivo.FII)
    session.commit()
    ativo = session.query(Ativo).filter(Ativo.ticker == "MXRF11").one()
    assert ativo.ticker == "MXRF11"
    assert ativo.tipo == TipoAtivo.FII
    assert session.query(Ativo).filter(Ativo.ticker == "GARE11").one().ticker == "GARE11"
    session.close()


def test_cnpj_resolve_ativo_correto():
    session, _ = _sessao()
    registrar_no_catalogo(session, "MXRF11", TipoAtivo.FII, cnpj="29.265.280/0001-40")
    garantir_ativo(session, "MXRF11", TipoAtivo.FII, cnpj="29.265.280/0001-40")
    garantir_ativo(session, "GARE11", TipoAtivo.FII)
    session.commit()
    assert resolver_ticker_fii(session, cnpj="29.265.280/0001-40") == "MXRF11"
    assert consultar_por_cnpj(session, "29.265.280/0001-40").ticker == "MXRF11"
    session.close()


def test_nenhum_pendente_criado_no_espelhamento_nem_catalogo():
    session, _ = _sessao()
    ativo, _, status = espelhar_ativo(session, "MXRF11", TipoAtivo.FII)
    assert status == STATUS_CRIADO
    assert ativo.cnpj is None
    registro = registrar_no_catalogo(session, "ZZZX11", TipoAtivo.FII, cnpj="PENDENTE-ZZZX11")
    assert registro.cnpj is None
    for linha in session.query(Ativo).all() + session.query(AtivoCatalogo).all():
        assert linha.cnpj is None or not str(linha.cnpj).upper().startswith("PENDENTE-")
    session.close()


def test_banco_aceita_ativo_sem_cnpj():
    session, _ = _sessao()
    ativo = Ativo(ticker="MXRF11", cnpj=None, tipo=TipoAtivo.FII)
    session.add(ativo)
    session.commit()
    recarregado = session.query(Ativo).filter(Ativo.ticker == "MXRF11").one()
    assert recarregado.cnpj is None
    session.close()


def test_cnpj_real_continua_unique():
    session, _ = _sessao()
    session.add(Ativo(ticker="MXRF11", cnpj="29.265.280/0001-40", tipo=TipoAtivo.FII))
    session.commit()
    session.add(Ativo(ticker="GARE11", cnpj="29.265.280/0001-40", tipo=TipoAtivo.FII))
    try:
        session.commit()
        raise AssertionError("CNPJ duplicado deveria violar UNIQUE")
    except IntegrityError:
        session.rollback()
    session.close()


def test_dois_ativos_sem_cnpj_sao_aceitos():
    session, _ = _sessao()
    session.add(Ativo(ticker="MXRF11", cnpj=None, tipo=TipoAtivo.FII))
    session.add(Ativo(ticker="GARE11", cnpj=None, tipo=TipoAtivo.FII))
    session.commit()
    assert session.query(Ativo).count() == 2
    session.close()


def test_dados_existentes_nao_sao_destruidos():
    session, engine = _sessao()
    session.add(Ativo(ticker="PETR4", cnpj="33.000.167/0001-01", tipo=TipoAtivo.ACAO))
    session.add(Ativo(ticker="MXRF11", cnpj=None, tipo=TipoAtivo.FII))
    session.commit()
    from pipeline_dados.banco_dados import garantir_cnpj_nullable

    garantir_cnpj_nullable(engine)
    petr = session.query(Ativo).filter(Ativo.ticker == "PETR4").one()
    mxrf = session.query(Ativo).filter(Ativo.ticker == "MXRF11").one()
    assert petr.cnpj == "33.000.167/0001-01"
    assert mxrf.cnpj is None
    session.close()
