"""Testes da camada de leitura de mercado persistido (Fase 7, Etapa 7.3).

Cobre a cadeia ``fonte -> normalização -> validação -> snapshot -> PostgreSQL ->
consulta``: persistência via produtor 5C e leitura pelo serviço
(``services.mercado``), identificação do ativo (ticker/tipo), histórico
temporal, idempotência, dados ausentes preservados (``None``, nunca ``0.0``),
INVALID não persistido, dados financeiros (CVM), serialização e os endpoints
HTTP ``/api/v1/mercado/*``.
"""
from datetime import date
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
    DadosFinanceirosAcoes,
    DadosFinanceirosFiis,
    SnapshotAcao,
    SnapshotFii,
    TipoAtivo,
)
from pipeline_dados.espelhamento_mercado_5c import espelhar_mercado_acoes, espelhar_mercado_fiis
from services import chaves_api, mercado, usuarios

FII_CNPJ = "PENDENTE-MXRF11"


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessao = sessionmaker(bind=engine)()
    yield sessao
    sessao.close()


def matriz_fiis():
    cabecalho = ["Ticker", "Tipo", "Setor", "Preço", "Cotas", "P/VP", "DY", "Vacância",
                 "Imóveis", "Inquilinos", "WALT", "Alavancagem", "Liquidez",
                 "Valor Mercado", "VPA", "Lucro 12M", "Div Mensal", "Carimbo"]
    linhas = [
        ["MXRF11", "Papel", "CRI", 9.87, 500000000.0, 0.95, 0.12, 0.0, 0,
         "Não informado", "Pendente de IA", "Pendente de IA", 1500000.0,
         4800000000.0, 10.39, 576000000.0, 0.0987, "19/08 10:00"],
        ["GARE11", "Tijolo", "Logística", 12.30, 200000000.0, 0.90, 0.10, 0.05, 3,
         "Inquilino A (50%), Inquilino B (50%)", "Pendente de IA", "Pendente de IA",
         800000.0, 2400000000.0, 13.67, 240000000.0, 0.1025, "19/08 10:00"],
        ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""],
    ]
    return [cabecalho] + linhas


def matriz_acoes():
    cabecalho = ["Ticker", "Setor", "Preço", "DY", "Qtd Ações", "P/L", "P/VP", "P/Ativo",
                 "Marg. Bruta", "Marg. EBIT", "Marg. Líq", "P/EBIT", "EV/EBIT",
                 "Dív/EBIT", "Dív/Patrim", "PSR", "P/Cap.Giro", "P/At.Circ.Liq",
                 "Liq. Corr", "ROE", "ROA", "ROIC", "Reservado", "Reservado",
                 "Reservado", "CAGR 5a", "Reservado", "Liq. Média", "VPA", "LPA",
                 "PEG", "Valor Mercado", "Carimbo"]
    linhas = [
        ["PETR4", "Petróleo, Gás & Biocombustíveis", 37.52, 0.14, 12300000000.0,
         4.5, 1.2, 0.8, 0.55, 0.30, 0.12, 8.0, 5.0, 0.5, 0.8, 0.9, 1.2, 1.1, 1.5,
         0.18, 0.12, 0.16, 0, 0, 0, 0.10, 0, 85000000.0, 31.0, 8.3, 1.1,
         400000000000.0, "19/08 10:00"],
    ]
    return [cabecalho] + linhas


def _criar_ativo(sessao, ticker, tipo):
    ativo = Ativo(ticker=ticker, cnpj=f"PENDENTE-{ticker}", tipo=tipo)
    sessao.add(ativo)
    sessao.flush()
    return ativo


# ==========================================
# PERSISTÊNCIA (produtor 5C) + LEITURA PELO SERVIÇO
# ==========================================

def test_persistencia_via_produtor_e_leitura_pelo_servico(db_session):
    espelhar_mercado_fiis(db_session, matriz_fiis(), data_referencia=date(2026, 8, 20))
    registros = mercado.obter_snapshots(session=db_session)
    assert len(registros) == 2
    assert {r.ativo.ticker for r in registros} == {"MXRF11", "GARE11"}
    assert all(isinstance(r, SnapshotFii) for r in registros)


def test_leitura_mais_recente_do_fluxo_existente(db_session):
    espelhar_mercado_fiis(db_session, matriz_fiis(), data_referencia=date(2026, 8, 19))
    espelhar_mercado_fiis(db_session, matriz_fiis(), data_referencia=date(2026, 8, 20))
    ultimo = mercado.obter_snapshot_mais_recente(ticker="MXRF11", session=db_session)
    assert ultimo is not None
    assert ultimo.data_referencia == date(2026, 8, 20)
    assert ultimo.ativo.ticker == "MXRF11"


def test_acoes_tambem_sao_lidas_pelo_servico(db_session):
    espelhar_mercado_acoes(db_session, matriz_acoes(), data_referencia=date(2026, 8, 20))
    registros = mercado.obter_snapshots(tipo="ACAO", session=db_session)
    assert len(registros) == 1
    assert isinstance(registros[0], SnapshotAcao)
    assert registros[0].ativo.ticker == "PETR4"
    assert registros[0].preco == Decimal("37.52")


# ==========================================
# IDENTIFICAÇÃO DO ATIVO / ISOLAMENTO
# ==========================================

def test_identificacao_por_ticker_e_tipo(db_session):
    espelhar_mercado_fiis(db_session, matriz_fiis(), data_referencia=date(2026, 8, 20))
    espelhar_mercado_acoes(db_session, matriz_acoes(), data_referencia=date(2026, 8, 20))

    mxrf = mercado.obter_snapshots(ticker="mxrf11", session=db_session)
    assert len(mxrf) == 1 and mxrf[0].ativo.ticker == "MXRF11"

    fiis = mercado.obter_snapshots(tipo="FII", session=db_session)
    assert len(fiis) == 2 and all(isinstance(r, SnapshotFii) for r in fiis)

    acoes = mercado.obter_snapshots(tipo="ACAO", session=db_session)
    assert len(acoes) == 1 and isinstance(acoes[0], SnapshotAcao)

    por_id = mercado.obter_snapshots(ativo_id=mxrf[0].ativo_id, session=db_session)
    assert len(por_id) == 1 and por_id[0].ativo.ticker == "MXRF11"


def test_isolamento_entre_ativos(db_session):
    espelhar_mercado_fiis(db_session, matriz_fiis(), data_referencia=date(2026, 8, 20))
    so_mxrf = mercado.obter_snapshots(ticker="MXRF11", session=db_session)
    assert {r.ativo.ticker for r in so_mxrf} == {"MXRF11"}
    so_gare = mercado.obter_snapshots(ticker="GARE11", session=db_session)
    assert {r.ativo.ticker for r in so_gare} == {"GARE11"}


# ==========================================
# HISTÓRICO TEMPORAL / IDEMPOTÊNCIA
# ==========================================

def test_historico_temporal_ordenado_decrescente(db_session):
    _criar_ativo(db_session, "MXRF11", TipoAtivo.FII)
    for dia in (date(2026, 8, 18), date(2026, 8, 20), date(2026, 8, 19)):
        db_session.add(
            SnapshotFii(
                ativo_id=db_session.query(Ativo).filter_by(ticker="MXRF11").one().id,
                data_referencia=dia,
                preco=Decimal("10.00"),
            )
        )
    db_session.commit()

    registros = mercado.obter_snapshots(ticker="MXRF11", session=db_session)
    assert [r.data_referencia for r in registros] == [
        date(2026, 8, 20), date(2026, 8, 19), date(2026, 8, 18),
    ]
    assert mercado.obter_snapshot_mais_recente(ticker="MXRF11", session=db_session).data_referencia == date(2026, 8, 20)


def test_idempotencia_nao_duplica_na_leitura(db_session):
    espelhar_mercado_fiis(db_session, matriz_fiis(), data_referencia=date(2026, 8, 20))
    espelhar_mercado_fiis(db_session, matriz_fiis(), data_referencia=date(2026, 8, 20))
    registros = mercado.obter_snapshots(ticker="MXRF11", session=db_session)
    assert len(registros) == 1


def test_data_referencia_diferente_cria_nova_linha_na_serie(db_session):
    espelhar_mercado_fiis(db_session, matriz_fiis(), data_referencia=date(2026, 8, 19))
    espelhar_mercado_fiis(db_session, matriz_fiis(), data_referencia=date(2026, 8, 20))
    assert len(mercado.obter_snapshots(ticker="MXRF11", session=db_session)) == 2


# ==========================================
# DADOS AUSENTES / ERRO NUNCA VIRA ZERO
# ==========================================

def test_dados_ausentes_permanecem_none(db_session):
    ativo = _criar_ativo(db_session, "MXRF11", TipoAtivo.FII)
    db_session.add(
        SnapshotFii(
            ativo_id=ativo.id,
            data_referencia=date(2026, 8, 20),
            preco=Decimal("9.87"),
            pvp=None,
            dy=None,
        )
    )
    db_session.commit()
    snapshot = mercado.obter_snapshot_mais_recente(ticker="MXRF11", session=db_session)
    assert snapshot.preco == Decimal("9.87")
    assert snapshot.pvp is None
    assert snapshot.dy is None


def test_invalid_nao_persiste_e_nao_e_retornado(db_session):
    matriz = matriz_fiis()
    matriz.append(["HGCR11", "Papel", "CRI", -1.00, 0, 1.5, 0.12, 0.0, 0,
                   "Não informado", "Pendente de IA", "Pendente de IA", 1000.0,
                   1000000000.0, 1.0, 120000000.0, 0.01, "19/08 10:00"])
    rel = espelhar_mercado_fiis(db_session, matriz, data_referencia=date(2026, 8, 20))
    assert rel["invalidos"] == 1
    assert mercado.obter_snapshots(ticker="HGCR11", session=db_session) == []


# ==========================================
# DADOS FINANCEIROS (CVM)
# ==========================================

def test_obter_dados_financeiros_por_tipo_e_tipo_doc(db_session):
    ativo = _criar_ativo(db_session, "PETR4", TipoAtivo.ACAO)
    db_session.add(
        DadosFinanceirosAcoes(
            ativo_id=ativo.id,
            data_referencia=date(2026, 6, 30),
            tipo_doc="ITR",
            lucro_liquido=1000.0,
            receita=5000.0,
        )
    )
    fii = _criar_ativo(db_session, "MXRF11", TipoAtivo.FII)
    db_session.add(
        DadosFinanceirosFiis(
            ativo_id=fii.id,
            data_referencia=date(2026, 6, 30),
            patrimonio_liquido=50.0,
            rendimento_por_cota=0.10,
        )
    )
    db_session.commit()

    acoes = mercado.obter_dados_financeiros(tipo="ACAO", session=db_session)
    assert len(acoes) == 1 and isinstance(acoes[0], DadosFinanceirosAcoes)
    assert acoes[0].lucro_liquido == 1000.0

    itr = mercado.obter_dados_financeiros(tipo="ACAO", tipo_doc="itr", session=db_session)
    assert len(itr) == 1 and itr[0].tipo_doc == "ITR"

    fiis = mercado.obter_dados_financeiros(tipo="FII", session=db_session)
    assert len(fiis) == 1 and isinstance(fiis[0], DadosFinanceirosFiis)

    todos = mercado.obter_dados_financeiros(session=db_session)
    assert len(todos) == 2


def test_tipo_doc_com_fii_e_rejeitado(db_session):
    with pytest.raises(ValueError):
        mercado.obter_dados_financeiros(tipo="FII", tipo_doc="ITR", session=db_session)


# ==========================================
# VALIDAÇÕES DO SERVIÇO
# ==========================================

def test_tipo_invalido_rejeitado(db_session):
    for tipo_invalido in ("ETF", "CRIPTO", "FUNDO"):
        with pytest.raises(ValueError):
            mercado.obter_snapshots(tipo=tipo_invalido, session=db_session)
        with pytest.raises(ValueError):
            mercado.obter_dados_financeiros(tipo=tipo_invalido, session=db_session)


def test_limite_aplicado_e_teto_seguro(db_session):
    ativo = _criar_ativo(db_session, "MXRF11", TipoAtivo.FII)
    for dia in (date(2026, 8, 18), date(2026, 8, 19), date(2026, 8, 20)):
        db_session.add(
            SnapshotFii(
                ativo_id=ativo.id, data_referencia=dia, preco=Decimal("10.00")
            )
        )
    db_session.commit()
    assert len(mercado.obter_snapshots(ticker="MXRF11", limite=2, session=db_session)) == 2
    assert len(mercado.obter_snapshots(ticker="MXRF11", limite=9999, session=db_session)) <= 500


def test_snapshot_mais_recente_retorna_none_quando_ausente(db_session):
    assert mercado.obter_snapshot_mais_recente(ticker="INEXISTENTE", session=db_session) is None


# ==========================================
# SERIALIZAÇÃO
# ==========================================

def test_serializar_snapshot_fii_e_explicito_e_preserva_none(db_session):
    from api.serializadores import serializar_snapshot

    ativo = _criar_ativo(db_session, "MXRF11", TipoAtivo.FII)
    snapshot = SnapshotFii(
        ativo_id=ativo.id,
        data_referencia=date(2026, 8, 20),
        preco=Decimal("9.87"),
        pvp=None,
        dy=Decimal("0.12"),
    )
    db_session.add(snapshot)
    db_session.commit()

    dados = serializar_snapshot(snapshot)
    assert dados["ticker"] == "MXRF11"
    assert dados["tipo"] == "FII"
    assert dados["preco"] == 9.87
    assert dados["pvp"] is None
    assert dados["dy"] == 0.12


def test_serializar_dados_financeiros_acoes_explicito(db_session):
    from api.serializadores import serializar_dados_financeiros

    ativo = _criar_ativo(db_session, "PETR4", TipoAtivo.ACAO)
    registro = DadosFinanceirosAcoes(
        ativo_id=ativo.id,
        data_referencia=date(2026, 6, 30),
        tipo_doc="ITR",
        lucro_liquido=1000.0,
        divida_liquida=None,
    )
    db_session.add(registro)
    db_session.commit()

    dados = serializar_dados_financeiros(registro)
    assert dados["tipo_doc"] == "ITR"
    assert dados["lucro_liquido"] == 1000.0
    assert dados["divida_liquida"] is None


# ==========================================
# ENDPOINTS HTTP /api/v1/mercado/*
# ==========================================

@pytest.fixture()
def ambiente(monkeypatch):
    """Flask app com a API integrada, SQLite em memória e um usuário/chave."""
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
    espelhar_mercado_fiis(sessao, matriz_fiis(), data_referencia=date(2026, 8, 20))
    usuario = usuarios.criar_usuario(
        nome="Usuario", email="user@mercado.com", senha="senha1234",
        papel=usuarios.USER, session=sessao,
    )
    chave = chaves_api.criar_chave_api(usuario, "chave-mercado", session=sessao)
    sessao.close()

    app = Flask(__name__)
    app.config["TESTING"] = True
    integrar_api(app, habilitada=True)
    return {"cliente": app.test_client(), "chave": chave}


def _cabecalho(ambiente):
    return {"X-API-Key": ambiente["chave"]}


def test_api_snapshots_requer_autenticacao(ambiente):
    resposta = ambiente["cliente"].get("/api/v1/mercado/snapshots")
    assert resposta.status_code == 401


def test_api_listar_snapshots(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/mercado/snapshots", headers=_cabecalho(ambiente)
    )
    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados["meta"]["total"] == 2
    assert {item["ticker"] for item in dados["data"]} == {"MXRF11", "GARE11"}
    assert all(item["tipo"] == "FII" for item in dados["data"])


def test_api_filtrar_snapshots_por_ticker_e_tipo(ambiente):
    cabecalho = _cabecalho(ambiente)
    cliente = ambiente["cliente"]
    assert cliente.get(
        "/api/v1/mercado/snapshots?ticker=MXRF11", headers=cabecalho
    ).get_json()["meta"]["total"] == 1
    assert cliente.get(
        "/api/v1/mercado/snapshots?tipo_ativo=ACAO", headers=cabecalho
    ).get_json()["meta"]["total"] == 0
    assert cliente.get(
        "/api/v1/mercado/snapshots?tipo_ativo=FII", headers=cabecalho
    ).get_json()["meta"]["total"] == 2


def test_api_snapshot_mais_recente_e_404_quando_ausente(ambiente):
    cabecalho = _cabecalho(ambiente)
    cliente = ambiente["cliente"]
    resposta = cliente.get(
        "/api/v1/mercado/snapshots/mais-recente?ticker=MXRF11", headers=cabecalho
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["ticker"] == "MXRF11"

    ausente = cliente.get(
        "/api/v1/mercado/snapshots/mais-recente?ticker=ZZZZ9", headers=cabecalho
    )
    assert ausente.status_code == 404


def test_api_data_referencia_invalida_retorna_400(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/mercado/snapshots?data_referencia=20-08-2026",
        headers=_cabecalho(ambiente),
    )
    assert resposta.status_code == 400


def test_api_dados_financeiros(ambiente):
    sessao = dependencias.obter_sessao()
    ativo = sessao.query(Ativo).filter(Ativo.ticker == "MXRF11").one()
    sessao.add(
        DadosFinanceirosFiis(
            ativo_id=ativo.id,
            data_referencia=date(2026, 6, 30),
            patrimonio_liquido=50.0,
        )
    )
    sessao.commit()
    sessao.close()

    resposta = ambiente["cliente"].get(
        "/api/v1/mercado/dados-financeiros?tipo_ativo=FII",
        headers=_cabecalho(ambiente),
    )
    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados["meta"]["total"] == 1
    assert dados["data"][0]["tipo"] == "FII"
    assert dados["data"][0]["patrimonio_liquido"] == 50.0
