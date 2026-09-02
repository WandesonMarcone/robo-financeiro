"""Desacoplamento do Financial Intelligence Core do espelhamento 5C — Fase 7,
Etapa 7.7.

Comprova que o motor de alertas (``pipeline_dados.motor_alertas``) produz e
publica eventos de forma independente do fluxo legado 5C, através da interface
``services.publicador_eventos.publicar_evento``, sem regressões:

- o motor de alertas não referencia (em nível de módulo) o espelhamento 5C;
- não existe ciclo de importação entre motor, publicador, notificações e 5C;
- o motor produz e publica um alerta sem nenhuma chamada ao 5C;
- o publicador gera notificações individualizadas e é idempotente;
- falhas de publicação são isoladas (nunca derrubam o pipeline);
- o fluxo 5C continua consumindo exatamente os mesmos resultados;
- os imports do scheduler/varredura continuam válidos.
"""
import inspect
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
from services.publicador_eventos import publicar_evento

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


def _evento(fii, evento_id="alerta:1"):
    return {
        "tipo": "ALERTA_MERCADO",
        "titulo": f"{fii.ticker} — ALERTA DE MERCADO",
        "mensagem": "Alteração relevante detectada em preco.",
        "ativo_id": fii.id,
        "evento_id": evento_id,
        "dados": {"ticker": fii.ticker, "tipo_ativo": "FII", "indicador": "preco"},
    }


# ===========================================================================
# DESACOPLAMENTO ESTRUTURAL (motor de alertas vs espelhamento 5C)
# ===========================================================================

def test_motor_alertas_nao_referencia_espelhamento_5c():
    """O motor de alertas não importa/referencia o espelhamento 5C (Core independente)."""
    import pipeline_dados.motor_alertas as motor

    fonte = inspect.getsource(motor)
    assert "espelhamento_mercado_5c" not in fonte
    assert "espelhamento_sheets" not in fonte


def test_importacao_sem_ciclo_entre_core_publicador_5c_e_notificacoes():
    """Imports válidos: motor, publicador, 5C e notificações carregam sem ciclo."""
    import pipeline_dados.espelhamento_mercado_5c as cinco_c
    import pipeline_dados.motor_alertas as motor
    import services.notificacoes as notificacoes
    import services.publicador_eventos as publicador

    assert publicador.publicar_evento is not None
    assert motor.processar_indicadores_ativo is not None
    assert notificacoes.processar_evento is not None
    assert cinco_c.espelhar_mercado_se_ativo is not None


# ===========================================================================
# O MOTOR PRODUZ E PUBLICA ALERTAS SEM O FLUXO 5C
# ===========================================================================

def test_motor_produz_e_publica_alerta_sem_5c(db_session, fii):
    """``processar_indicadores_ativo`` gera o alerta e publica a notificação
    individual sem nenhuma chamada ao espelhamento 5C."""
    alice = _criar_usuario(db_session, "alice")
    _seguir(db_session, alice, fii.id)

    processar_indicadores_ativo(db_session, fii, _dados_fii(), "FII", REF, notificar=False)
    alertas = processar_indicadores_ativo(
        db_session, fii, _dados_fii(preco=11.50), "FII", REF, notificar=True
    )

    assert len(alertas) == 1
    assert alertas[0].tipo_alerta == TIPO_MERCADO
    notificacoes = db_session.query(Notificacao).all()
    assert len(notificacoes) == 1
    assert notificacoes[0].usuario_id == alice.id
    assert notificacoes[0].tipo == "ALERTA_MERCADO"
    assert notificacoes[0].evento_id == f"alerta:{alertas[0].id}"


def test_publicar_evento_direto_sem_5c(db_session, fii):
    """A interface de publicação do Core cria a notificação individual sem o 5C."""
    alice = _criar_usuario(db_session, "alice")
    _seguir(db_session, alice, fii.id)

    resumo = publicar_evento(_evento(fii), session=db_session)

    assert resumo["publicado"] is True
    assert resumo["elegiveis"] == 1
    assert resumo["geradas"] == 1
    notificacao = db_session.query(Notificacao).one()
    assert notificacao.usuario_id == alice.id
    assert notificacao.status == "GERADA"


def test_publicar_evento_sem_usuario_elegivel(db_session, fii):
    """Sem acompanhamento do ativo, o evento é publicado sem gerar notificações."""
    resumo = publicar_evento(_evento(fii), session=db_session)
    assert resumo["publicado"] is True
    assert resumo["elegiveis"] == 0
    assert resumo["geradas"] == 0
    assert db_session.query(Notificacao).count() == 0


# ===========================================================================
# IDEMPOTÊNCIA E ISOLAMENTO DE FALHAS
# ===========================================================================

def test_publicar_evento_idempotente(db_session, fii):
    """Reprocessar o mesmo evento não duplica notificações (idempotência)."""
    alice = _criar_usuario(db_session, "alice")
    _seguir(db_session, alice, fii.id)

    resumo1 = publicar_evento(_evento(fii, evento_id="alerta:42"), session=db_session)
    resumo2 = publicar_evento(_evento(fii, evento_id="alerta:42"), session=db_session)

    assert resumo1["geradas"] == 1
    assert resumo2["geradas"] == 0
    assert resumo2["ignoradas"] == 1
    assert db_session.query(Notificacao).count() == 1


def test_publicar_evento_isola_falha_do_motor(db_session, fii):
    """Uma falha no motor de notificações nunca levanta: o Core segue operando."""
    with patch(
        "services.notificacoes.processar_evento", side_effect=RuntimeError("boom")
    ):
        resumo = publicar_evento(_evento(fii), session=db_session)
    assert resumo["publicado"] is False
    assert resumo["erro"] == "boom"
    assert db_session.query(Notificacao).count() == 0


def test_falha_no_publicador_nao_derruba_deteccao(db_session, fii):
    """Uma falha na publicação não interrompe a detecção de alertas do motor."""
    alice = _criar_usuario(db_session, "alice")
    _seguir(db_session, alice, fii.id)
    processar_indicadores_ativo(db_session, fii, _dados_fii(), "FII", REF, notificar=False)

    with patch(
        "services.notificacoes.processar_evento", side_effect=RuntimeError("boom")
    ):
        alertas = processar_indicadores_ativo(
            db_session, fii, _dados_fii(preco=11.50), "FII", REF, notificar=True
        )
    assert len(alertas) == 1
    assert alertas[0].tipo_alerta == TIPO_MERCADO


# ===========================================================================
# FLUXO 5C PRESERVADO
# ===========================================================================

def _matriz_fiis():
    cabecalho = ["Ticker", "Tipo", "Setor", "Preço", "Cotas", "P/VP", "DY", "Vacância",
                 "Imóveis", "Inquilinos", "WALT", "Alavancagem", "Liquidez",
                 "Valor Mercado", "VPA", "Lucro 12M", "Div Mensal", "Carimbo"]
    linhas = [
        ["MXRF11", "Papel", "CRI", 9.87, 500000000.0, 0.95, 0.12, 0.0, 0,
         "Não informado", "Pendente de IA", "Pendente de IA", 1500000.0,
         4800000000.0, 10.39, 576000000.0, 0.0987, "19/08 10:00"],
    ]
    return [cabecalho] + linhas


def _matriz_fiis_preco_alterado():
    matriz = _matriz_fiis()
    matriz[1][3] = 11.50
    return matriz


def test_fluxo_5c_continua_consumindo_os_mesmos_resultados(db_session):
    """O espelhamento 5C continua gerando e publicando alertas via o Core."""
    from pipeline_dados.espelhamento_mercado_5c import espelhar_mercado_fiis

    alice = _criar_usuario(db_session, "alice")
    rel1 = espelhar_mercado_fiis(db_session, _matriz_fiis(), data_referencia=REF)
    assert rel1["criados"] >= 1
    assert "alertas" in rel1

    ativo = db_session.query(Ativo).filter_by(ticker="MXRF11").one()
    _seguir(db_session, alice, ativo.id)

    rel2 = espelhar_mercado_fiis(db_session, _matriz_fiis_preco_alterado(), data_referencia=REF)
    assert rel2["alertas"] >= 1

    notificacao = db_session.query(Notificacao).one()
    assert notificacao.usuario_id == alice.id
    assert notificacao.tipo == "ALERTA_MERCADO"
    assert notificacao.evento_id.startswith("alerta:")


# ===========================================================================
# SCHEDULER / VARREDURA DIÁRIA (sem regressão)
# ===========================================================================

def test_scheduler_imports_permanecem_validos():
    """Os pontos do scheduler (varredura diária e dispatcher) continuam válidos."""
    from services.dispatcher_notificacoes import registrar_dispatcher_no_scheduler
    from services.orquestrador import varredura_diaria

    assert callable(varredura_diaria)
    assert callable(registrar_dispatcher_no_scheduler)
