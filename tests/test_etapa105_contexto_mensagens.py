"""Testes da Etapa 10.5 — contexto e qualidade da mensagem de alerta.

Cobre o texto gerado por ``formatar_mensagem`` e o payload entregue ao
dispatcher/Telegram: ativo, tipo, indicador, valores, prioridade, data,
origem, freshness, motivo. Sem LLM, sem segundo motor.
"""
import json
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pipeline_dados.banco_dados import (
    AlertaEvento,
    Ativo,
    Base,
    IndicadorHistorico,
    Notificacao,
    TipoAtivo,
    Usuario,
)
from pipeline_dados.mapeamento_sheets import ORIGEM_GOOGLE_SHEETS
from pipeline_dados.motor_alertas import (
    PRIORIDADE_ALTO,
    PRIORIDADE_CRITICO,
    PRIORIDADE_MEDIO,
    TIPO_CRITICO,
    TIPO_MERCADO,
    TIPO_QUALIDADE,
    formatar_mensagem,
    processar_indicadores_ativo,
)

REF = date(2026, 8, 19)


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessao = sessionmaker(bind=engine)()
    yield sessao
    sessao.close()


@pytest.fixture()
def fii(db_session):
    ativo = Ativo(ticker="MXRF11", cnpj="11111111111111", tipo=TipoAtivo.FII)
    db_session.add(ativo)
    db_session.commit()
    return ativo


def _dados_fii(**overrides):
    dados = {
        "preco": 9.87, "pvp": 0.95, "dy": 0.12, "liquidez": 1500000.0,
        "vpa": 10.39, "lucro_12m": 576000000.0, "dividendo_mensal": 0.0987,
        "qtd_imoveis": 0,
    }
    dados.update(overrides)
    return dados


def _alerta_mercado(db_session, fii, preco=11.50):
    processar_indicadores_ativo(db_session, fii, _dados_fii(), "FII", REF, notificar=False)
    alertas = processar_indicadores_ativo(
        db_session, fii, _dados_fii(preco=preco), "FII", REF, notificar=False
    )
    assert len(alertas) == 1
    return alertas[0]


# ===========================================================================
# CONTEXTO NA MENSAGEM
# ===========================================================================


def test_mensagem_mercado_inclui_contexto_completo(db_session, fii):
    alerta = _alerta_mercado(db_session, fii)
    texto = formatar_mensagem(alerta, fii.ticker)
    assert "ALERTA DE MERCADO" in texto
    assert "Ativo: MXRF11" in texto
    assert "Tipo: FII" in texto
    assert "Indicador:" in texto
    assert "preco" in texto
    assert "Anterior:" in texto
    assert "Atual:" in texto
    assert "Variacao:" in texto
    assert "Motivo:" in texto
    assert "Severidade:" in texto
    assert f"Prioridade: {PRIORIDADE_MEDIO}" in texto
    assert f"Data: {REF.isoformat()}" in texto
    assert f"Origem: {ORIGEM_GOOGLE_SHEETS}" in texto
    assert "Freshness: FRESH" in texto
    assert alerta.tipo_alerta == TIPO_MERCADO


def test_mensagem_critico_rotulo_consistente(db_session, fii):
    processar_indicadores_ativo(db_session, fii, _dados_fii(), "FII", REF, notificar=False)
    alerta = processar_indicadores_ativo(
        db_session, fii, _dados_fii(preco=15.00), "FII", REF, notificar=False
    )[0]
    texto = formatar_mensagem(alerta, fii.ticker)
    assert alerta.tipo_alerta == TIPO_CRITICO
    assert "ALERTA CRITICO" in texto
    assert "ALERTA CRÍTICO" not in texto
    assert f"Prioridade: {PRIORIDADE_CRITICO}" in texto
    assert "Ativo: MXRF11" in texto
    assert f"Data: {REF.isoformat()}" in texto
    assert f"Origem: {ORIGEM_GOOGLE_SHEETS}" in texto


def test_mensagem_qualidade_sem_anterior_nao_inventa_valor(db_session, fii):
    alertas = processar_indicadores_ativo(
        db_session, fii, _dados_fii(preco=-1.00), "FII", REF, notificar=False
    )
    assert len(alertas) == 1
    alerta = alertas[0]
    texto = formatar_mensagem(alerta, fii.ticker)
    assert alerta.tipo_alerta == TIPO_QUALIDADE
    assert alerta._prioridade == PRIORIDADE_ALTO
    assert "Anterior:" not in texto
    assert "Atual:" in texto
    assert "Variacao:" not in texto
    assert f"Prioridade: {PRIORIDADE_ALTO}" in texto
    assert f"Data: {REF.isoformat()}" in texto
    assert f"Origem: {ORIGEM_GOOGLE_SHEETS}" in texto


def test_mensagem_freshness_stale_no_critico(db_session, fii):
    processar_indicadores_ativo(db_session, fii, _dados_fii(), "FII", REF, notificar=False)
    hist = (
        db_session.query(IndicadorHistorico)
        .filter_by(ativo_id=fii.id, indicador="preco")
        .first()
    )
    hist.ultima_coleta = datetime.now() - timedelta(hours=5)
    db_session.commit()
    alerta = processar_indicadores_ativo(
        db_session, fii, _dados_fii(preco=15.00), "FII", REF, notificar=False
    )[0]
    texto = formatar_mensagem(alerta, fii.ticker)
    assert alerta.tipo_alerta == TIPO_CRITICO
    assert "Freshness: STALE" in texto


def test_mensagem_omite_campos_ausentes():
    alerta = AlertaEvento(
        tipo_alerta=TIPO_QUALIDADE,
        tipo_ativo="FII",
        ativo_id=1,
        indicador="preco",
        valor_anterior=None,
        valor_atual=None,
        variacao_percentual=None,
        regra="VALOR_NEGATIVO_IMPOSSIVEL",
        motivo="Preco negativo.",
        severidade="ERRO",
        recomendacao="Conferir a fonte antes de considerar o dado como real.",
        origem=None,
        data_referencia=None,
    )
    alerta._prioridade = None
    alerta._freshness = None
    texto = formatar_mensagem(alerta, "MXRF11")
    assert "Anterior:" not in texto
    assert "Variacao:" not in texto
    assert "Prioridade:" not in texto
    assert "Data:" not in texto
    assert "Origem:" not in texto
    assert "Freshness:" not in texto
    assert "Ativo: MXRF11" in texto
    assert "Atual: -" in texto


def test_ausente_nao_gera_mensagem(db_session, fii):
    alertas = processar_indicadores_ativo(
        db_session, fii, _dados_fii(preco="-"), "FII", REF, notificar=False
    )
    assert alertas == []
    assert db_session.query(AlertaEvento).count() == 0


# ===========================================================================
# PAYLOAD / DISPATCHER / ISOLAMENTO
# ===========================================================================


@pytest.fixture()
def ambiente(monkeypatch):
    from flask import Flask

    from api import dependencias, integrar_api
    from services import chaves_api, usuarios

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

    app = Flask(__name__)
    app.config["TESTING"] = True
    integrar_api(app, habilitada=True)

    sessao = Session()
    usuarios_ids = {}
    for nome in ("alice", "bob"):
        registro = usuarios.criar_usuario(
            nome=nome,
            email=f"{nome}@x.com",
            senha="senha1234",
            papel=usuarios.USER,
            ativo=True,
            session=sessao,
        )
        usuarios_ids[nome] = registro.id
        chaves_api.criar_chave_api(registro, f"chave-{nome}", session=sessao)

    ativo = Ativo(ticker="MXRF11", cnpj="11.111.111/0001-11", tipo=TipoAtivo.FII)
    sessao.add(ativo)
    sessao.commit()
    ativo_id = ativo.id
    sessao.close()

    return {
        "Session": Session,
        "usuarios": usuarios_ids,
        "ativos": {"MXRF11": ativo_id},
    }


def _id(ambiente, nome):
    return ambiente["usuarios"][nome]


def _seguir_amb(ambiente, nome, ticker="MXRF11"):
    from services import ativos_acompanhados

    sessao = ambiente["Session"]()
    try:
        usuario = sessao.get(Usuario, _id(ambiente, nome))
        ativos_acompanhados.adicionar_acompanhamento(
            usuario, ambiente["ativos"][ticker], session=sessao
        )
    finally:
        sessao.close()


def _vincular_telegram(ambiente, nome, user_id, chat_id):
    from services import usuarios

    sessao = ambiente["Session"]()
    try:
        usuario = sessao.get(Usuario, _id(ambiente, nome))
        usuarios.vincular_telegram(
            usuario, user_id, telegram_chat_id=chat_id, session=sessao
        )
    finally:
        sessao.close()


def _notificacoes(ambiente, nome=None, canal=None):
    sessao = ambiente["Session"]()
    try:
        query = sessao.query(Notificacao)
        if nome is not None:
            query = query.filter(Notificacao.usuario_id == _id(ambiente, nome))
        if canal is not None:
            query = query.filter(Notificacao.canal == canal)
        return query.order_by(Notificacao.id).all()
    finally:
        sessao.close()


def _disparar_mercado(ambiente, preco=11.50):
    sessao = ambiente["Session"]()
    try:
        ativo = sessao.get(Ativo, ambiente["ativos"]["MXRF11"])
        processar_indicadores_ativo(
            sessao, ativo, _dados_fii(), "FII", REF, notificar=False
        )
        return processar_indicadores_ativo(
            sessao, ativo, _dados_fii(preco=preco), "FII", REF, notificar=True
        )
    finally:
        sessao.close()


def test_payload_inclui_contexto_e_freshness(ambiente):
    _seguir_amb(ambiente, "alice")
    _disparar_mercado(ambiente)
    notif = _notificacoes(ambiente, "alice")[0]
    dados = json.loads(notif.dados)
    assert dados["ticker"] == "MXRF11"
    assert dados["tipo_ativo"] == "FII"
    assert dados["indicador"] == "preco"
    assert dados["prioridade"] == PRIORIDADE_MEDIO
    assert dados["tipo_alerta"] == TIPO_MERCADO
    assert dados["origem"] == ORIGEM_GOOGLE_SHEETS
    assert dados["data_referencia"] == REF.isoformat()
    assert dados["freshness"] == "FRESH"
    assert dados["valor_anterior"] is not None
    assert dados["valor_atual"] is not None
    assert "Ativo: MXRF11" in notif.mensagem
    assert "Prioridade: MEDIO" in notif.mensagem
    assert "Data: 2026-08-19" in notif.mensagem
    assert "Origem:" in notif.mensagem
    assert "MXRF11" in notif.titulo
    assert "ALERTA DE MERCADO" in notif.titulo


def test_titulo_critico_sem_acento(ambiente):
    _seguir_amb(ambiente, "alice")
    sessao = ambiente["Session"]()
    try:
        ativo = sessao.get(Ativo, ambiente["ativos"]["MXRF11"])
        processar_indicadores_ativo(
            sessao, ativo, _dados_fii(), "FII", REF, notificar=False
        )
        processar_indicadores_ativo(
            sessao, ativo, _dados_fii(preco=15.00), "FII", REF, notificar=True
        )
    finally:
        sessao.close()
    notif = _notificacoes(ambiente, "alice")[0]
    assert "ALERTA CRITICO" in notif.titulo
    assert "ALERTA CRÍTICO" not in notif.titulo
    assert "ALERTA CRITICO" in notif.mensagem


def test_dispatcher_entrega_mensagem_com_contexto(ambiente, monkeypatch):
    from services import dispatcher_notificacoes

    enviadas = []
    monkeypatch.setattr(
        "bot.loader.enviar_mensagem",
        lambda chat_id, texto, **kwargs: enviadas.append((chat_id, texto)) or object(),
    )
    _seguir_amb(ambiente, "alice")
    _vincular_telegram(ambiente, "alice", 81001, 91001)
    _disparar_mercado(ambiente)
    notif = _notificacoes(ambiente, "alice", "TELEGRAM")[0]
    sessao = ambiente["Session"]()
    try:
        resumo = dispatcher_notificacoes.despachar_notificacao(notif.id, session=sessao)
    finally:
        sessao.close()
    assert resumo["entregue"] is True
    assert len(enviadas) == 1
    chat_id, texto = enviadas[0]
    assert chat_id == 91001
    assert "[NOTIFICACAO]" in texto
    assert "MXRF11" in texto
    assert "ALERTA DE MERCADO" in texto
    assert "Prioridade: MEDIO" in texto
    assert "Data: 2026-08-19" in texto
    assert "Origem:" in texto


def test_mensagem_nao_vaza_para_outro_usuario(ambiente, monkeypatch):
    from services import dispatcher_notificacoes

    enviadas = []
    monkeypatch.setattr(
        "bot.loader.enviar_mensagem",
        lambda chat_id, texto, **kwargs: enviadas.append((chat_id, texto)) or object(),
    )
    _seguir_amb(ambiente, "alice")
    _vincular_telegram(ambiente, "alice", 81001, 91001)
    _vincular_telegram(ambiente, "bob", 81002, 91002)
    _disparar_mercado(ambiente)
    notif = _notificacoes(ambiente, "alice", "TELEGRAM")[0]
    sessao = ambiente["Session"]()
    try:
        dispatcher_notificacoes.despachar_notificacao(notif.id, session=sessao)
    finally:
        sessao.close()
    assert enviadas == [(91001, enviadas[0][1])]
    assert _notificacoes(ambiente, "bob") == []
