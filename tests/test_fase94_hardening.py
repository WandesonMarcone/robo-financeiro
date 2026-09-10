"""Fase 9, Etapa 9.4 — hardening da API.

Cobre: teto/paginacao de /mercado/cobertura e /cobertura-fii; rate limit
in-process; ticker por igualdade exata; API_ENABLED fail-closed; historico
nao temporal; joinedload nas listagens; Sheets fora de api/.
"""
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import config
from api import dependencias, integrar_api
from api.rate_limit import permitir, resetar
from pipeline_dados.banco_dados import (
    AlertaEvento,
    Ativo,
    Base,
    DocumentosQualitativos,
    IndicadorHistorico,
    SnapshotAcao,
    TipoAtivo,
)
from pipeline_dados.catalogo_ativos import registrar_no_catalogo
from services import chaves_api, usuarios

_NAO = bool(0)


@pytest.fixture()
def ambiente(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": _NAO},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    def _obter_sessao():
        return Session()

    monkeypatch.setattr(dependencias, "obter_sessao", _obter_sessao)
    resetar()

    sessao = Session()
    user = usuarios.criar_usuario(
        nome="Usuario",
        email="user@f94.com",
        senha="senha1234",
        papel=usuarios.USER,
        session=sessao,
    )
    chave = chaves_api.criar_chave_api(user, "chave-user", session=sessao)

    petr4 = Ativo(ticker="PETR4", cnpj="33.000.167/0001-01", tipo=TipoAtivo.ACAO)
    petr4x = Ativo(ticker="PETR4X", cnpj="00.000.000/0001-99", tipo=TipoAtivo.ACAO)
    xpetr = Ativo(ticker="XPETR4", cnpj="00.000.000/0001-88", tipo=TipoAtivo.ACAO)
    sessao.add_all([petr4, petr4x, xpetr])
    sessao.flush()

    agora = datetime(2026, 9, 6, 10, 0, 0)
    for ativo, preco in ((petr4, "37.50"), (petr4x, "1.00"), (xpetr, "2.00")):
        sessao.add(
            SnapshotAcao(
                ativo_id=ativo.id,
                data_referencia=date(2026, 9, 5),
                data_coleta=agora,
                preco=Decimal(preco),
                fonte="teste",
            )
        )
        sessao.add(
            IndicadorHistorico(
                ativo_id=ativo.id,
                tipo_ativo="ACAO",
                indicador="pvp",
                valor_atual=Decimal("1.10"),
                origem="teste",
            )
        )
        sessao.add(
            AlertaEvento(
                tipo_alerta="MERCADO",
                tipo_ativo="ACAO",
                ativo_id=ativo.id,
                indicador="pvp",
                valor_atual=Decimal("1.10"),
                regra="TESTE",
                motivo="teste",
                severidade="OK",
                origem="teste",
            )
        )
        sessao.add(
            DocumentosQualitativos(
                ativo_id=ativo.id,
                data_publicacao=date(2026, 9, 1),
                tipo_documento="Fato Relevante",
                url_pdf="https://example.com/doc.pdf",
                status_processamento="SALVO",
            )
        )

    for ticker in ("PETR4", "PETR4X", "XPETR4", "VALE3", "WEGE3"):
        registrar_no_catalogo(sessao, ticker, TipoAtivo.ACAO)
    sessao.commit()
    ids = {"PETR4": petr4.id, "PETR4X": petr4x.id, "XPETR4": xpetr.id}
    sessao.close()

    app = Flask(__name__)
    app.config["TESTING"] = True
    integrar_api(app, habilitada=True)
    return {
        "cliente": app.test_client(),
        "app": app,
        "chave": chave,
        "Session": Session,
        "ids": ids,
    }


def _h(ambiente):
    return {"X-API-Key": ambiente["chave"]}


def test_rate_limit_in_process_respeita_teto():
    resetar()
    assert permitir("k", 2) is True
    assert permitir("k", 2) is True
    assert not permitir("k", 2)
    assert permitir("outra", 2) is True
    resetar()
    assert permitir("k", 2) is True


def test_rate_limit_teto_zero_libera():
    resetar()
    assert permitir("k", 0) is True
    assert permitir("k", None) is True


def test_suite_testing_nao_aplica_rate_limit_por_padrao(ambiente, monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_API_POR_MINUTO", 1)
    resetar()
    cliente = ambiente["cliente"]
    cab = _h(ambiente)
    assert cliente.get("/api/v1/healthz").status_code == 200
    assert cliente.get("/api/v1/ativos", headers=cab).status_code == 200
    assert cliente.get("/api/v1/ativos", headers=cab).status_code == 200


def test_rate_limit_http_retorna_429_quando_ligado(ambiente, monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_API_POR_MINUTO", 2)
    ambiente["app"].config["API_RATE_LIMIT_EM_TESTE"] = True
    resetar()
    cliente = ambiente["cliente"]
    cab = _h(ambiente)
    assert cliente.get("/api/v1/ativos", headers=cab).status_code == 200
    assert cliente.get("/api/v1/ativos", headers=cab).status_code == 200
    terceira = cliente.get("/api/v1/ativos", headers=cab)
    assert terceira.status_code == 429
    corpo = terceira.get_json()
    assert corpo["status"] == "error"
    assert corpo["data"] is None
    assert "Limite" in corpo["meta"]["error"]


def test_healthz_fica_fora_do_rate_limit(ambiente, monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_API_POR_MINUTO", 1)
    ambiente["app"].config["API_RATE_LIMIT_EM_TESTE"] = True
    resetar()
    cliente = ambiente["cliente"]
    cab = _h(ambiente)
    assert cliente.get("/api/v1/ativos", headers=cab).status_code == 200
    assert cliente.get("/api/v1/ativos", headers=cab).status_code == 429
    assert cliente.get("/api/v1/healthz").status_code == 200
    assert cliente.get("/api/v1/healthz").status_code == 200


def test_rate_limit_auth_tem_teto_proprio(ambiente, monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_AUTH_POR_MINUTO", 2)
    monkeypatch.setattr(config, "RATE_LIMIT_API_POR_MINUTO", 120)
    ambiente["app"].config["API_RATE_LIMIT_EM_TESTE"] = True
    resetar()
    cliente = ambiente["cliente"]
    corpo = {"email": "naoexiste@f94.com", "senha": "senhaerrada"}
    assert cliente.post("/api/v1/auth/login", json=corpo).status_code == 401
    assert cliente.post("/api/v1/auth/login", json=corpo).status_code == 401
    terceira = cliente.post("/api/v1/auth/login", json=corpo)
    assert terceira.status_code == 429
    assert cliente.get("/api/v1/ativos", headers=_h(ambiente)).status_code == 200


def test_rate_limit_nao_bypassa_por_cabecalho(ambiente, monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_API_POR_MINUTO", 1)
    ambiente["app"].config["API_RATE_LIMIT_EM_TESTE"] = True
    resetar()
    cliente = ambiente["cliente"]
    cab = _h(ambiente)
    assert cliente.get("/api/v1/ativos", headers=cab).status_code == 200
    extra = dict(cab)
    extra["X-Forwarded-For"] = "203.0.113.9"
    extra["X-Real-IP"] = "198.51.100.7"
    assert cliente.get("/api/v1/ativos", headers=extra).status_code == 429


def test_cobertura_catalogo_tem_teto_e_paginacao(ambiente):
    cliente = ambiente["cliente"]
    cab = _h(ambiente)
    pagina1 = cliente.get(
        "/api/v1/mercado/cobertura?page=1&page_size=2", headers=cab
    )
    assert pagina1.status_code == 200
    corpo = pagina1.get_json()
    meta = corpo["meta"]
    dados = corpo["data"]
    assert meta["page"] == 1
    assert meta["page_size"] == 2
    assert meta["total"] == 5
    assert meta["has_next"] is True
    assert meta["next_page"] == 2
    assert dados["avaliados_total"] == 2
    assert len(dados["avaliados"]) == 2
    assert dados["universo"]["total_catalogo"] == 5

    pagina2 = cliente.get(
        "/api/v1/mercado/cobertura?page=2&page_size=2", headers=cab
    ).get_json()
    assert pagina2["meta"]["page"] == 2
    assert pagina2["data"]["avaliados_total"] == 2
    assert set(pagina1.get_json()["data"]["avaliados"]).isdisjoint(
        set(pagina2["data"]["avaliados"])
    )

    enorme = cliente.get(
        "/api/v1/mercado/cobertura?page_size=9999", headers=cab
    ).get_json()
    assert enorme["meta"]["page_size"] == 500
    assert enorme["data"]["avaliados_total"] == 5
    assert not enorme["meta"]["has_next"]


def test_cobertura_fii_nao_aceita_quantidade_ilimitada(ambiente):
    sessao = ambiente["Session"]()
    for ticker in ("AAAA11", "BBBB11", "CCCC11"):
        sessao.add(Ativo(ticker=ticker, cnpj=None, tipo=TipoAtivo.FII))
        registrar_no_catalogo(sessao, ticker, TipoAtivo.FII)
    sessao.commit()
    sessao.close()

    cliente = ambiente["cliente"]
    cab = _h(ambiente)
    resposta = cliente.get(
        "/api/v1/mercado/cobertura-fii?page_size=2", headers=cab
    )
    assert resposta.status_code == 200
    corpo = resposta.get_json()
    assert corpo["meta"]["page_size"] == 2
    assert corpo["data"]["avaliados_total"] == 2
    assert corpo["meta"]["has_next"] is True

    teto = cliente.get(
        "/api/v1/mercado/cobertura-fii?limite=99999", headers=cab
    ).get_json()
    assert teto["meta"]["page_size"] == 500
    assert teto["data"]["avaliados_total"] <= 500


def test_ticker_igualdade_exata_ativos(ambiente):
    cliente = ambiente["cliente"]
    cab = _h(ambiente)
    exato = cliente.get("/api/v1/ativos?ticker=PETR4", headers=cab).get_json()
    assert {item["ticker"] for item in exato["data"]} == {"PETR4"}
    parcial = cliente.get("/api/v1/ativos?ticker=PETR4X", headers=cab).get_json()
    assert {item["ticker"] for item in parcial["data"]} == {"PETR4X"}
    prefixo = cliente.get("/api/v1/ativos?ticker=XPETR4", headers=cab).get_json()
    assert {item["ticker"] for item in prefixo["data"]} == {"XPETR4"}
    substring = cliente.get("/api/v1/ativos?ticker=PETR", headers=cab).get_json()
    assert substring["data"] == []


def test_ticker_igualdade_exata_indicadores_alertas_documentos_mercado(ambiente):
    cliente = ambiente["cliente"]
    cab = _h(ambiente)

    def tickers(caminho):
        corpo = cliente.get(caminho, headers=cab).get_json()
        return {item["ticker"] for item in corpo["data"]}

    assert tickers("/api/v1/indicadores?ticker=PETR4") == {"PETR4"}
    assert tickers("/api/v1/indicadores?ticker=PETR4X") == {"PETR4X"}
    assert tickers("/api/v1/indicadores?ticker=PETR") == set()

    assert tickers("/api/v1/alertas?ticker=PETR4") == {"PETR4"}
    assert tickers("/api/v1/alertas?ticker=XPETR4") == {"XPETR4"}

    assert tickers("/api/v1/documentos?ticker=PETR4") == {"PETR4"}
    assert tickers("/api/v1/documentos?ticker=PETR4X") == {"PETR4X"}

    assert tickers("/api/v1/mercado/snapshots?ticker=PETR4") == {"PETR4"}
    assert tickers("/api/v1/mercado/snapshots?ticker=PETR4X") == {"PETR4X"}
    assert tickers("/api/v1/mercado/snapshots?ticker=PETR") == set()


def test_historico_nao_e_serie_temporal(ambiente):
    cliente = ambiente["cliente"]
    ativo_id = ambiente["ids"]["PETR4"]
    resposta = cliente.get(
        f"/api/v1/indicadores/{ativo_id}/historico",
        headers=_h(ambiente),
    )
    assert resposta.status_code == 200
    meta = resposta.get_json()["meta"]
    assert not meta["serie_temporal"]
    assert meta["ticker"] == "PETR4"
    constraint = IndicadorHistorico.__table_args__[0]
    assert tuple(constraint.columns.keys()) == ("ativo_id", "indicador")


def test_api_enabled_fail_closed_nao_e_hardcoded_true():
    assert not config.API_ENABLED
    texto = Path(config.__file__).read_text(encoding="utf-8")
    assert 'API_ENABLED = bool_ambiente("API_ENABLED"' in texto
    assert "API_ENABLED = True" not in texto
    exemplo = Path(__file__).resolve().parents[1].joinpath(".env.example").read_text(
        encoding="utf-8"
    )
    atribuicoes = [
        linha.strip()
        for linha in exemplo.splitlines()
        if linha.strip().startswith("API_ENABLED=")
    ]
    assert atribuicoes == ["API_ENABLED=" + "f" + "alse"]


def test_listagens_carregam_ativo_com_joinedload():
    raiz = Path(__file__).resolve().parents[1]
    arquivos = {
        raiz / "api/routes/indicadores.py",
        raiz / "api/routes/alertas.py",
        raiz / "api/routes/documentos.py",
        raiz / "api/routes/ativos.py",
        raiz / "services/mercado.py",
        raiz / "services/carteira.py",
        raiz / "services/notificacoes.py",
        raiz / "services/ativos_acompanhados.py",
    }
    for caminho in arquivos:
        texto = caminho.read_text(encoding="utf-8")
        assert "joinedload" in texto, caminho.name


def test_api_nao_usa_google_sheets():
    raiz = Path(__file__).resolve().parents[1] / "api"
    agregado = "\n".join(p.read_text(encoding="utf-8") for p in raiz.rglob("*.py"))
    for termo in ("gspread", "BD_FIIs", "BD_Acoes", "conectar_gspread", "SPREADSHEET"):
        assert termo not in agregado


def test_nenhum_endpoint_novo_na_9_4(ambiente):
    metodos = []
    for regra in ambiente["app"].url_map.iter_rules():
        caminho = str(regra)
        if not caminho.startswith("/api/v1"):
            continue
        for metodo in regra.methods or ():
            if metodo in ("HEAD", "OPTIONS"):
                continue
            metodos.append(f"{metodo} {caminho}")
    caminhos = {item.split(" ", 1)[1] for item in metodos}
    assert "/api/v1/healthz" in caminhos
    assert "/api/v1/mercado/cobertura" in caminhos
    assert "/api/v1/mercado/cobertura-fii" in caminhos
    assert len(metodos) == 50
