"""Fase 9, Etapa 9.2 — correções da auditoria da API.

Cobre: ADMIN com alertas.consultar; /cobertura-fii limitado e serializado;
paginação real das coleções; contrato semântico 8.5 no JSON.
"""
from datetime import date, datetime
from decimal import Decimal

import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api import dependencias, integrar_api
from pipeline_dados.banco_dados import (
    Ativo,
    Base,
    DadosFinanceirosFiis,
    SnapshotFii,
    TipoAtivo,
)
from services import chaves_api, usuarios


@pytest.fixture()
def ambiente(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    def _obter_sessao():
        return Session()

    monkeypatch.setattr(dependencias, "obter_sessao", _obter_sessao)

    sessao = Session()
    admin = usuarios.criar_usuario(
        nome="Admin", email="admin@f92.com", senha="senha1234",
        papel=usuarios.ADMIN, session=sessao,
    )
    user = usuarios.criar_usuario(
        nome="Usuario", email="user@f92.com", senha="senha1234",
        papel=usuarios.USER, session=sessao,
    )
    visitor = usuarios.criar_usuario(
        nome="Visitante", email="visitor@f92.com", senha="senha1234",
        papel=usuarios.VISITOR, session=sessao,
    )
    chave_admin = chaves_api.criar_chave_api(admin, "chave-admin", session=sessao)
    chave_user = chaves_api.criar_chave_api(user, "chave-user", session=sessao)
    chave_visitor = chaves_api.criar_chave_api(visitor, "chave-visitor", session=sessao)

    for ticker in ("AAAA11", "BBBB11", "CCCC11"):
        ativo = Ativo(ticker=ticker, cnpj=None, tipo=TipoAtivo.FII)
        sessao.add(ativo)
        sessao.flush()
        sessao.add(
            SnapshotFii(
                ativo_id=ativo.id,
                data_referencia=date(2026, 8, 20),
                data_coleta=datetime(2026, 8, 20, 10, 0, 0),
                preco=Decimal("10.00") if ticker != "CCCC11" else Decimal("0"),
                dy=None,
                pvp=Decimal("1.10"),
                vpa=Decimal("9.00"),
                fonte="teste",
            )
        )
        if ticker == "AAAA11":
            sessao.add(
                DadosFinanceirosFiis(
                    ativo_id=ativo.id,
                    data_referencia=date(2026, 6, 30),
                    data_coleta=datetime(2026, 7, 1, 12, 0, 0),
                    patrimonio_liquido=Decimal("100.0"),
                    valor_patrimonial_cotas=Decimal("9.50"),
                    percentual_dividend_yield_mes=Decimal("0.01"),
                    fonte="CVM",
                    fonte_primaria="CVM",
                )
            )
    sessao.commit()
    sessao.close()

    app = Flask(__name__)
    app.config["TESTING"] = True
    integrar_api(app, habilitada=True)
    return {
        "cliente": app.test_client(),
        "admin": chave_admin,
        "user": chave_user,
        "visitor": chave_visitor,
        "Session": Session,
    }


def _h(ambiente, papel):
    return {"X-API-Key": ambiente[papel]}


def test_admin_consulta_alertas_e_visitor_nao(ambiente):
    admin = ambiente["cliente"].get("/api/v1/alertas", headers=_h(ambiente, "admin"))
    assert admin.status_code == 200
    user = ambiente["cliente"].get("/api/v1/alertas", headers=_h(ambiente, "user"))
    assert user.status_code == 200
    visitor = ambiente["cliente"].get("/api/v1/alertas", headers=_h(ambiente, "visitor"))
    assert visitor.status_code == 403


def test_cobertura_fii_e_estruturada_e_limitada(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/mercado/cobertura-fii?page_size=2",
        headers=_h(ambiente, "user"),
    )
    assert resposta.status_code == 200
    corpo = resposta.get_json()
    assert corpo["status"] == "success"
    dados = corpo["data"]
    meta = corpo["meta"]
    assert meta["page"] == 1
    assert meta["page_size"] == 2
    assert meta["total"] == 3
    assert meta["has_next"] is True
    assert meta["next_page"] == 2
    assert dados["avaliados_total"] == 2
    assert len(dados["items"]) == 2
    item = dados["items"][0]
    assert "freshness" in item
    categorias = item["freshness"]["categorias"]
    for categoria in categorias.values():
        if categoria is None:
            continue
        assert "sla" not in categoria
        assert "sla_segundos" in categoria
        if categoria.get("sla_segundos") is not None:
            assert isinstance(categoria["sla_segundos"], int)
        if categoria.get("data_referencia") is not None:
            assert isinstance(categoria["data_referencia"], str)
        if categoria.get("data_coleta") is not None:
            assert isinstance(categoria["data_coleta"], str)
    texto = resposta.get_data(as_text=True)
    assert "timedelta" not in texto
    assert "datetime.datetime" not in texto


def test_cobertura_fii_filtro_ticker(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/mercado/cobertura-fii?ticker=AAAA11",
        headers=_h(ambiente, "user"),
    )
    assert resposta.status_code == 200
    dados = resposta.get_json()["data"]
    assert dados["avaliados"] == ["AAAA11"]
    assert dados["items"][0]["ticker"] == "AAAA11"
    assert dados["por_ticker"]["AAAA11"]["campos"]["preco"]["status"] == "PREENCHIDO"


def test_paginacao_cobertura_fii_segunda_pagina(ambiente):
    pagina2 = ambiente["cliente"].get(
        "/api/v1/mercado/cobertura-fii?page=2&page_size=2",
        headers=_h(ambiente, "user"),
    ).get_json()
    assert pagina2["meta"]["page"] == 2
    assert pagina2["meta"]["has_next"] is False
    assert pagina2["data"]["avaliados_total"] == 1


def test_snapshot_preserva_zero_ausente_e_unidades(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/mercado/snapshots?ticker=CCCC11",
        headers=_h(ambiente, "user"),
    )
    assert resposta.status_code == 200
    item = resposta.get_json()["data"][0]
    assert item["preco"] == 0.0
    assert item["dy"] is None
    assert item["data_referencia"] == "2026-08-20"
    assert item["data_coleta"].startswith("2026-08-20")
    assert item["fonte"] == "teste"
    assert item["campos"]["preco"]["semantica"] == "ZERO"
    assert item["campos"]["dy"]["semantica"] == "AUSENTE"
    assert item["campos"]["preco"]["unidade"] == "R$"
    assert item["campos"]["dy"]["unidade"] == "%"
    assert item["campos"]["pvp"]["unidade"] == "x"


def test_dados_financeiros_distinguem_vpa_cvm_e_dy_mensal(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/mercado/dados-financeiros?ticker=AAAA11",
        headers=_h(ambiente, "user"),
    )
    item = resposta.get_json()["data"][0]
    assert item["valor_patrimonial_cotas"] == 9.5
    assert item["percentual_dividend_yield_mes"] == 0.01
    assert item["data_referencia"] == "2026-06-30"
    assert item["fonte"] == "CVM"
    assert "CVM" in item["proveniencia"]["valor_patrimonial_cotas"]
    assert "nao e DY 12m" in item["proveniencia"]["percentual_dividend_yield_mes"]
    assert item["campos"]["valor_patrimonial_cotas"]["semantica"] == "PRESENTE"
    assert item["campos"]["percentual_dividend_yield_mes"]["escala"] == "fracao"


def test_api_nao_usa_google_sheets():
    import api as pacote_api
    import pathlib

    textos = []
    raiz = pathlib.Path(pacote_api.__file__).parent
    for caminho in raiz.rglob("*.py"):
        textos.append(caminho.read_text(encoding="utf-8"))
    agregado = "\n".join(textos)
    for termo in ("gspread", "BD_FIIs", "BD_Acoes", "conectar_gspread", "SPREADSHEET"):
        assert termo not in agregado
