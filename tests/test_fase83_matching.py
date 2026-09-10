"""Fase 8.3: matching FII por CNPJ, ticker e nome único — sem substring ambígua."""
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline_dados.banco_dados import Ativo, Base, DocumentosQualitativos, TipoAtivo
from pipeline_dados.catalogo_ativos import (
    garantir_ativo,
    identificar_ativo_fii,
    registrar_no_catalogo,
    resolver_ticker_fii,
    seed_catalogo,
    ticker_por_nome_fii,
    ticker_token_em_nome,
)


def _sessao():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_matching_prioriza_cnpj_depois_ticker_depois_nome():
    session = _sessao()
    registrar_no_catalogo(
        session, "MXRF11", TipoAtivo.FII, cnpj="29.265.280/0001-40", nome_emissor="MAXI RENDA"
    )
    registrar_no_catalogo(
        session, "GARE11", TipoAtivo.FII, nome_emissor="GUARDIAN REAL ESTATE"
    )
    mxrf = garantir_ativo(session, "MXRF11", TipoAtivo.FII, cnpj="29.265.280/0001-40")
    gare = garantir_ativo(session, "GARE11", TipoAtivo.FII)
    session.commit()

    por_cnpj = identificar_ativo_fii(session, cnpj="29.265.280/0001-40", ticker="GARE11", nome="GUARDIAN")
    assert por_cnpj.id == mxrf.id

    por_ticker = identificar_ativo_fii(session, ticker="GARE11")
    assert por_ticker.id == gare.id

    por_nome = identificar_ativo_fii(session, nome="MAXI RENDA FUNDO DE INVESTIMENTO")
    assert por_nome.id == mxrf.id
    session.close()


def test_nomes_semelhantes_xp_kinea_btg_nao_associam_errado():
    session = _sessao()
    seed_catalogo(session)
    assert ticker_por_nome_fii("XP", session=session) is None
    assert ticker_por_nome_fii("KINEA", session=session) is None
    assert ticker_por_nome_fii("BTG", session=session) is None
    assert ticker_por_nome_fii("BTG PACTUAL", session=session) is None
    assert ticker_por_nome_fii("XP LOG", session=session) is None
    assert ticker_por_nome_fii("VINCI", session=session) is None
    assert ticker_por_nome_fii("XP MALLS", session=session) == "XPML11"
    assert ticker_por_nome_fii("KINEA RENDIMENTOS", session=session) == "KNCR11"
    assert ticker_por_nome_fii("BTG PACTUAL LOGÍSTICA", session=session) == "BTLG11"
    assert ticker_por_nome_fii("XP LOG FDO", session=session) == "XPLG11"
    assert ticker_por_nome_fii("XP LOG PRI", session=session) == "XPLY11"
    session.close()


def test_substring_ambigua_nao_resolve_silenciosamente():
    session = _sessao()
    seed_catalogo(session)
    assert ticker_por_nome_fii("FUNDO XP", session=session) is None
    assert ticker_por_nome_fii("KINEA FUNDO", session=session) is None
    assert ticker_por_nome_fii("BTG PACTUAL FUNDO IMOBILIARIO", session=session) is None
    assert resolver_ticker_fii(session, nome="RECEBIVEIS") is None
    assert resolver_ticker_fii(session, nome="") is None
    assert resolver_ticker_fii(session, nome=None) is None
    session.close()


def test_ticker_no_nome_identifica_fii_unico():
    session = _sessao()
    seed_catalogo(session)
    assert ticker_token_em_nome("MAXI RENDA FII MXRF11", session) == "MXRF11"
    assert ticker_token_em_nome("Documento XPML11 Malls", session) == "XPML11"
    assert ticker_token_em_nome("MXRF11 e GARE11 juntos", session) is None
    session.close()


def test_documento_associado_ao_fii_correto():
    session = _sessao()
    seed_catalogo(session)
    monitorados = {"MXRF11", "GARE11", "XPML11"}
    documentos = [
        {"id": "100", "nome_fundo": "MAXI RENDA FII", "data_ref": "2026-08-01", "tipo_doc": "Informe Mensal"},
        {"id": "101", "nome_fundo": "XP MALLS FDO INV IMOB", "data_ref": "2026-08-01", "tipo_doc": "Fato Relevante"},
        {"id": "102", "nome_fundo": "XP", "data_ref": "2026-08-01", "tipo_doc": "Outros"},
        {"id": "103", "nome_fundo": "KINEA", "data_ref": "2026-08-01", "tipo_doc": "Outros"},
    ]
    associados = {}
    for doc in documentos:
        ticker = resolver_ticker_fii(session, nome=doc["nome_fundo"])
        if not ticker or ticker not in monitorados:
            continue
        ativo = garantir_ativo(session, ticker, TipoAtivo.FII)
        registro = DocumentosQualitativos(
            ativo_id=ativo.id,
            id_b3=doc["id"],
            data_publicacao=date(2026, 8, 1),
            tipo_documento=doc["tipo_doc"],
            status_processamento="PENDENTE",
        )
        session.add(registro)
        associados[doc["id"]] = ticker
    session.commit()

    assert associados == {"100": "MXRF11", "101": "XPML11"}
    mxrf = session.query(Ativo).filter(Ativo.ticker == "MXRF11").one()
    xpml = session.query(Ativo).filter(Ativo.ticker == "XPML11").one()
    docs = {d.id_b3: d.ativo_id for d in session.query(DocumentosQualitativos).all()}
    assert docs["100"] == mxrf.id
    assert docs["101"] == xpml.id
    assert "102" not in docs
    assert "103" not in docs
    assert mxrf.cnpj is None
    assert xpml.cnpj is None
    session.close()


def test_identificar_nao_associa_por_substring_de_familia():
    session = _sessao()
    seed_catalogo(session)
    garantir_ativo(session, "XPML11", TipoAtivo.FII)
    garantir_ativo(session, "XPLG11", TipoAtivo.FII)
    session.commit()
    assert identificar_ativo_fii(session, nome="XP") is None
    assert identificar_ativo_fii(session, nome="XP LOG") is None
    assert identificar_ativo_fii(session, nome="XP MALLS").ticker == "XPML11"
    session.close()
