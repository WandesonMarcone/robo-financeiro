"""Testes da modelagem do Bloco 5B (Fase 3).

Cobre: criação das tabelas via migração versionada e via ``create_all``
(caminho de produção), reversibilidade/rollback, tipos NUMERIC (não FLOAT),
constraints de unicidade, FK para ``ativos`` e relacionamentos ORM com Ativo.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.types import Integer, Numeric, String

from pipeline_dados.banco_dados import (
    Ativo,
    AtivoInquilino,
    AtivoPerfil,
    Base,
    SnapshotAcao,
    SnapshotFii,
    TipoAtivo,
)
from pipeline_dados.migracao_5b import MIGRACAO_ID, TABELAS_5B, aplicar, reverter, status

TABELAS_LEGADAS = (
    "ativos",
    "dados_financeiros_acoes",
    "dados_financeiros_fiis",
    "documentos_qualitativos",
)


@pytest.fixture()
def engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'teste_5b.db'}")

    @event.listens_for(eng, "connect")
    def _fk_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(eng, tables=[Base.metadata.tables[n] for n in TABELAS_LEGADAS])
    yield eng
    eng.dispose()


def _session(engine):
    return sessionmaker(bind=engine)()


def _todas_as_tabelas(engine) -> set[str]:
    return set(inspect(engine).get_table_names())


# ==========================================
# MIGRAÇÃO VERSIONADA: APLICAR / REVERTER
# ==========================================

def test_aplicar_cria_tabelas_5b_e_registra_versao(engine):
    assert aplicar(engine) == "aplicada"
    tabelas = _todas_as_tabelas(engine)
    for nome in TABELAS_5B:
        assert nome in tabelas
    assert status(engine)["aplicada"] is True


def test_aplicar_nao_toca_tabelas_existentes(engine):
    aplicar(engine)
    tabelas = _todas_as_tabelas(engine)
    for nome in TABELAS_LEGADAS:
        assert nome in tabelas


def test_aplicar_idempotente(engine):
    assert aplicar(engine) == "aplicada"
    assert aplicar(engine) == "ja_aplicada"
    tabelas = _todas_as_tabelas(engine)
    assert sum(1 for t in TABELAS_5B if t in tabelas) == len(TABELAS_5B)


def test_reverter_remove_tabelas_e_versao(engine):
    aplicar(engine)
    assert reverter(engine) == "revertida"
    tabelas = _todas_as_tabelas(engine)
    for nome in TABELAS_5B:
        assert nome not in tabelas
    assert status(engine)["aplicada"] is False
    for nome in TABELAS_LEGADAS:
        assert nome in tabelas


def test_reverter_sem_aplicar_nao_gera_erro(engine):
    assert reverter(engine) == "nao_aplicada"


def test_re_aplicar_apos_reverter(engine):
    aplicar(engine)
    reverter(engine)
    assert aplicar(engine) == "aplicada"
    assert status(engine)["aplicada"] is True


def test_create_all_tambem_cria_tabelas_5b(engine):
    Base.metadata.create_all(engine)
    tabelas = _todas_as_tabelas(engine)
    for nome in TABELAS_5B + TABELAS_LEGADAS:
        assert nome in tabelas


# ==========================================
# SCHEMA: COLUNAS E TIPOS
# ==========================================

def test_snapshots_usam_numeric_nao_float(engine):
    aplicar(engine)
    insp = inspect(engine)
    for tabela, campos in (
        ("snapshots_fiis", ["preco", "pvp", "dy", "vpa", "liquidez", "lucro_12m", "dividendo_mensal"]),
        ("snapshots_acoes", ["preco", "pl", "pvp", "roe", "marg_bruta", "valor_mercado", "peg_ratio"]),
    ):
        colunas = {c["name"]: c["type"] for c in insp.get_columns(tabela)}
        for campo in campos:
            assert isinstance(colunas[campo], Numeric), f"{tabela}.{campo} deveria ser NUMERIC"
            assert colunas[campo].precision is not None


def test_ativo_perfil_tem_chaves_esperadas(engine):
    aplicar(engine)
    colunas = {c["name"]: c["type"] for c in inspect(engine).get_columns("ativos_perfil")}
    assert isinstance(colunas["ativo_id"], Integer)
    assert isinstance(colunas["setor"], String)
    assert isinstance(colunas["tipo_fii"], String)


def test_inquilinos_tem_nome_e_participacao(engine):
    aplicar(engine)
    colunas = {c["name"]: c["type"] for c in inspect(engine).get_columns("ativos_inquilinos")}
    assert isinstance(colunas["nome"], String)
    assert isinstance(colunas["participacao"], Numeric)


def test_snapshots_tem_metadados_de_coleta(engine):
    aplicar(engine)
    for tabela in ("snapshots_fiis", "snapshots_acoes"):
        colunas = {c["name"] for c in inspect(engine).get_columns(tabela)}
        for campo in ("data_referencia", "data_coleta", "fonte", "url_origem"):
            assert campo in colunas


# ==========================================
# CONSTRAINTS: UNICIDADE E FK
# ==========================================

def test_unicidade_snapshot_fii(engine):
    aplicar(engine)
    sess = _session(engine)
    ativo = Ativo(ticker="MXRF11", cnpj="PENDENTE-MXRF11", tipo=TipoAtivo.FII)
    sess.add(ativo)
    sess.flush()
    sess.add(SnapshotFii(ativo_id=ativo.id, data_referencia=date(2026, 8, 1), preco=Decimal("9.87")))
    sess.add(SnapshotFii(ativo_id=ativo.id, data_referencia=date(2026, 8, 1), preco=Decimal("10.00")))
    with pytest.raises(IntegrityError):
        sess.commit()
    sess.rollback()
    sess.close()


def test_unicidade_snapshot_acao(engine):
    aplicar(engine)
    sess = _session(engine)
    ativo = Ativo(ticker="PETR4", cnpj="33.000.167/0001-01", tipo=TipoAtivo.ACAO)
    sess.add(ativo)
    sess.flush()
    sess.add(SnapshotAcao(ativo_id=ativo.id, data_referencia=date(2026, 8, 1), preco=Decimal("37.52")))
    sess.add(SnapshotAcao(ativo_id=ativo.id, data_referencia=date(2026, 8, 1), preco=Decimal("38.00")))
    with pytest.raises(IntegrityError):
        sess.commit()
    sess.rollback()
    sess.close()


def test_perfil_e_1para1(engine):
    aplicar(engine)
    sess = _session(engine)
    ativo = Ativo(ticker="GARE11", cnpj="PENDENTE-GARE11", tipo=TipoAtivo.FII)
    sess.add(ativo)
    sess.flush()
    sess.add(AtivoPerfil(ativo_id=ativo.id, setor="Logística"))
    sess.add(AtivoPerfil(ativo_id=ativo.id, setor="Shoppings"))
    with pytest.raises(IntegrityError):
        sess.commit()
    sess.rollback()
    sess.close()


def test_unicidade_inquilino_por_periodo(engine):
    aplicar(engine)
    sess = _session(engine)
    ativo = Ativo(ticker="GARE11", cnpj="PENDENTE-GARE11", tipo=TipoAtivo.FII)
    sess.add(ativo)
    sess.flush()
    ref = date(2026, 7, 31)
    sess.add(AtivoInquilino(ativo_id=ativo.id, nome="Inquilino A", participacao=Decimal("0.5"), data_referencia=ref))
    sess.add(AtivoInquilino(ativo_id=ativo.id, nome="Inquilino A", participacao=Decimal("0.6"), data_referencia=ref))
    with pytest.raises(IntegrityError):
        sess.commit()
    sess.rollback()
    sess.close()


def test_inquilinos_periodos_diferentes_sao_aceitos(engine):
    aplicar(engine)
    sess = _session(engine)
    ativo = Ativo(ticker="GARE11", cnpj="PENDENTE-GARE11", tipo=TipoAtivo.FII)
    sess.add(ativo)
    sess.flush()
    sess.add(AtivoInquilino(ativo_id=ativo.id, nome="Inquilino A", participacao=Decimal("0.5"), data_referencia=date(2026, 6, 30)))
    sess.add(AtivoInquilino(ativo_id=ativo.id, nome="Inquilino A", participacao=Decimal("0.6"), data_referencia=date(2026, 7, 31)))
    sess.commit()
    assert sess.query(AtivoInquilino).count() == 2
    sess.close()


def test_fk_exige_ativo_existente(engine):
    aplicar(engine)
    sess = _session(engine)
    sess.add(SnapshotFii(ativo_id=9999, data_referencia=date(2026, 8, 1), preco=Decimal("9.87")))
    with pytest.raises(IntegrityError):
        sess.commit()
    sess.rollback()
    sess.close()


def test_foreign_key_aponta_para_ativos(engine):
    aplicar(engine)
    insp = inspect(engine)
    for tabela in TABELAS_5B:
        fks = insp.get_foreign_keys(tabela)
        assert fks, f"{tabela} deveria ter FK para ativos"
        assert fks[0]["referred_table"] == "ativos"


def test_unicidades_declaradas_no_schema(engine):
    aplicar(engine)
    insp = inspect(engine)
    uq_fiis = {u["name"]: u["column_names"] for u in insp.get_unique_constraints("snapshots_fiis")}
    uq_acoes = {u["name"]: u["column_names"] for u in insp.get_unique_constraints("snapshots_acoes")}
    uq_perfil = {u["name"]: u["column_names"] for u in insp.get_unique_constraints("ativos_perfil")}
    assert uq_fiis["uix_snapshots_fiis"] == ["ativo_id", "data_referencia"]
    assert uq_acoes["uix_snapshots_acoes"] == ["ativo_id", "data_referencia"]
    assert uq_perfil["uix_ativos_perfil_ativo"] == ["ativo_id"]


def test_constraints_legadas_preservadas(engine):
    aplicar(engine)
    insp = inspect(engine)
    nomes = {
        u["name"]
        for tabela in ("dados_financeiros_acoes", "dados_financeiros_fiis", "documentos_qualitativos")
        for u in insp.get_unique_constraints(tabela)
    }
    assert {"uix_dados_acoes", "uix_dados_fiis", "uix_docs_url"} <= nomes


# ==========================================
# RELACIONAMENTO ORM COM ATIVO
# ==========================================

def test_relacionamentos_orm_retornam_filhos(engine):
    aplicar(engine)
    sess = _session(engine)
    ativo = Ativo(ticker="GARE11", cnpj="PENDENTE-GARE11", tipo=TipoAtivo.FII)
    sess.add(ativo)
    sess.flush()
    sess.add(AtivoPerfil(ativo_id=ativo.id, setor="Logística", tipo_fii="Tijolo"))
    sess.add(SnapshotFii(ativo_id=ativo.id, data_referencia=date(2026, 8, 1), preco=Decimal("12.30")))
    sess.add(AtivoInquilino(ativo_id=ativo.id, nome="Inquilino A", participacao=Decimal("0.5")))
    sess.commit()

    recarregado = sess.query(Ativo).filter(Ativo.ticker == "GARE11").one()
    assert recarregado.perfil.setor == "Logística"
    assert recarregado.perfil.tipo_fii == "Tijolo"
    assert recarregado.snapshots_fiis[0].preco == Decimal("12.30")
    assert recarregado.inquilinos[0].nome == "Inquilino A"
    sess.close()


def test_valores_numeric_sao_decimal(engine):
    aplicar(engine)
    sess = _session(engine)
    ativo = Ativo(ticker="PETR4", cnpj="33.000.167/0001-01", tipo=TipoAtivo.ACAO)
    sess.add(ativo)
    sess.flush()
    sess.add(SnapshotAcao(ativo_id=ativo.id, data_referencia=date(2026, 8, 1), pl=Decimal("4.5"), roe=Decimal("0.18")))
    sess.commit()
    snap = sess.query(SnapshotAcao).one()
    assert isinstance(snap.pl, Decimal)
    assert snap.pl == Decimal("4.5")
    sess.close()


def test_deletar_ativo_remove_filhos_5b(engine):
    aplicar(engine)
    sess = _session(engine)
    ativo = Ativo(ticker="MXRF11", cnpj="PENDENTE-MXRF11", tipo=TipoAtivo.FII)
    sess.add(ativo)
    sess.flush()
    sess.add(AtivoPerfil(ativo_id=ativo.id, setor="Papel"))
    sess.add(SnapshotFii(ativo_id=ativo.id, data_referencia=date(2026, 8, 1)))
    sess.commit()

    sess.delete(ativo)
    sess.commit()
    assert sess.query(AtivoPerfil).count() == 0
    assert sess.query(SnapshotFii).count() == 0
    assert sess.query(Ativo).count() == 0
    sess.close()


def test_versao_registrada_na_tabela_schema_migrations(engine):
    aplicar(engine)
    from sqlalchemy import text

    with engine.connect() as conn:
        versoes = [row[0] for row in conn.execute(text("SELECT version FROM schema_migrations"))]
    assert MIGRACAO_ID in versoes
    with engine.connect() as conn:
        apagados = conn.execute(
            text("SELECT COUNT(*) FROM schema_migrations WHERE version = :v"),
            {"v": MIGRACAO_ID},
        ).scalar()
    assert apagados == 1
