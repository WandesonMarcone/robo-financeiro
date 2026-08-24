from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline_dados.banco_dados import Ativo, Base, DocumentosQualitativos, TipoAtivo
from pipeline_dados.deduplicacao import (
    STATUS_DUPLICADO,
    buscar_original_por_hash,
    calcular_hash_sha256,
    marcar_duplicado,
    verificar_duplicidade,
)


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessao = sessionmaker(bind=engine)()
    yield sessao
    sessao.close()


def criar_ativo(sessao, ticker="TEST11", cnpj="00.000.000/0000-00"):
    ativo = Ativo(ticker=ticker, cnpj=cnpj, tipo=TipoAtivo.FII)
    sessao.add(ativo)
    sessao.flush()
    return ativo


def criar_documento(sessao, hash_sha256=None, id_b3="B3-1", ativo=None):
    if ativo is None:
        ativo = criar_ativo(sessao)
    doc = DocumentosQualitativos(
        ativo_id=ativo.id,
        data_publicacao=date(2024, 5, 10),
        tipo_documento="Fato Relevante",
        id_b3=id_b3,
        hash_sha256=hash_sha256,
        status_processamento="SALVO_DRIVE",
    )
    sessao.add(doc)
    sessao.flush()
    return doc


def test_hash_deterministico():
    assert calcular_hash_sha256(b"conteudo") == calcular_hash_sha256(b"conteudo")


def test_hash_diferente_para_conteudos_diferentes():
    assert calcular_hash_sha256(b"abc") != calcular_hash_sha256(b"abd")


def test_hash_conteudo_vazio_deterministico():
    assert calcular_hash_sha256(b"") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_documento_duplicado_por_conteudo_e_detectado(db_session):
    conteudo = b"%PDF-1.4 conteudo identico"
    original = criar_documento(
        db_session, hash_sha256=calcular_hash_sha256(conteudo), id_b3="B3-100"
    )

    hash_pdf, duplicado = verificar_duplicidade(db_session, conteudo)

    assert hash_pdf == original.hash_sha256
    assert duplicado is not None
    assert duplicado.id == original.id


def test_documento_diferente_nao_e_bloqueado(db_session):
    criar_documento(db_session, hash_sha256=calcular_hash_sha256(b"outro"), id_b3="B3-100")

    conteudo_novo = b"%PDF-1.4 documento diferente"
    hash_pdf, duplicado = verificar_duplicidade(db_session, conteudo_novo)

    assert duplicado is None
    assert hash_pdf == calcular_hash_sha256(conteudo_novo)


def test_duplicidade_independe_do_ticker(db_session):
    conteudo = b"%PDF-1.4 mesmo conteudo"
    original = criar_documento(db_session, hash_sha256=calcular_hash_sha256(conteudo), id_b3="B3-1")

    ativo_outro = criar_ativo(db_session, ticker="GARE11", cnpj="22.222.222/0002-22")
    doc_b = DocumentosQualitativos(
        ativo_id=ativo_outro.id,
        data_publicacao=date(2024, 5, 10),
        tipo_documento="Fato Relevante",
        id_b3="B3-2",
        status_processamento="PENDENTE",
    )
    db_session.add(doc_b)
    db_session.flush()

    hash_pdf, duplicado = verificar_duplicidade(db_session, conteudo, exceto_id=doc_b.id)

    assert duplicado is not None
    assert duplicado.id == original.id


def test_proprio_documento_nao_conta_como_duplicado(db_session):
    conteudo = b"%PDF-1.4 conteudo"
    doc = criar_documento(db_session, hash_sha256=calcular_hash_sha256(conteudo))

    _, duplicado = verificar_duplicidade(db_session, conteudo, exceto_id=doc.id)

    assert duplicado is None


def test_documento_antigo_sem_hash_nao_interfere(db_session):
    criar_documento(db_session, hash_sha256=None, id_b3="B3-200")

    conteudo = b"%PDF-1.4 conteudo novo"
    hash_pdf, duplicado = verificar_duplicidade(db_session, conteudo)

    assert duplicado is None
    assert hash_pdf == calcular_hash_sha256(conteudo)


def test_buscar_original_por_hash_nulo_retorna_none(db_session):
    assert buscar_original_por_hash(db_session, None) is None
    assert buscar_original_por_hash(db_session, "") is None


def test_marcar_duplicado_mantem_rastreabilidade(db_session):
    conteudo = b"%PDF-1.4 conteudo"
    original = criar_documento(db_session, hash_sha256=calcular_hash_sha256(conteudo), id_b3="B3-1")

    ativo_outro = criar_ativo(db_session, ticker="GARE11", cnpj="22.222.222/0002-22")
    duplicado = DocumentosQualitativos(
        ativo_id=ativo_outro.id,
        data_publicacao=date(2024, 5, 10),
        tipo_documento="Fato Relevante",
        id_b3="B3-2",
        status_processamento="PENDENTE",
    )
    db_session.add(duplicado)
    db_session.flush()

    marcar_duplicado(duplicado, original)
    db_session.commit()

    assert duplicado.status_processamento == STATUS_DUPLICADO
    assert f"#{original.id}" in duplicado.log_erro
    assert duplicado.id_b3 == "B3-2"
