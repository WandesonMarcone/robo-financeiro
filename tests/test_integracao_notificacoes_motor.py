"""Integração: alertas reais do pipeline (Fase 4) alimentam o motor individual
de notificações (Fase 6) sem quebrar o fluxo nem o Telegram legado.

Cobre: alerta real detectado gera ``Notificacao`` individual para quem
acompanha o ativo; idempotência (reprocessar os mesmos dados não duplica);
isolamento entre usuários (quem não acompanha não recebe); o envio legado ao
Telegram continua intacto; uma falha no motor individual nunca derruba o
pipeline de detecção.
"""
from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline_dados.banco_dados import (
    Ativo,
    AtivoAcompanhado,
    Base,
    Notificacao,
    TipoAtivo,
)
from pipeline_dados.motor_alertas import TIPO_MERCADO, processar_indicadores_ativo
from services import usuarios

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


def _criar_usuario(db_session, nome):
    return usuarios.criar_usuario(
        nome=nome,
        email=f"{nome}@x.com",
        senha="senha1234",
        papel=usuarios.USER,
        ativo=True,
        session=db_session,
    )


def _seguir(db_session, usuario, ativo_id):
    db_session.add(AtivoAcompanhado(usuario_id=usuario.id, ativo_id=ativo_id))
    db_session.commit()


def _primeira_observacao(db_session, fii):
    processar_indicadores_ativo(
        db_session, fii, _dados_fii(), "FII", REF, notificar=False
    )


def _disparar_alerta(db_session, fii):
    return processar_indicadores_ativo(
        db_session, fii, _dados_fii(preco=11.50), "FII", REF, notificar=True
    )


def test_alerta_real_gera_notificacao_individual(db_session, fii):
    alice = _criar_usuario(db_session, "alice")
    _seguir(db_session, alice, fii.id)

    _primeira_observacao(db_session, fii)
    alertas = _disparar_alerta(db_session, fii)

    assert len(alertas) == 1
    assert alertas[0].tipo_alerta == TIPO_MERCADO

    notificacoes = db_session.query(Notificacao).all()
    assert len(notificacoes) == 1
    notificacao = notificacoes[0]
    assert notificacao.usuario_id == alice.id
    assert notificacao.tipo == "ALERTA_MERCADO"
    assert notificacao.ativo_id == fii.id
    assert notificacao.canal == "WEB"
    assert notificacao.status == "GERADA"
    assert notificacao.evento_id == f"alerta:{alertas[0].id}"
    assert notificacao.titulo.startswith("MXRF11")
    assert "MXRF11" in notificacao.mensagem


def test_reprocessar_mesmos_dados_nao_duplica_notificacoes(db_session, fii):
    alice = _criar_usuario(db_session, "alice")
    _seguir(db_session, alice, fii.id)

    _primeira_observacao(db_session, fii)
    _disparar_alerta(db_session, fii)
    assert db_session.query(Notificacao).count() == 1

    alertas = processar_indicadores_ativo(
        db_session, fii, _dados_fii(preco=11.50), "FII", REF, notificar=True
    )
    assert alertas == []
    assert db_session.query(Notificacao).count() == 1


def test_quem_nao_acompanha_o_ativo_nao_recebe_notificacao(db_session, fii):
    alice = _criar_usuario(db_session, "alice")
    _criar_usuario(db_session, "bob")
    _seguir(db_session, alice, fii.id)

    _primeira_observacao(db_session, fii)
    _disparar_alerta(db_session, fii)

    notificacoes = db_session.query(Notificacao).all()
    assert len(notificacoes) == 1
    assert notificacoes[0].usuario_id == alice.id


def test_telegram_legado_continua_sendo_notificado(db_session, fii):
    sentinela = object()
    with patch("bot.loader.enviar_mensagem", return_value=sentinela) as mock_envio:
        _primeira_observacao(db_session, fii)
        alertas = _disparar_alerta(db_session, fii)
    mock_envio.assert_called_once()
    assert alertas[0].telegram_enviado is True


def test_falha_no_motor_individual_nao_derruba_pipeline(db_session, fii):
    _primeira_observacao(db_session, fii)
    with patch(
        "services.notificacoes.processar_evento", side_effect=RuntimeError("boom")
    ):
        alertas = _disparar_alerta(db_session, fii)
    assert len(alertas) == 1
    assert alertas[0].tipo_alerta == TIPO_MERCADO
    assert db_session.query(Notificacao).count() == 0
