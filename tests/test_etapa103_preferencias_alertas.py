"""Testes da Etapa 10.3 — preferências da Fase 6 no gating de alertas.

Cobre consumo real de ``frequencia_notificacoes`` e ``mercado_acoes``/
``mercado_fiis`` na elegibilidade e no dispatcher; volume/dedup por janela;
isolamento A/B; usuário sem vínculo Telegram sem alerta privado; operador
sem fan-out via ``TELEGRAM_CHAT_ID``; regressão do dispatcher. Reusa o
sistema de preferências existente (nenhuma tabela nova).
"""
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api import dependencias, integrar_api
from pipeline_dados.banco_dados import (
    Ativo,
    Base,
    Notificacao,
    TipoAtivo,
    Usuario,
)
from pipeline_dados.motor_alertas import notificar_telegram, processar_indicadores_ativo
from services import (
    ativos_acompanhados,
    chaves_api,
    dispatcher_notificacoes,
    notificacoes,
    preferencias,
    usuarios,
)


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

    app = Flask(__name__)
    app.config["TESTING"] = True
    integrar_api(app, habilitada=True)

    seed = _Semear(Session())
    seed.rodar()

    return {
        "Session": Session,
        "usuarios": seed.usuarios,
        "chaves": seed.chaves,
        "ativos": seed.ativos,
    }


class _Semear:
    def __init__(self, sessao):
        self.sessao = sessao
        self.usuarios = {}
        self.chaves = {}
        self.ativos = {}

    def rodar(self):
        s = self.sessao
        for nome, papel, ativo in (
            ("superadmin", usuarios.SUPERADMIN, True),
            ("admin", usuarios.ADMIN, True),
            ("alice", usuarios.USER, True),
            ("bob", usuarios.USER, True),
            ("visitor", usuarios.VISITOR, True),
        ):
            self.usuarios[nome] = usuarios.criar_usuario(
                nome=nome,
                email=f"{nome}@x.com",
                senha="senha1234",
                papel=papel,
                ativo=ativo,
                session=s,
            )

        ativos = [
            Ativo(ticker="PETR4", cnpj="33.000.167/0001-01", tipo=TipoAtivo.ACAO),
            Ativo(ticker="GARE11", cnpj="00.000.000/0001-11", tipo=TipoAtivo.FII),
        ]
        s.add_all(ativos)
        s.commit()
        self.ativos = {registro.ticker: registro.id for registro in ativos}

        for nome, usuario in self.usuarios.items():
            self.chaves[nome] = chaves_api.criar_chave_api(
                usuario, f"chave-{nome}", session=s
            )
        s.commit()
        self.usuarios = {nome: usuario.id for nome, usuario in self.usuarios.items()}
        s.close()


def _id(ambiente, nome):
    return ambiente["usuarios"][nome]


def _evento(ambiente, tipo="PRECO_ATINGIDO", ativo="PETR4", evento_id=None, **extra):
    corpo = {
        "tipo": tipo,
        "titulo": f"{ativo or 'Sistema'} alerta",
        "mensagem": f"{ativo or 'Sistema'} enviou uma atualização.",
        "evento_id": evento_id,
    }
    if ativo:
        corpo["ativo_id"] = ambiente["ativos"][ativo]
    corpo.update(extra)
    return {chave: valor for chave, valor in corpo.items() if valor is not None}


def _seguir(ambiente, nome, ativo="PETR4"):
    sessao = ambiente["Session"]()
    try:
        usuario = sessao.get(Usuario, _id(ambiente, nome))
        ativos_acompanhados.adicionar_acompanhamento(
            usuario, ambiente["ativos"][ativo], session=sessao
        )
    finally:
        sessao.close()


def _vincular_telegram(ambiente, nome, user_id, chat_id):
    sessao = ambiente["Session"]()
    try:
        usuario = sessao.get(Usuario, _id(ambiente, nome))
        usuarios.vincular_telegram(
            usuario, user_id, telegram_chat_id=chat_id, session=sessao
        )
    finally:
        sessao.close()


def _prefere(ambiente, nome, **campos):
    sessao = ambiente["Session"]()
    try:
        usuario = sessao.get(Usuario, _id(ambiente, nome))
        preferencias.atualizar_preferencias(usuario, campos, session=sessao)
    finally:
        sessao.close()


def _processar(ambiente, evento):
    sessao = ambiente["Session"]()
    try:
        return notificacoes.processar_evento(evento, session=sessao)
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


def _despachar(ambiente, notificacao_id):
    sessao = ambiente["Session"]()
    try:
        return dispatcher_notificacoes.despachar_notificacao(
            notificacao_id, session=sessao
        )
    finally:
        sessao.close()


def _voltar_criado_em(ambiente, nome, delta):
    sessao = ambiente["Session"]()
    try:
        for registro in (
            sessao.query(Notificacao)
            .filter(Notificacao.usuario_id == _id(ambiente, nome))
            .all()
        ):
            registro.criado_em = datetime.now() - delta
        sessao.commit()
    finally:
        sessao.close()


# ==========================================
# FREQUENCIA
# ==========================================


def test_frequencia_desativada_nao_gera(ambiente):
    _seguir(ambiente, "alice")
    _prefere(ambiente, "alice", frequencia_notificacoes="desativada")
    resumo = _processar(ambiente, _evento(ambiente, evento_id="evt-off"))
    assert resumo["elegiveis"] == 0
    assert resumo["geradas"] == 0
    assert _notificacoes(ambiente, "alice") == []


def test_frequencia_imediata_gera_eventos_distintos(ambiente):
    _seguir(ambiente, "alice")
    _prefere(ambiente, "alice", frequencia_notificacoes="imediata")
    assert _processar(ambiente, _evento(ambiente, evento_id="evt-im1"))["geradas"] == 1
    assert _processar(ambiente, _evento(ambiente, evento_id="evt-im2"))["geradas"] == 1
    assert len(_notificacoes(ambiente, "alice")) == 2


def test_frequencia_diaria_bloqueia_segundo_evento_na_janela(ambiente):
    _seguir(ambiente, "alice")
    _prefere(ambiente, "alice", frequencia_notificacoes="diaria")
    assert _processar(ambiente, _evento(ambiente, evento_id="evt-d1"))["geradas"] == 1
    segundo = _processar(ambiente, _evento(ambiente, evento_id="evt-d2"))
    assert segundo["elegiveis"] == 0
    assert segundo["geradas"] == 0
    assert len(_notificacoes(ambiente, "alice")) == 1


def test_frequencia_semanal_bloqueia_segundo_evento_na_janela(ambiente):
    _seguir(ambiente, "alice")
    _prefere(ambiente, "alice", frequencia_notificacoes="semanal")
    assert _processar(ambiente, _evento(ambiente, evento_id="evt-s1"))["geradas"] == 1
    segundo = _processar(ambiente, _evento(ambiente, evento_id="evt-s2"))
    assert segundo["geradas"] == 0
    assert len(_notificacoes(ambiente, "alice")) == 1


def test_frequencia_diaria_libera_apos_janela(ambiente):
    _seguir(ambiente, "alice")
    _prefere(ambiente, "alice", frequencia_notificacoes="diaria")
    assert _processar(ambiente, _evento(ambiente, evento_id="evt-d-old"))["geradas"] == 1
    _voltar_criado_em(ambiente, "alice", timedelta(days=2))
    resumo = _processar(ambiente, _evento(ambiente, evento_id="evt-d-new"))
    assert resumo["geradas"] == 1
    assert len(_notificacoes(ambiente, "alice")) == 2


def test_frequencia_nao_altera_geracao_financeira(ambiente):
    _seguir(ambiente, "alice")
    _prefere(ambiente, "alice", frequencia_notificacoes="desativada")
    sessao = ambiente["Session"]()
    try:
        ativo = sessao.get(Ativo, ambiente["ativos"]["GARE11"])
        dados = {
            "preco": 9.87,
            "pvp": 0.95,
            "dy": 0.12,
            "liquidez": 1500000.0,
            "vpa": 10.39,
            "lucro_12m": 576000000.0,
            "dividendo_mensal": 0.0987,
            "qtd_imoveis": 0,
        }
        processar_indicadores_ativo(
            sessao, ativo, dados, "FII", notificar=False
        )
        alertas = processar_indicadores_ativo(
            sessao, ativo, {**dados, "preco": 11.50}, "FII", notificar=True
        )
        assert len(alertas) == 1
    finally:
        sessao.close()


def test_dispatcher_respeita_frequencia_desativada(ambiente):
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente, evento_id="evt-disp-off"))
    _prefere(ambiente, "alice", frequencia_notificacoes="desativada")
    notif = _notificacoes(ambiente, "alice")[0]
    resumo = _despachar(ambiente, notif.id)
    assert resumo["resultado"] == dispatcher_notificacoes.RESULTADO_FALHA
    assert resumo["motivo"] == "preferencias_desativadas"


# ==========================================
# FILTROS DE MERCADO
# ==========================================


def test_mercado_acoes_false_bloqueia_acao(ambiente):
    _seguir(ambiente, "alice", "PETR4")
    _prefere(ambiente, "alice", mercado_acoes=False, mercado_fiis=True)
    resumo = _processar(ambiente, _evento(ambiente, ativo="PETR4", evento_id="evt-acao"))
    assert resumo["elegiveis"] == 0
    assert resumo["geradas"] == 0


def test_mercado_acoes_false_permite_fii(ambiente):
    _seguir(ambiente, "alice", "GARE11")
    _prefere(ambiente, "alice", mercado_acoes=False, mercado_fiis=True)
    resumo = _processar(
        ambiente, _evento(ambiente, ativo="GARE11", evento_id="evt-fii-ok")
    )
    assert resumo["geradas"] == 1


def test_mercado_fiis_false_bloqueia_fii(ambiente):
    _seguir(ambiente, "alice", "GARE11")
    _prefere(ambiente, "alice", mercado_acoes=True, mercado_fiis=False)
    resumo = _processar(
        ambiente, _evento(ambiente, ativo="GARE11", evento_id="evt-fii-off")
    )
    assert resumo["geradas"] == 0


def test_mercado_fiis_false_permite_acao(ambiente):
    _seguir(ambiente, "alice", "PETR4")
    _prefere(ambiente, "alice", mercado_acoes=True, mercado_fiis=False)
    resumo = _processar(
        ambiente, _evento(ambiente, ativo="PETR4", evento_id="evt-acao-ok")
    )
    assert resumo["geradas"] == 1


def test_evento_sem_ativo_ignora_filtro_de_mercado(ambiente):
    _prefere(ambiente, "alice", mercado_acoes=False, mercado_fiis=False)
    resumo = _processar(
        ambiente,
        _evento(ambiente, ativo=None, tipo="RELATORIO_DISPONIVEL", evento_id="evt-sys"),
    )
    assert resumo["elegiveis"] >= 1
    assert any(n.usuario_id == _id(ambiente, "alice") for n in _notificacoes(ambiente))


def test_dispatcher_respeita_filtro_de_mercado(ambiente):
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente, evento_id="evt-disp-mkt"))
    _prefere(ambiente, "alice", mercado_acoes=False)
    notif = _notificacoes(ambiente, "alice")[0]
    resumo = _despachar(ambiente, notif.id)
    assert resumo["resultado"] == dispatcher_notificacoes.RESULTADO_FALHA
    assert resumo["motivo"] == "mercado_filtrado"


# ==========================================
# ISOLAMENTO
# ==========================================


def test_preferencias_de_alice_nao_afetam_bob(ambiente):
    _seguir(ambiente, "alice")
    _seguir(ambiente, "bob")
    _prefere(ambiente, "alice", frequencia_notificacoes="desativada", mercado_acoes=False)
    resumo = _processar(ambiente, _evento(ambiente, evento_id="evt-iso-pref"))
    ids = {n.usuario_id for n in _notificacoes(ambiente)}
    assert _id(ambiente, "alice") not in ids
    assert _id(ambiente, "bob") in ids
    assert resumo["geradas"] == 1


def test_frequencia_diaria_de_alice_nao_silencia_bob(ambiente):
    _seguir(ambiente, "alice")
    _seguir(ambiente, "bob")
    _prefere(ambiente, "alice", frequencia_notificacoes="diaria")
    _prefere(ambiente, "bob", frequencia_notificacoes="imediata")
    _processar(ambiente, _evento(ambiente, evento_id="evt-iso-d1"))
    _processar(ambiente, _evento(ambiente, evento_id="evt-iso-d2"))
    assert len(_notificacoes(ambiente, "alice")) == 1
    assert len(_notificacoes(ambiente, "bob")) == 2


def test_usuario_sem_vinculo_nao_gera_telegram(ambiente):
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente, evento_id="evt-unlink"))
    canais = {n.canal for n in _notificacoes(ambiente, "alice")}
    assert canais == {"WEB"}
    assert "TELEGRAM" not in canais


def test_usuario_vinculado_recebe_telegram_individual(ambiente, monkeypatch):
    chamadas = []
    monkeypatch.setattr(
        "bot.loader.enviar_mensagem",
        lambda chat_id, texto, **kwargs: chamadas.append(chat_id) or object(),
    )
    _seguir(ambiente, "alice")
    _vincular_telegram(ambiente, "alice", 81001, 91001)
    _processar(ambiente, _evento(ambiente, evento_id="evt-link"))
    notif = _notificacoes(ambiente, "alice", "TELEGRAM")[0]
    resumo = _despachar(ambiente, notif.id)
    assert resumo["entregue"] is True
    assert chamadas == [91001]


# ==========================================
# FAN-OUT / OPERADOR
# ==========================================


def test_notificar_telegram_nao_usa_chat_id_legado():
    alerta = type("A", (), {"indicador": "preco", "telegram_enviado": False})()
    with patch("bot.loader.enviar_mensagem") as mock_env:
        assert notificar_telegram(alerta, "PETR4") is False
    mock_env.assert_not_called()
    assert alerta.telegram_enviado is False


def test_dispatcher_nao_envia_para_telegram_chat_id(ambiente, monkeypatch):
    chamadas = []
    monkeypatch.setattr(
        "bot.loader.enviar_mensagem",
        lambda chat_id, texto, **kwargs: chamadas.append(chat_id) or object(),
    )
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "777777")
    _seguir(ambiente, "alice")
    _vincular_telegram(ambiente, "alice", 81002, 91002)
    _processar(ambiente, _evento(ambiente, evento_id="evt-no-fanout"))
    notif = _notificacoes(ambiente, "alice", "TELEGRAM")[0]
    _despachar(ambiente, notif.id)
    assert chamadas == [91002]
    assert 777777 not in chamadas


def test_admin_operador_nao_recebe_alerta_individual(ambiente):
    _seguir(ambiente, "admin")
    resumo = _processar(ambiente, _evento(ambiente, evento_id="evt-admin"))
    assert resumo["elegiveis"] == 0
    assert _notificacoes(ambiente, "admin") == []


def test_idempotencia_preservada_com_frequencia_imediata(ambiente):
    _seguir(ambiente, "alice")
    evento = _evento(ambiente, evento_id="evt-idem")
    _processar(ambiente, evento)
    resumo = _processar(ambiente, evento)
    assert resumo["geradas"] == 0
    assert resumo["ignoradas"] == 1
    assert len(_notificacoes(ambiente, "alice")) == 1
