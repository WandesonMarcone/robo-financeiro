"""Testes da camada centralizada de acesso ao banco (Fase 7, Etapa 7.4).

Cobrem a nova abstração ``services/db``: a fábrica canônica de sessões
(``SessionDB``/``criar_sessao``), o contexto recomendado ``sessao_db``
(reuso da sessão do chamador vs sessão própria com close/rollback) e a
delegação do legado (``atualizador_documentos`` passa a reexportar o mesmo
``SessionDB``/``engine``). Não testam fluxos de negócio — apenas a base de
conexão dos componentes novos do Core.
"""
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from pipeline_dados.banco_dados import AtivoCatalogo, Base
from services import db


@pytest.fixture()
def sessao_memoria():
    """Sessão isolada em SQLite em memória (padrão dos testes do projeto)."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessao = sessionmaker(bind=engine)()
    yield sessao
    sessao.close()


# ==========================================
# ENGINE CENTRAL E FÁBRICA DE SESSÕES
# ==========================================

def test_sessiondb_retorna_sessao_do_engine_central():
    sessao = db.SessionDB()
    try:
        assert sessao.get_bind() is db.engine
    finally:
        sessao.close()


def test_criar_sessao_retorna_sessao_e_pode_ser_fechada():
    sessao = db.criar_sessao()
    fechada = {"close": False}
    close_original = sessao.close

    def _close_rastreado():
        fechada["close"] = True
        return close_original()

    sessao.close = _close_rastreado
    sessao.close()
    assert fechada["close"] is True


def test_engine_central_mantem_pool_para_neon():
    pool = db.engine.pool
    assert pool._pre_ping is True
    assert pool._recycle == 1800


# ==========================================
# CONTEXTO RECOMENDADO (sessao_db)
# ==========================================

def _close_rastreado(sessao):
    """Envolve ``sessao.close`` registrando a chamada num dicionário."""
    rastreado = {"close": False}
    close_original = sessao.close

    def _wrapper():
        rastreado["close"] = True
        return close_original()

    sessao.close = _wrapper
    return rastreado


def test_sessao_db_reutiliza_sessao_informada_e_nao_fecha(sessao_memoria):
    rastreado = _close_rastreado(sessao_memoria)
    with db.sessao_db(sessao_memoria) as s:
        assert s is sessao_memoria
    assert rastreado["close"] is False


def test_sessao_db_propria_fecha_ao_final(monkeypatch):
    sessao = db.criar_sessao()
    rastreado = _close_rastreado(sessao)
    monkeypatch.setattr(db, "criar_sessao", lambda: sessao)
    with db.sessao_db() as s:
        assert s is sessao
    assert rastreado["close"] is True


def test_sessao_db_propria_faz_rollback_e_fecha_em_erro(monkeypatch):
    db.criar_tabelas()
    sessao = db.criar_sessao()
    rastreado = _close_rastreado(sessao)
    monkeypatch.setattr(db, "criar_sessao", lambda: sessao)
    with pytest.raises(RuntimeError):
        with db.sessao_db() as s:
            s.add(AtivoCatalogo(ticker="ZZZZ-ROLLBACK", tipo="ACAO"))
            raise RuntimeError("falha simulada")
    assert rastreado["close"] is True
    with db.sessao_db() as s:
        assert (
            s.query(AtivoCatalogo)
            .filter(AtivoCatalogo.ticker == "ZZZZ-ROLLBACK")
            .first()
            is None
        )


def test_sessao_db_propria_nao_commita_automaticamente():
    db.criar_tabelas()
    with db.sessao_db() as s:
        s.add(AtivoCatalogo(ticker="ZZZZ-SEMCOMMIT", tipo="ACAO"))
    with db.sessao_db() as s:
        assert (
            s.query(AtivoCatalogo)
            .filter(AtivoCatalogo.ticker == "ZZZZ-SEMCOMMIT")
            .first()
            is None
        )


def test_criar_tabelas_idempotente():
    db.criar_tabelas()
    db.criar_tabelas()
    tabelas = inspect(db.engine).get_table_names()
    assert "ativos" in tabelas
    assert "ativos_catalogo" in tabelas


# ==========================================
# COMPATIBILIDADE COM O LEGADO
# ==========================================

def test_atualizador_documentos_reexporta_o_mesmo_sessiondb_e_engine():
    from atualizador_documentos import SessionDB as SessionDB_legado
    from atualizador_documentos import engine as engine_legado

    assert SessionDB_legado is db.SessionDB
    assert engine_legado is db.engine
