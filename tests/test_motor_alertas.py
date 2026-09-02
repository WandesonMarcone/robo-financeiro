"""Testes do motor de qualidade, detecção de mudanças e alertas — Fase 4.

Cobre (Ações e FIIs de forma genérica): primeira observação sem histórico;
valor inalterado não regrava nem alerta; alteração acima do limiar gera alerta
de mercado; alteração pequena não alerta; variação crítica vira alerta crítico;
negativo legítimo não alerta; preço negativo gera alerta de qualidade; ausência
de Telegram não falha; notificação Telegram marca telegram_enviado; mensagem
formatada; dados originais nunca são mutados; alerta persistido no banco.
"""
from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import config
from pipeline_dados.banco_dados import (
    AlertaEvento,
    Ativo,
    Base,
    IndicadorHistorico,
    TipoAtivo,
)
from pipeline_dados.mapeamento_sheets import ORIGEM_GOOGLE_SHEETS
from pipeline_dados.motor_alertas import (
    TIPO_CRITICO,
    TIPO_MERCADO,
    TIPO_QUALIDADE,
    detectar_mudanca,
    formatar_mensagem,
    gerar_alerta,
    notificar_telegram,
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


@pytest.fixture()
def acao(db_session):
    ativo = Ativo(ticker="PETR4", cnpj="22222222222222", tipo=TipoAtivo.ACAO)
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


def _dados_acao(**overrides):
    dados = {
        "preco": 25.0, "dy": 0.05, "pl": 8.0, "pvp": 1.2, "p_ativo": 0.8,
        "marg_bruta": 0.35, "marg_ebit": 0.20, "marg_liquida": 0.12,
        "p_ebit": 6.0, "ev_ebit": 7.0, "div_liq_patrimonio": 0.8, "psr": 1.5,
        "p_cap_giro": 3.0, "p_at_circ_liq": 2.0, "liq_corrente": 1.5, "roe": 0.20,
        "roa": 0.08, "roic": 0.10, "cagr_rec_5a": 0.15, "liq_media": 500000.0,
        "vpa": 20.0, "lpa": 3.0, "peg_ratio": 1.2, "valor_mercado": 100000000.0,
    }
    dados.update(overrides)
    return dados


def _historico(db_session, ativo, indicador):
    return (
        db_session.query(IndicadorHistorico)
        .filter_by(ativo_id=ativo.id, indicador=indicador)
        .first()
    )


def _qtd_alertas(db_session):
    return db_session.query(AlertaEvento).count()


# ===========================================================================
# Primeira observação / sem histórico
# ===========================================================================

def test_primeira_observacao_registra_historico_sem_alerta(db_session, fii):
    alertas = processar_indicadores_ativo(
        db_session, fii, _dados_fii(), "FII", REF, notificar=False
    )
    assert alertas == []
    assert db_session.query(IndicadorHistorico).count() == 8
    hist = _historico(db_session, fii, "preco")
    assert float(hist.valor_atual) == 9.87
    assert hist.valor_anterior is None
    assert hist.variacao_percentual is None


def test_primeira_observacao_acao_registra_historico_sem_alerta(db_session, acao):
    alertas = processar_indicadores_ativo(
        db_session, acao, _dados_acao(), "ACAO", REF, notificar=False
    )
    assert alertas == []
    assert db_session.query(IndicadorHistorico).count() == 24


# ===========================================================================
# Valor inalterado
# ===========================================================================

def test_valor_inalterado_nao_regrava_historico_nem_alerta(db_session, fii):
    processar_indicadores_ativo(db_session, fii, _dados_fii(), "FII", REF, notificar=False)
    alertas = processar_indicadores_ativo(
        db_session, fii, _dados_fii(), "FII", REF, notificar=False
    )
    assert alertas == []
    assert db_session.query(IndicadorHistorico).count() == 8
    hist = _historico(db_session, fii, "preco")
    assert float(hist.valor_atual) == 9.87
    assert hist.valor_anterior is None
    assert hist.ultima_coleta is not None


def test_valor_inalterado_com_qualidade_suspeita_avisa_uma_vez(db_session, fii):
    processar_indicadores_ativo(
        db_session, fii, _dados_fii(dy=0.30), "FII", REF, notificar=False
    )
    assert _qtd_alertas(db_session) == 1
    alerta = db_session.query(AlertaEvento).first()
    assert alerta.tipo_alerta == TIPO_QUALIDADE
    assert alerta.indicador == "dy"
    assert alerta.valor_anterior is None


# ===========================================================================
# Alteração de valor / alertas de mercado
# ===========================================================================

def test_alteracao_acima_do_limite_gera_alerta_mercado(db_session, fii):
    processar_indicadores_ativo(db_session, fii, _dados_fii(), "FII", REF, notificar=False)
    alertas = processar_indicadores_ativo(
        db_session, fii, _dados_fii(preco=11.50), "FII", REF, notificar=False
    )
    assert len(alertas) == 1
    alerta = alertas[0]
    assert alerta.tipo_alerta == TIPO_MERCADO
    assert alerta.indicador == "preco"
    assert float(alerta.valor_anterior) == 9.87
    assert float(alerta.valor_atual) == 11.50
    assert float(alerta.variacao_percentual) == pytest.approx(16.51, abs=0.1)
    assert _qtd_alertas(db_session) == 1


def test_alteracao_pequena_nao_gera_alerta_mas_atualiza_historico(db_session, fii):
    processar_indicadores_ativo(db_session, fii, _dados_fii(), "FII", REF, notificar=False)
    alertas = processar_indicadores_ativo(
        db_session, fii, _dados_fii(preco=9.90), "FII", REF, notificar=False
    )
    assert alertas == []
    hist = _historico(db_session, fii, "preco")
    assert float(hist.valor_atual) == 9.90
    assert float(hist.valor_anterior) == 9.87


def test_variacao_critica_gera_alerta_critico(db_session, fii):
    processar_indicadores_ativo(db_session, fii, _dados_fii(), "FII", REF, notificar=False)
    alertas = processar_indicadores_ativo(
        db_session, fii, _dados_fii(preco=15.00), "FII", REF, notificar=False
    )
    assert len(alertas) == 1
    assert alertas[0].tipo_alerta == TIPO_CRITICO


# ===========================================================================
# Qualidade: negativo legítimo vs suspeito/impossível
# ===========================================================================

def test_preco_negativo_gera_alerta_de_qualidade(db_session, fii):
    alertas = processar_indicadores_ativo(
        db_session, fii, _dados_fii(preco=-1.00), "FII", REF, notificar=False
    )
    assert len(alertas) == 1
    alerta = alertas[0]
    assert alerta.tipo_alerta == TIPO_QUALIDADE
    assert alerta.indicador == "preco"
    assert alerta.severidade == "ERRO"
    assert alerta.regra == "VALOR_NEGATIVO_IMPOSSIVEL"


def test_negativo_legitimo_nao_gera_alerta(db_session, acao):
    alertas = processar_indicadores_ativo(
        db_session, acao, _dados_acao(roe=-0.10, lpa=-1.50), "ACAO", REF,
        notificar=False,
    )
    assert alertas == []
    hist_roe = _historico(db_session, acao, "roe")
    assert float(hist_roe.valor_atual) == -0.10
    hist_lpa = _historico(db_session, acao, "lpa")
    assert float(hist_lpa.valor_atual) == -1.50


def test_negativo_legitimo_sem_alertas_em_repeticoes(db_session, acao):
    dados = _dados_acao(roe=-0.10)
    processar_indicadores_ativo(db_session, acao, dados, "ACAO", REF, notificar=False)
    alertas = processar_indicadores_ativo(
        db_session, acao, dados, "ACAO", REF, notificar=False
    )
    assert alertas == []
    assert _qtd_alertas(db_session) == 0


def test_negativo_suspeito_gera_alerta_qualidade(db_session, fii):
    alertas = processar_indicadores_ativo(
        db_session, fii, _dados_fii(dy=-0.02), "FII", REF, notificar=False
    )
    assert len(alertas) == 1
    assert alertas[0].tipo_alerta == TIPO_QUALIDADE
    assert alertas[0].indicador == "dy"
    assert alertas[0].severidade == "WARNING"


# ===========================================================================
# Telegram
# ===========================================================================

def test_sem_telegram_notificacao_retorna_falso(db_session, fii):
    alerta = _criar_alerta(db_session, fii)
    with patch.object(config, "TELEGRAM_BOT_TOKEN", ""), patch.object(
        config, "TELEGRAM_CHAT_ID", None
    ):
        assert notificar_telegram(alerta, fii.ticker) is False
    assert alerta.telegram_enviado is False


def test_processar_indicadores_sem_telegram_nao_falha(db_session, fii):
    processar_indicadores_ativo(db_session, fii, _dados_fii(), "FII", REF)
    with patch.object(config, "TELEGRAM_BOT_TOKEN", ""):
        alertas = processar_indicadores_ativo(
            db_session, fii, _dados_fii(preco=11.50), "FII", REF, notificar=True
        )
    assert len(alertas) == 1
    assert alertas[0].telegram_enviado is False


def test_notificacao_telegram_marca_enviado(db_session, fii):
    alerta = _criar_alerta(db_session, fii)
    sentinela = object()
    with patch("bot.loader.enviar_mensagem", return_value=sentinela) as mock_env:
        assert notificar_telegram(alerta, fii.ticker) is True
    mock_env.assert_called_once()
    assert alerta.telegram_enviado is True


# ===========================================================================
# Mensagem / persistência / não mutação
# ===========================================================================

def test_formatar_mensagem_inclui_contexto(db_session, fii):
    alerta = _criar_alerta(db_session, fii)
    texto = formatar_mensagem(alerta, fii.ticker)
    assert "MXRF11" in texto
    assert "FII" in texto
    assert "preco" in texto
    assert "Anterior" in texto
    assert "Atual" in texto
    assert "Motivo" in texto
    assert "Severidade" in texto
    assert "Vari" in texto


def test_alerta_persistido_no_banco(db_session, fii):
    processar_indicadores_ativo(db_session, fii, _dados_fii(), "FII", REF, notificar=False)
    processar_indicadores_ativo(
        db_session, fii, _dados_fii(preco=11.50), "FII", REF, notificar=False
    )
    alerta = db_session.query(AlertaEvento).first()
    assert alerta is not None
    assert alerta.ativo_id == fii.id
    assert alerta.tipo_ativo == "FII"
    assert alerta.origem == ORIGEM_GOOGLE_SHEETS
    assert alerta.recomendacao
    assert alerta.telegram_enviado is False


def test_processar_indicadores_nao_muta_dados(db_session, fii):
    dados = _dados_fii(preco=-1.00)
    original = dict(dados)
    processar_indicadores_ativo(db_session, fii, dados, "FII", REF, notificar=False)
    assert dados == original


def test_dados_vazios_sao_ignorados(db_session, fii):
    alertas = processar_indicadores_ativo(db_session, fii, {}, "FII", REF, notificar=False)
    assert alertas == []
    assert db_session.query(IndicadorHistorico).count() == 0


def test_indicador_com_valor_ilegivel_ignorado(db_session, fii):
    dados = _dados_fii(preco="abc")
    alertas = processar_indicadores_ativo(db_session, fii, dados, "FII", REF, notificar=False)
    assert alertas == []
    assert _historico(db_session, fii, "preco") is None


def _criar_alerta(db_session, fii, preco_atual=11.50):
    detectar_mudanca(db_session, fii, "FII", "preco", 9.87, REF, ORIGEM_GOOGLE_SHEETS)
    mudanca = detectar_mudanca(
        db_session, fii, "FII", "preco", preco_atual, REF, ORIGEM_GOOGLE_SHEETS
    )
    alerta = gerar_alerta(
        db_session, fii, "FII", "preco", preco_atual, mudanca, REF,
        ORIGEM_GOOGLE_SHEETS,
    )
    assert alerta is not None
    return alerta
