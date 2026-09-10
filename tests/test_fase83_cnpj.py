"""Fase 8.3: CNPJ só existe quando real (14 dígitos); ausência é None."""
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from pipeline_dados.banco_dados import Ativo, Base, TipoAtivo, garantir_cnpj_nullable
from pipeline_dados.catalogo_ativos import cnpj_real, garantir_ativo, registrar_no_catalogo, resolver_cnpj
from pipeline_dados.espelhamento_sheets import espelhar_ativo
from pipeline_dados.mapeamento_sheets import resolver_cnpj as resolver_cnpj_offline
from pipeline_dados.normalizacao import normalizar_cnpj


def _sessao():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)(), engine


def test_cnpj_com_14_digitos_e_aceito():
    assert normalizar_cnpj("33.000.167/0001-01") == "33000167000101"
    assert cnpj_real("33.000.167/0001-01") == "33.000.167/0001-01"
    assert cnpj_real("33000167000101") == "33.000.167/0001-01"
    assert len(normalizar_cnpj("29.265.280/0001-40")) == 14


def test_cnpj_invalido_vira_none():
    assert cnpj_real("123") is None
    assert cnpj_real("1234567890123") is None
    assert cnpj_real("abc") is None
    assert cnpj_real("PENDENTE-MXRF11") is None
    assert cnpj_real("MXRF11") is None
    assert cnpj_real("PETR4") is None
    assert cnpj_real("") is None
    assert cnpj_real("   ") is None


def test_ausencia_de_cnpj_e_none():
    assert cnpj_real(None) is None
    session, _ = _sessao()
    assert resolver_cnpj(session, "MXRF11", TipoAtivo.FII) is None
    assert resolver_cnpj_offline("MXRF11", TipoAtivo.FII) is None
    assert resolver_cnpj_offline("ZZZZ3", TipoAtivo.ACAO) is None
    session.close()


def test_nenhum_pendente_criado_em_garantir_ativo():
    session, _ = _sessao()
    ativo = garantir_ativo(session, "MXRF11", TipoAtivo.FII)
    session.commit()
    assert ativo.cnpj is None
    assert session.query(Ativo).one().cnpj is None
    session.close()


def test_placeholder_nao_entra_no_catalogo():
    session, _ = _sessao()
    registro = registrar_no_catalogo(session, "GARE11", "FII", cnpj="PENDENTE-GARE11")
    assert registro.cnpj is None
    session.close()


def test_espelhar_ativo_nao_inventa_cnpj():
    session, _ = _sessao()
    ativo, _, _ = espelhar_ativo(session, "GARE11", TipoAtivo.FII)
    assert ativo.cnpj is None
    session.close()


def test_schema_ativos_cnpj_nullable():
    _, engine = _sessao()
    colunas = {c["name"]: c for c in inspect(engine).get_columns("ativos")}
    assert colunas["cnpj"]["nullable"] is True


def test_migracao_converte_pendente_em_null_e_preserva_cnpj_real():
    session, engine = _sessao()
    session.add(Ativo(ticker="MXRF11", cnpj="PENDENTE-MXRF11", tipo=TipoAtivo.FII))
    session.add(Ativo(ticker="PETR4", cnpj="33.000.167/0001-01", tipo=TipoAtivo.ACAO))
    session.add(Ativo(ticker="GARE11", cnpj=None, tipo=TipoAtivo.FII))
    session.commit()

    garantir_cnpj_nullable(engine)
    session.expire_all()

    mxrf = session.query(Ativo).filter(Ativo.ticker == "MXRF11").one()
    petr = session.query(Ativo).filter(Ativo.ticker == "PETR4").one()
    gare = session.query(Ativo).filter(Ativo.ticker == "GARE11").one()
    assert mxrf.cnpj is None
    assert petr.cnpj == "33.000.167/0001-01"
    assert gare.cnpj is None
    total = session.execute(text("SELECT COUNT(*) FROM ativos")).scalar()
    assert total == 3
    session.close()


def test_espelhar_substitui_placeholder_por_cnpj_real_ou_null():
    session, _ = _sessao()
    ativo = Ativo(ticker="PETR4", cnpj="PENDENTE-PETR4", tipo=TipoAtivo.ACAO)
    session.add(ativo)
    session.flush()
    _, _, status = espelhar_ativo(session, "PETR4", TipoAtivo.ACAO)
    assert status == "ATUALIZADO"
    assert cnpj_real(ativo.cnpj) == "33.000.167/0001-01"
    session.close()
