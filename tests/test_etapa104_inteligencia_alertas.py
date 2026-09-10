"""Testes da Etapa 10.4 — inteligencia e priorizacao deterministica de alertas.

Cobre prioridade CRITICO/ALTO/MEDIO/BAIXO, relevancia, estados de dado
(AUSENTE/INVALIDO/NAO_APLICAVEL/ZERO/PRESENTE), deduplicacao, preservacao
do critico, preferencias bloqueando, isolamento entre usuarios, dispatcher
individual e regressao do motor da Fase 4 / Etapa 10.3. Sem LLM.
"""
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
from pipeline_dados.motor_alertas import (
    MOTIVO_DUPLICADO,
    MOTIVO_FRESHNESS,
    MOTIVO_IRRELEVANTE,
    MOTIVO_SEMANTICA,
    PRIORIDADE_ALTO,
    PRIORIDADE_BAIXO,
    PRIORIDADE_CRITICO,
    PRIORIDADE_MEDIO,
    TIPO_CRITICO,
    TIPO_MERCADO,
    TIPO_QUALIDADE,
    avaliar_dado,
    classificar_prioridade,
    decidir_alerta,
    detectar_mudanca,
    evento_relevante,
    gerar_alerta,
    processar_indicadores_ativo,
)
from pipeline_dados.semantica_indicadores import (
    AUSENTE,
    INVALIDO,
    NAO_APLICAVEL,
    PRESENTE,
    ZERO,
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


# ===========================================================================
# PRIORIDADE
# ===========================================================================


def test_prioridade_critico_variacao_acima_do_limiar(db_session, fii):
    processar_indicadores_ativo(db_session, fii, _dados_fii(), "FII", REF, notificar=False)
    alertas = processar_indicadores_ativo(
        db_session, fii, _dados_fii(preco=15.00), "FII", REF, notificar=False
    )
    assert len(alertas) == 1
    assert alertas[0].tipo_alerta == TIPO_CRITICO
    assert alertas[0]._prioridade == PRIORIDADE_CRITICO


def test_prioridade_alto_qualidade_erro(db_session, fii):
    alertas = processar_indicadores_ativo(
        db_session, fii, _dados_fii(preco=-1.00), "FII", REF, notificar=False
    )
    assert len(alertas) == 1
    assert alertas[0].tipo_alerta == TIPO_QUALIDADE
    assert alertas[0].severidade == "ERRO"
    assert alertas[0]._prioridade == PRIORIDADE_ALTO


def test_prioridade_medio_alerta_de_mercado(db_session, fii):
    processar_indicadores_ativo(db_session, fii, _dados_fii(), "FII", REF, notificar=False)
    alertas = processar_indicadores_ativo(
        db_session, fii, _dados_fii(preco=11.50), "FII", REF, notificar=False
    )
    assert len(alertas) == 1
    assert alertas[0].tipo_alerta == TIPO_MERCADO
    assert alertas[0]._prioridade == PRIORIDADE_MEDIO


def test_prioridade_baixo_qualidade_warning_sem_mudanca(db_session, fii):
    alertas = processar_indicadores_ativo(
        db_session, fii, _dados_fii(dy=0.30), "FII", REF, notificar=False
    )
    assert len(alertas) == 1
    assert alertas[0].tipo_alerta == TIPO_QUALIDADE
    assert alertas[0].severidade == "WARNING"
    assert alertas[0]._prioridade == PRIORIDADE_BAIXO


def test_classificar_prioridade_funcoes_puras():
    assert classificar_prioridade(
        TIPO_CRITICO, {"severidade": "CRITICO"}, {"mudou": False}
    ) == PRIORIDADE_CRITICO
    assert classificar_prioridade(
        TIPO_QUALIDADE, {"severidade": "ERRO"}, {"mudou": False}
    ) == PRIORIDADE_ALTO
    assert classificar_prioridade(
        TIPO_MERCADO, {"severidade": "OK"}, {"mudou": True, "variacao_percentual": 16.51}
    ) == PRIORIDADE_MEDIO
    assert classificar_prioridade(
        TIPO_QUALIDADE, {"severidade": "WARNING"}, {"mudou": False}
    ) == PRIORIDADE_BAIXO


# ===========================================================================
# RELEVANCIA / RUIDO
# ===========================================================================


def test_evento_irrelevante_variacao_pequena(db_session, fii):
    processar_indicadores_ativo(db_session, fii, _dados_fii(), "FII", REF, notificar=False)
    alertas = processar_indicadores_ativo(
        db_session, fii, _dados_fii(preco=9.90), "FII", REF, notificar=False
    )
    assert alertas == []
    relevante, motivo = evento_relevante(
        None,
        {"severidade": "OK"},
        {"mudou": True, "variacao_percentual": 0.30, "limite_variacao_pct": 0.10},
        semantica=PRESENTE,
    )
    assert relevante is False
    assert motivo == MOTIVO_IRRELEVANTE


def test_alerta_repetido_nao_regenera(db_session, fii):
    processar_indicadores_ativo(
        db_session, fii, _dados_fii(dy=0.30), "FII", REF, notificar=False
    )
    assert db_session.query(AlertaEvento).count() == 1
    alertas = processar_indicadores_ativo(
        db_session, fii, _dados_fii(dy=0.30), "FII", REF, notificar=False
    )
    assert alertas == []
    assert db_session.query(AlertaEvento).count() == 1


def test_alerta_repetido_mercado_mesmo_valor(db_session, fii):
    processar_indicadores_ativo(db_session, fii, _dados_fii(), "FII", REF, notificar=False)
    processar_indicadores_ativo(
        db_session, fii, _dados_fii(preco=11.50), "FII", REF, notificar=False
    )
    assert db_session.query(AlertaEvento).count() == 1
    alertas = processar_indicadores_ativo(
        db_session, fii, _dados_fii(preco=11.50), "FII", REF, notificar=False
    )
    assert alertas == []
    assert db_session.query(AlertaEvento).count() == 1


def test_alerta_critico_preservado_na_primeira_ocorrencia(db_session, fii):
    processar_indicadores_ativo(db_session, fii, _dados_fii(), "FII", REF, notificar=False)
    alertas = processar_indicadores_ativo(
        db_session, fii, _dados_fii(preco=15.00), "FII", REF, notificar=False
    )
    assert len(alertas) == 1
    assert alertas[0]._prioridade == PRIORIDADE_CRITICO


def test_alerta_critico_novo_valor_nao_e_silenciado(db_session, fii):
    processar_indicadores_ativo(db_session, fii, _dados_fii(), "FII", REF, notificar=False)
    processar_indicadores_ativo(
        db_session, fii, _dados_fii(preco=15.00), "FII", REF, notificar=False
    )
    alertas = processar_indicadores_ativo(
        db_session, fii, _dados_fii(preco=20.00), "FII", REF, notificar=False
    )
    assert len(alertas) == 1
    assert alertas[0].tipo_alerta == TIPO_CRITICO
    assert db_session.query(AlertaEvento).count() == 2


def test_freshness_stale_bloqueia_nao_critico():
    relevante, motivo = evento_relevante(
        TIPO_MERCADO,
        {"severidade": "OK"},
        {"mudou": True, "variacao_percentual": 16.51},
        semantica=PRESENTE,
        freshness="STALE",
    )
    assert relevante is False
    assert motivo == MOTIVO_FRESHNESS


def test_freshness_stale_nao_bloqueia_critico():
    relevante, motivo = evento_relevante(
        TIPO_CRITICO,
        {"severidade": "CRITICO"},
        {"mudou": False},
        semantica=PRESENTE,
        freshness="STALE",
    )
    assert relevante is True
    assert motivo is None


def test_freshness_stale_bloqueia_mercado_no_pipeline(db_session, fii):
    processar_indicadores_ativo(db_session, fii, _dados_fii(), "FII", REF, notificar=False)
    hist = (
        db_session.query(IndicadorHistorico)
        .filter_by(ativo_id=fii.id, indicador="preco")
        .first()
    )
    hist.ultima_coleta = datetime.now() - timedelta(hours=5)
    db_session.commit()
    alertas = processar_indicadores_ativo(
        db_session, fii, _dados_fii(preco=11.50), "FII", REF, notificar=False
    )
    assert alertas == []
    assert db_session.query(AlertaEvento).count() == 0


def test_freshness_stale_nao_bloqueia_critico_no_pipeline(db_session, fii):
    processar_indicadores_ativo(db_session, fii, _dados_fii(), "FII", REF, notificar=False)
    hist = (
        db_session.query(IndicadorHistorico)
        .filter_by(ativo_id=fii.id, indicador="preco")
        .first()
    )
    hist.ultima_coleta = datetime.now() - timedelta(hours=5)
    db_session.commit()
    alertas = processar_indicadores_ativo(
        db_session, fii, _dados_fii(preco=15.00), "FII", REF, notificar=False
    )
    assert len(alertas) == 1
    assert alertas[0].tipo_alerta == TIPO_CRITICO
    assert alertas[0]._prioridade == PRIORIDADE_CRITICO


# ===========================================================================
# ESTADOS DE DADO
# ===========================================================================


def test_dado_ausente_nao_vira_evento_financeiro(db_session, fii):
    assert avaliar_dado("FII", "preco", None)["semantica"] == AUSENTE
    assert avaliar_dado("FII", "preco", "-")["semantica"] == AUSENTE
    assert avaliar_dado("FII", "preco", None)["recusar"] is True
    alertas = processar_indicadores_ativo(
        db_session, fii, _dados_fii(preco="-"), "FII", REF, notificar=False
    )
    assert alertas == []
    assert db_session.query(AlertaEvento).count() == 0


def test_dado_invalido_nao_vira_evento_financeiro(db_session, fii):
    assert avaliar_dado("FII", "preco", "abc")["semantica"] == INVALIDO
    assert avaliar_dado("FII", "preco", "abc")["recusar"] is True
    alertas = processar_indicadores_ativo(
        db_session, fii, _dados_fii(preco="abc"), "FII", REF, notificar=False
    )
    assert alertas == []
    assert db_session.query(AlertaEvento).count() == 0


def test_nao_aplicavel_nao_vira_evento(db_session, fii):
    avaliacao = avaliar_dado("FII", "preco", "n/a")
    assert avaliacao["semantica"] == NAO_APLICAVEL
    assert avaliacao["recusar"] is True
    relevante, motivo = evento_relevante(
        TIPO_MERCADO, {"severidade": "OK"}, {"mudou": True}, semantica=NAO_APLICAVEL
    )
    assert relevante is False
    assert motivo == MOTIVO_SEMANTICA


def test_zero_real_e_utilizavel_nao_ausente():
    avaliacao = avaliar_dado("FII", "qtd_imoveis", 0)
    assert avaliacao["semantica"] == ZERO
    assert avaliacao["utilizavel"] is True
    assert avaliacao["recusar"] is False


def test_presente_e_utilizavel():
    avaliacao = avaliar_dado("FII", "preco", 9.87)
    assert avaliacao["semantica"] == PRESENTE
    assert avaliacao["utilizavel"] is True
    assert avaliacao["recusar"] is False


def test_ausente_nao_corrompe_historico(db_session, fii):
    processar_indicadores_ativo(db_session, fii, _dados_fii(), "FII", REF, notificar=False)
    processar_indicadores_ativo(
        db_session, fii, _dados_fii(preco="n/d"), "FII", REF, notificar=False
    )
    hist = (
        db_session.query(IndicadorHistorico)
        .filter_by(ativo_id=fii.id, indicador="preco")
        .first()
    )
    assert float(hist.valor_atual) == 9.87
    assert db_session.query(AlertaEvento).count() == 0


# ===========================================================================
# REGRESSAO DO MOTOR ATUAL
# ===========================================================================


def test_regressao_primeira_observacao_sem_alerta_mercado(db_session, fii):
    alertas = processar_indicadores_ativo(
        db_session, fii, _dados_fii(), "FII", REF, notificar=False
    )
    assert alertas == []


def test_regressao_negativo_legitimo_nao_alerta(db_session, acao):
    alertas = processar_indicadores_ativo(
        db_session,
        acao,
        {
            "preco": 25.0, "dy": 0.05, "pl": 8.0, "pvp": 1.2, "p_ativo": 0.8,
            "marg_bruta": 0.35, "marg_ebit": 0.20, "marg_liquida": 0.12,
            "p_ebit": 6.0, "ev_ebit": 7.0, "div_liq_patrimonio": 0.8, "psr": 1.5,
            "p_cap_giro": 3.0, "p_at_circ_liq": 2.0, "liq_corrente": 1.5, "roe": -0.10,
            "roa": 0.08, "roic": 0.10, "cagr_rec_5a": 0.15, "liq_media": 500000.0,
            "vpa": 20.0, "lpa": -1.50, "peg_ratio": 1.2, "valor_mercado": 100000000.0,
        },
        "ACAO",
        REF,
        notificar=False,
    )
    assert alertas == []


def test_regressao_nao_muta_dados(db_session, fii):
    dados = _dados_fii(preco=11.50)
    original = dict(dados)
    processar_indicadores_ativo(db_session, fii, _dados_fii(), "FII", REF, notificar=False)
    processar_indicadores_ativo(db_session, fii, dados, "FII", REF, notificar=False)
    assert dados == original


# ===========================================================================
# PREFERENCIAS / ISOLAMENTO / DISPATCHER
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
    chaves = {}
    for nome, papel in (
        ("alice", usuarios.USER),
        ("bob", usuarios.USER),
    ):
        registro = usuarios.criar_usuario(
            nome=nome,
            email=f"{nome}@x.com",
            senha="senha1234",
            papel=papel,
            ativo=True,
            session=sessao,
        )
        usuarios_ids[nome] = registro.id
        chaves[nome] = chaves_api.criar_chave_api(registro, f"chave-{nome}", session=sessao)

    ativo = Ativo(ticker="MXRF11", cnpj="11.111.111/0001-11", tipo=TipoAtivo.FII)
    sessao.add(ativo)
    sessao.commit()
    ativo_id = ativo.id
    sessao.close()

    return {
        "Session": Session,
        "usuarios": usuarios_ids,
        "ativos": {"MXRF11": ativo_id},
        "chaves": chaves,
    }


def _id(ambiente, nome):
    return ambiente["usuarios"][nome]


def _prefere(ambiente, nome, **campos):
    from services import preferencias

    sessao = ambiente["Session"]()
    try:
        usuario = sessao.get(Usuario, _id(ambiente, nome))
        preferencias.atualizar_preferencias(usuario, campos, session=sessao)
    finally:
        sessao.close()


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


def _disparar_mercado(ambiente, preco=11.50, notificar=True):
    sessao = ambiente["Session"]()
    try:
        ativo = sessao.get(Ativo, ambiente["ativos"]["MXRF11"])
        processar_indicadores_ativo(
            sessao, ativo, _dados_fii(), "FII", REF, notificar=False
        )
        return processar_indicadores_ativo(
            sessao, ativo, _dados_fii(preco=preco), "FII", REF, notificar=notificar
        )
    finally:
        sessao.close()


def test_preferencia_bloqueia_alerta(ambiente):
    _seguir_amb(ambiente, "alice")
    _prefere(ambiente, "alice", notificacoes_alertas=False)
    alertas = _disparar_mercado(ambiente)
    assert len(alertas) == 1
    assert _notificacoes(ambiente, "alice") == []


def test_frequencia_desativada_bloqueia_alerta(ambiente):
    _seguir_amb(ambiente, "alice")
    _prefere(ambiente, "alice", frequencia_notificacoes="desativada")
    _disparar_mercado(ambiente)
    assert _notificacoes(ambiente, "alice") == []


def test_mercado_fiis_false_bloqueia_fii(ambiente):
    _seguir_amb(ambiente, "alice")
    _prefere(ambiente, "alice", mercado_fiis=False)
    _disparar_mercado(ambiente)
    assert _notificacoes(ambiente, "alice") == []


def test_isolamento_entre_usuarios(ambiente):
    _seguir_amb(ambiente, "alice")
    _disparar_mercado(ambiente)
    ids = {n.usuario_id for n in _notificacoes(ambiente)}
    assert _id(ambiente, "alice") in ids
    assert _id(ambiente, "bob") not in ids
    assert len(_notificacoes(ambiente, "alice")) == 1
    assert _notificacoes(ambiente, "bob") == []


def test_preferencia_de_alice_nao_silencia_bob(ambiente):
    _seguir_amb(ambiente, "alice")
    _seguir_amb(ambiente, "bob")
    _prefere(ambiente, "alice", notificacoes_alertas=False)
    _disparar_mercado(ambiente)
    assert _notificacoes(ambiente, "alice") == []
    assert len(_notificacoes(ambiente, "bob")) == 1


def test_critico_fura_teto_de_frequencia_diaria(ambiente):
    _seguir_amb(ambiente, "alice")
    _prefere(ambiente, "alice", frequencia_notificacoes="diaria")
    sessao = ambiente["Session"]()
    try:
        ativo = sessao.get(Ativo, ambiente["ativos"]["MXRF11"])
        processar_indicadores_ativo(
            sessao, ativo, _dados_fii(), "FII", REF, notificar=False
        )
        processar_indicadores_ativo(
            sessao, ativo, _dados_fii(preco=11.50), "FII", REF, notificar=True
        )
        assert len(_notificacoes(ambiente, "alice")) == 1
        processar_indicadores_ativo(
            sessao, ativo, _dados_fii(preco=15.00), "FII", REF, notificar=True
        )
    finally:
        sessao.close()
    assert len(_notificacoes(ambiente, "alice")) == 2


def test_critico_respeita_opt_out_explicito(ambiente):
    _seguir_amb(ambiente, "alice")
    _prefere(ambiente, "alice", frequencia_notificacoes="desativada")
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
    assert _notificacoes(ambiente, "alice") == []


def test_dispatcher_entrega_telegram_individual(ambiente, monkeypatch):
    from services import dispatcher_notificacoes

    chamadas = []
    monkeypatch.setattr(
        "bot.loader.enviar_mensagem",
        lambda chat_id, texto, **kwargs: chamadas.append(chat_id) or object(),
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
    assert chamadas == [91001]


def test_dispatcher_nao_usa_telegram_chat_id_legado(ambiente, monkeypatch):
    from services import dispatcher_notificacoes

    chamadas = []
    monkeypatch.setattr(
        "bot.loader.enviar_mensagem",
        lambda chat_id, texto, **kwargs: chamadas.append(chat_id) or object(),
    )
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "777777")
    _seguir_amb(ambiente, "alice")
    _vincular_telegram(ambiente, "alice", 81002, 91002)
    _disparar_mercado(ambiente)
    notif = _notificacoes(ambiente, "alice", "TELEGRAM")[0]
    sessao = ambiente["Session"]()
    try:
        dispatcher_notificacoes.despachar_notificacao(notif.id, session=sessao)
    finally:
        sessao.close()
    assert chamadas == [91002]
    assert 777777 not in chamadas


def test_payload_publica_prioridade(ambiente):
    _seguir_amb(ambiente, "alice")
    _disparar_mercado(ambiente)
    notif = _notificacoes(ambiente, "alice")[0]
    import json

    dados = json.loads(notif.dados)
    assert dados["prioridade"] == PRIORIDADE_MEDIO
    assert dados["tipo_alerta"] == TIPO_MERCADO


def test_decidir_alerta_marca_duplicado(db_session, fii):
    processar_indicadores_ativo(
        db_session, fii, _dados_fii(dy=0.30), "FII", REF, notificar=False
    )
    mudanca = detectar_mudanca(
        db_session, fii, "FII", "dy", 0.30, REF, "Google Sheets"
    )
    decisao = decidir_alerta(db_session, fii, "FII", "dy", 0.30, mudanca)
    assert decisao["relevante"] is False
    assert decisao["duplicado"] is True
    assert decisao["motivo_irrelevante"] == MOTIVO_DUPLICADO
    assert gerar_alerta(
        db_session, fii, "FII", "dy", 0.30, mudanca, REF, decisao=decisao
    ) is None
