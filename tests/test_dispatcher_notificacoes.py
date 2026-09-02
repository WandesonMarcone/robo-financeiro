"""Testes da Fase 6, Etapa 7 — Dispatcher de entrega individual.

Cobrem o dispatcher ``services/dispatcher_notificacoes.py``: entrega WEB
(disponibilidade via API existente), entrega Telegram individual usando apenas o
vínculo existente (``telegram_user_id``/``telegram_chat_id`` — nunca chat id
arbitrário), usuário sem Telegram, Telegram desativado, usuário desativado,
usuário não elegível, isolamento entre usuários, IDOR/BOLA, processamento
duplicado, idempotência, retry, limite de tentativas, falha de Telegram sem
derrubar outros usuários, preferências, ausência de segredos e preservação do
Telegram legado. SQLite em memória.
"""
import hashlib
import json

import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api import dependencias, integrar_api
from modules import seguranca
from pipeline_dados.banco_dados import (
    Ativo,
    AuditoriaAcesso,
    Base,
    Notificacao,
    TipoAtivo,
    Usuario,
)
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
    """Flask app com a API integrada e um SQLite em memória compartilhado."""
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
    cliente = app.test_client()

    seed = _Semear(Session())
    seed.rodar()

    return {
        "cliente": cliente,
        "Session": Session,
        "usuarios": seed.usuarios,
        "chaves": seed.chaves,
        "ativos": seed.ativos,
    }


class _Semear:
    """Popula o banco de testes: usuários de vários papéis + ativos + chaves."""

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
            ("desativado", usuarios.USER, False),
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
            if usuario.ativo:
                self.chaves[nome] = chaves_api.criar_chave_api(
                    usuario, f"chave-{nome}", session=s
                )
            else:
                chave_bruta = f"chave-{nome}-legado"
                s.add(
                    chaves_api.ChaveApi(
                        usuario_id=usuario.id,
                        rotulo=f"chave-{nome}",
                        chave_hash=hashlib.sha256(chave_bruta.encode("utf-8")).hexdigest(),
                        ativa=True,
                    )
                )
                self.chaves[nome] = chave_bruta
        s.commit()
        self.usuarios = {nome: usuario.id for nome, usuario in self.usuarios.items()}
        s.close()


def _h(ambiente, nome):
    return {"X-API-Key": ambiente["chaves"][nome]}


def _id(ambiente, nome):
    return ambiente["usuarios"][nome]


def _usuario(ambiente, nome):
    sessao = ambiente["Session"]()
    try:
        return sessao.get(Usuario, _id(ambiente, nome))
    finally:
        sessao.close()


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
        usuarios.vincular_telegram(usuario, user_id, telegram_chat_id=chat_id, session=sessao)
    finally:
        sessao.close()


def _desativar(ambiente, nome):
    sessao = ambiente["Session"]()
    try:
        usuario = sessao.get(Usuario, _id(ambiente, nome))
        usuarios.desativar_usuario(usuario, session=sessao)
    finally:
        sessao.close()


def _trocar_papel(ambiente, nome, papel):
    sessao = ambiente["Session"]()
    try:
        usuario = sessao.get(Usuario, _id(ambiente, nome))
        usuario.papel = papel
        sessao.commit()
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


def _auditoria(ambiente):
    sessao = ambiente["Session"]()
    try:
        return sessao.query(AuditoriaAcesso).order_by(AuditoriaAcesso.id).all()
    finally:
        sessao.close()


def _texto_auditoria(ambiente):
    return "\n".join(
        f"{evento.acao} {evento.alvo or ''} {evento.detalhe or ''}"
        for evento in _auditoria(ambiente)
    )


def _segredos(ambiente):
    segredos = {"senha1234", "senha_hash", "token_hash", "chave_hash"}
    segredos.update(ambiente["chaves"].values())
    return segredos


def _despachar(ambiente, notificacao_id, forcar=False):
    sessao = ambiente["Session"]()
    try:
        return dispatcher_notificacoes.despachar_notificacao(
            notificacao_id, session=sessao, forcar=forcar
        )
    finally:
        sessao.close()


# ==========================================
# ENTREGA WEB (disponibilidade)
# ==========================================


def test_dispatcher_web_torna_disponivel(ambiente):
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente, evento_id="evt-web"))
    notif = _notificacoes(ambiente, "alice")[0]
    assert notif.canal == "WEB"
    assert notif.status == notificacoes.STATUS_GERADA

    resumo = _despachar(ambiente, notif.id)
    assert resumo["resultado"] == dispatcher_notificacoes.RESULTADO_ENTREGUE
    assert resumo["entregue"] is True
    assert resumo["status"] == notificacoes.STATUS_ENVIADA

    atualizada = _notificacoes(ambiente, "alice")[0]
    assert atualizada.status == notificacoes.STATUS_ENVIADA
    assert atualizada.enviada_em is not None
    assert atualizada.tentativas == 1
    assert "NOTIFICACAO_ENTREGUE" in _texto_auditoria(ambiente)

    resposta = ambiente["cliente"].get(
        "/api/v1/notificacoes", headers=_h(ambiente, "alice")
    )
    assert resposta.status_code == 200
    item = resposta.get_json()["data"][0]
    assert item["status"] == "ENVIADA"
    assert item["tentativas"] == 1
    assert item["enviada_em"] is not None


def test_dispatcher_web_nao_envia_telegram(ambiente, monkeypatch):
    chamadas = []
    monkeypatch.setattr("bot.loader.enviar_mensagem", lambda *a, **k: chamadas.append(a) or None)
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente, evento_id="evt-web2"))
    notif = _notificacoes(ambiente, "alice", "WEB")[0]
    _despachar(ambiente, notif.id)
    assert chamadas == []


# ==========================================
# ENTREGA TELEGRAM INDIVIDUAL
# ==========================================


def test_dispatcher_telegram_entrega_individual(ambiente, monkeypatch):
    chamadas = []
    monkeypatch.setattr(
        "bot.loader.enviar_mensagem",
        lambda chat_id, texto, **kwargs: chamadas.append((chat_id, texto)) or object(),
    )
    _seguir(ambiente, "alice")
    _vincular_telegram(ambiente, "alice", 70001, 71001)
    _processar(ambiente, _evento(ambiente, evento_id="evt-tg"))

    canais = {reg.canal for reg in _notificacoes(ambiente, "alice")}
    assert canais == {"WEB", "TELEGRAM"}

    resumo = dispatcher_notificacoes.despachar_pendentes(session=ambiente["Session"]())
    assert resumo["processadas"] == 2
    assert resumo["entregues"] == 2

    entregues = _notificacoes(ambiente, "alice")
    assert all(reg.status == notificacoes.STATUS_ENVIADA for reg in entregues)
    assert [(chat, texto) for chat, texto in chamadas] == [
        (71001, "[NOTIFICACAO] PETR4 alerta\n\nPETR4 enviou uma atualização.")
    ]
    assert "NOTIFICACAO_ENTREGUE" in _texto_auditoria(ambiente)


def test_dispatcher_telegram_usa_vinculo_nao_legacy(ambiente, monkeypatch):
    chamadas = []
    monkeypatch.setattr(
        "bot.loader.enviar_mensagem",
        lambda chat_id, texto, **kwargs: chamadas.append(chat_id) or object(),
    )
    _seguir(ambiente, "alice")
    _vincular_telegram(ambiente, "alice", 70002, 71002)
    _processar(ambiente, _evento(ambiente, evento_id="evt-tg2"))
    notif = _notificacoes(ambiente, "alice", "TELEGRAM")[0]
    _despachar(ambiente, notif.id)
    assert chamadas == [71002]
    assert 71002 not in (None, "71002")


# ==========================================
# USUÁRIO SEM TELEGRAM / TELEGRAM DESATIVADO
# ==========================================


def test_usuario_sem_telegram_nao_envia(ambiente, monkeypatch):
    chamadas = []
    monkeypatch.setattr("bot.loader.enviar_mensagem", lambda *a, **k: chamadas.append(a) or None)
    _seguir(ambiente, "alice")
    _vincular_telegram(ambiente, "alice", 70003, 71003)
    _processar(ambiente, _evento(ambiente, evento_id="evt-sem-tg"))

    sessao = ambiente["Session"]()
    try:
        usuario = sessao.get(Usuario, _id(ambiente, "alice"))
        usuarios.desvincular_telegram(usuario, session=sessao)
    finally:
        sessao.close()

    notif = _notificacoes(ambiente, "alice", "TELEGRAM")[0]
    resumo = _despachar(ambiente, notif.id)
    assert resumo["resultado"] == dispatcher_notificacoes.RESULTADO_FALHA
    assert resumo["motivo"] == "telegram_sem_vinculo"
    assert _notificacoes(ambiente, "alice", "TELEGRAM")[0].status == notificacoes.STATUS_FALHA
    assert chamadas == []


def test_telegram_desativado_nao_envia(ambiente, monkeypatch):
    chamadas = []
    monkeypatch.setattr("bot.loader.enviar_mensagem", lambda *a, **k: chamadas.append(a) or None)
    _seguir(ambiente, "alice")
    _vincular_telegram(ambiente, "alice", 70004, 71004)
    _processar(ambiente, _evento(ambiente, evento_id="evt-tg-off"))
    _prefere(ambiente, "alice", telegram_ativo=False)
    notif = _notificacoes(ambiente, "alice", "TELEGRAM")[0]
    resumo = _despachar(ambiente, notif.id)
    assert resumo["motivo"] == "telegram_desativado"
    assert _notificacoes(ambiente, "alice", "TELEGRAM")[0].status == notificacoes.STATUS_FALHA
    assert chamadas == []


def test_telegram_sem_chat_id_nao_envia(ambiente, monkeypatch):
    chamadas = []
    monkeypatch.setattr("bot.loader.enviar_mensagem", lambda *a, **k: chamadas.append(a) or None)
    _seguir(ambiente, "alice")
    _vincular_telegram(ambiente, "alice", 70005, 71005)
    _processar(ambiente, _evento(ambiente, evento_id="evt-tg-chat"))
    sessao = ambiente["Session"]()
    try:
        usuario = sessao.get(Usuario, _id(ambiente, "alice"))
        usuario.telegram_chat_id = None
        sessao.commit()
    finally:
        sessao.close()
    notif = _notificacoes(ambiente, "alice", "TELEGRAM")[0]
    resumo = _despachar(ambiente, notif.id)
    assert resumo["motivo"] == "telegram_sem_chat"
    assert chamadas == []


# ==========================================
# USUÁRIO DESATIVADO / NÃO ELEGÍVEL / PREFERÊNCIAS
# ==========================================


def test_usuario_desativado_nao_recebe(ambiente, monkeypatch):
    chamadas = []
    monkeypatch.setattr("bot.loader.enviar_mensagem", lambda *a, **k: chamadas.append(a) or None)
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente, evento_id="evt-inat"))
    _desativar(ambiente, "alice")
    notif = _notificacoes(ambiente, "alice")[0]
    resumo = _despachar(ambiente, notif.id)
    assert resumo["resultado"] == dispatcher_notificacoes.RESULTADO_FALHA
    assert resumo["motivo"] == "usuario_desativado"
    assert _notificacoes(ambiente, "alice")[0].status == notificacoes.STATUS_FALHA
    assert chamadas == []


def test_usuario_nao_elegivel_nao_recebe(ambiente, monkeypatch):
    chamadas = []
    monkeypatch.setattr("bot.loader.enviar_mensagem", lambda *a, **k: chamadas.append(a) or None)
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente, evento_id="evt-naoel"))
    _trocar_papel(ambiente, "alice", usuarios.VISITOR)
    notif = _notificacoes(ambiente, "alice")[0]
    resumo = _despachar(ambiente, notif.id)
    assert resumo["resultado"] == dispatcher_notificacoes.RESULTADO_FALHA
    assert resumo["motivo"] == "usuario_nao_elegivel"
    assert chamadas == []


def test_preferencias_mestre_desativadas(ambiente, monkeypatch):
    chamadas = []
    monkeypatch.setattr("bot.loader.enviar_mensagem", lambda *a, **k: chamadas.append(a) or None)
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente, evento_id="evt-master"))
    _prefere(ambiente, "alice", notificacoes_ativas=False)
    notif = _notificacoes(ambiente, "alice")[0]
    resumo = _despachar(ambiente, notif.id)
    assert resumo["motivo"] == "preferencias_desativadas"
    assert chamadas == []


def test_preferencia_do_tipo_desativada(ambiente, monkeypatch):
    chamadas = []
    monkeypatch.setattr("bot.loader.enviar_mensagem", lambda *a, **k: chamadas.append(a) or None)
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente, tipo="DIVIDENDO", evento_id="evt-div"))
    _prefere(ambiente, "alice", notificacoes_dividendos=False)
    notif = _notificacoes(ambiente, "alice")[0]
    resumo = _despachar(ambiente, notif.id)
    assert resumo["motivo"] == "preferencias_desativadas"
    assert chamadas == []


def test_preferencias_respeitadas_quando_ativas(ambiente, monkeypatch):
    chamadas = []
    monkeypatch.setattr(
        "bot.loader.enviar_mensagem",
        lambda chat_id, texto, **kwargs: chamadas.append(chat_id) or object(),
    )
    _seguir(ambiente, "alice")
    _vincular_telegram(ambiente, "alice", 70006, 71006)
    _processar(ambiente, _evento(ambiente, tipo="DIVIDENDO", evento_id="evt-div2"))
    resumo = dispatcher_notificacoes.despachar_pendentes(session=ambiente["Session"]())
    assert resumo["entregues"] == 2
    assert len(chamadas) == 1


# ==========================================
# ISOLAMENTO ENTRE USUÁRIOS E IDOR/BOLA
# ==========================================


def test_isolamento_entre_usuarios(ambiente, monkeypatch):
    chamadas = []
    monkeypatch.setattr(
        "bot.loader.enviar_mensagem",
        lambda chat_id, texto, **kwargs: chamadas.append(chat_id) or object(),
    )
    _seguir(ambiente, "alice")
    _seguir(ambiente, "bob")
    _vincular_telegram(ambiente, "alice", 70007, 71007)
    _vincular_telegram(ambiente, "bob", 70008, 71008)
    _processar(ambiente, _evento(ambiente, evento_id="evt-iso"))

    resumo = dispatcher_notificacoes.despachar_pendentes(session=ambiente["Session"]())
    assert resumo["processadas"] == 4
    assert resumo["entregues"] == 4

    chamadas_set = set(chamadas)
    assert chamadas_set == {71007, 71008}
    assert _notificacoes(ambiente, "alice", "TELEGRAM")[0].status == notificacoes.STATUS_ENVIADA
    assert _notificacoes(ambiente, "bob", "TELEGRAM")[0].status == notificacoes.STATUS_ENVIADA


def test_idor_bola_dados_nao_alteram_destinatario(ambiente, monkeypatch):
    chamadas = []
    monkeypatch.setattr(
        "bot.loader.enviar_mensagem",
        lambda chat_id, texto, **kwargs: chamadas.append(chat_id) or object(),
    )
    _seguir(ambiente, "alice")
    _vincular_telegram(ambiente, "alice", 70009, 71009)
    _processar(
        ambiente,
        _evento(
            ambiente,
            evento_id="evt-idor",
            dados={
                "telegram_chat_id": 999999,
                "usuario_id": 12345,
                "destinatario": "hacker@x.com",
                "canal": "TELEGRAM",
            },
        ),
    )
    notif = _notificacoes(ambiente, "alice", "TELEGRAM")[0]
    assert notif.canal == "TELEGRAM"
    resumo = _despachar(ambiente, notif.id)
    assert resumo["entregue"] is True
    assert chamadas == [71009]
    assert 999999 not in chamadas


def test_despachar_nao_aceita_usuario_id_cliente(ambiente, monkeypatch):
    """O destinatário é sempre ``Notificacao.usuario_id`` (dono)."""
    chamadas = []
    monkeypatch.setattr(
        "bot.loader.enviar_mensagem",
        lambda chat_id, texto, **kwargs: chamadas.append(chat_id) or object(),
    )
    _seguir(ambiente, "alice")
    _seguir(ambiente, "bob")
    _vincular_telegram(ambiente, "alice", 70010, 71010)
    _vincular_telegram(ambiente, "bob", 70011, 71011)
    _processar(ambiente, _evento(ambiente, evento_id="evt-owner"))

    notif_bob = _notificacoes(ambiente, "bob", "TELEGRAM")[0]
    resumo = _despachar(ambiente, notif_bob.id)
    assert resumo["usuario_id"] == _id(ambiente, "bob")
    assert chamadas == [71011]


# ==========================================
# IDEMPOTÊNCIA E DUPLICIDADE
# ==========================================


def test_processamento_duplicado_nao_reenvia(ambiente, monkeypatch):
    chamadas = []
    monkeypatch.setattr(
        "bot.loader.enviar_mensagem",
        lambda chat_id, texto, **kwargs: chamadas.append(chat_id) or object(),
    )
    _seguir(ambiente, "alice")
    _vincular_telegram(ambiente, "alice", 70012, 71012)
    _processar(ambiente, _evento(ambiente, evento_id="evt-dupl"))
    notif = _notificacoes(ambiente, "alice", "TELEGRAM")[0]

    primeiro = _despachar(ambiente, notif.id)
    segundo = _despachar(ambiente, notif.id)

    assert primeiro["entregue"] is True
    assert segundo["resultado"] == dispatcher_notificacoes.RESULTADO_IGNORADA
    assert segundo["motivo"] == "ja_entregue"
    assert chamadas == [71012]


def test_idempotencia_apos_reinicio(ambiente, monkeypatch):
    chamadas = []
    monkeypatch.setattr(
        "bot.loader.enviar_mensagem",
        lambda chat_id, texto, **kwargs: chamadas.append(chat_id) or object(),
    )
    _seguir(ambiente, "alice")
    _vincular_telegram(ambiente, "alice", 70013, 71013)
    _processar(ambiente, _evento(ambiente, evento_id="evt-restart"))
    notif = _notificacoes(ambiente, "alice", "TELEGRAM")[0]

    _despachar(ambiente, notif.id)

    nova_sessao = ambiente["Session"]()
    try:
        resumo = dispatcher_notificacoes.despachar_notificacao(notif.id, session=nova_sessao)
    finally:
        nova_sessao.close()
    assert resumo["resultado"] == dispatcher_notificacoes.RESULTADO_IGNORADA
    assert resumo["motivo"] == "ja_entregue"
    assert chamadas == [71013]


def test_falha_permanente_nao_reprocessada(ambiente, monkeypatch):
    chamadas = []
    monkeypatch.setattr("bot.loader.enviar_mensagem", lambda *a, **k: chamadas.append(a) or None)
    _seguir(ambiente, "alice")
    _vincular_telegram(ambiente, "alice", 70014, 71014)
    _processar(ambiente, _evento(ambiente, evento_id="evt-falha-perm"))
    _prefere(ambiente, "alice", telegram_ativo=False)
    notif = _notificacoes(ambiente, "alice", "TELEGRAM")[0]

    primeiro = _despachar(ambiente, notif.id)
    segundo = _despachar(ambiente, notif.id)

    assert primeiro["resultado"] == dispatcher_notificacoes.RESULTADO_FALHA
    assert segundo["resultado"] == dispatcher_notificacoes.RESULTADO_IGNORADA
    assert segundo["motivo"] == "falha_permanente"
    assert chamadas == []


def test_notificacao_inexistente(ambiente):
    resumo = _despachar(ambiente, 999999)
    assert resumo["resultado"] == dispatcher_notificacoes.RESULTADO_IGNORADA
    assert resumo["motivo"] == "nao_encontrada"


# ==========================================
# RETRY E LIMITE DE TENTATIVAS
# ==========================================


def test_retry_transitorio_agenda_tentativa(ambiente, monkeypatch):
    chamadas = []
    monkeypatch.setattr("bot.loader.enviar_mensagem", lambda *a, **k: chamadas.append(a) or None)
    _seguir(ambiente, "alice")
    _vincular_telegram(ambiente, "alice", 70015, 71015)
    _processar(ambiente, _evento(ambiente, evento_id="evt-retry"))
    notif = _notificacoes(ambiente, "alice", "TELEGRAM")[0]

    resumo = _despachar(ambiente, notif.id)
    assert resumo["resultado"] == dispatcher_notificacoes.RESULTADO_RETRY
    assert resumo["tentativas"] == 1

    atualizada = _notificacoes(ambiente, "alice", "TELEGRAM")[0]
    assert atualizada.status == notificacoes.STATUS_GERADA
    assert atualizada.proxima_tentativa is not None
    assert atualizada.ultimo_erro == "falha_transitoria"


def test_retry_respeita_janela_agendada(ambiente, monkeypatch):
    chamadas = []
    monkeypatch.setattr("bot.loader.enviar_mensagem", lambda *a, **k: chamadas.append(a) or None)
    _seguir(ambiente, "alice")
    _vincular_telegram(ambiente, "alice", 70016, 71016)
    _processar(ambiente, _evento(ambiente, evento_id="evt-retry2"))
    notif = _notificacoes(ambiente, "alice", "TELEGRAM")[0]

    _despachar(ambiente, notif.id)
    tentativas_antes = _notificacoes(ambiente, "alice", "TELEGRAM")[0].tentativas

    dentro_da_janela = _despachar(ambiente, notif.id)
    assert dentro_da_janela["resultado"] == dispatcher_notificacoes.RESULTADO_IGNORADA
    assert dentro_da_janela["motivo"] == "aguardando_retry"
    assert _notificacoes(ambiente, "alice", "TELEGRAM")[0].tentativas == tentativas_antes


def test_retry_forcado_reprocessa(ambiente, monkeypatch):
    chamadas = []
    monkeypatch.setattr("bot.loader.enviar_mensagem", lambda *a, **k: chamadas.append(a) or None)
    _seguir(ambiente, "alice")
    _vincular_telegram(ambiente, "alice", 70017, 71017)
    _processar(ambiente, _evento(ambiente, evento_id="evt-retry3"))
    notif = _notificacoes(ambiente, "alice", "TELEGRAM")[0]

    _despachar(ambiente, notif.id)
    forcado = _despachar(ambiente, notif.id, forcar=True)
    assert forcado["resultado"] == dispatcher_notificacoes.RESULTADO_RETRY
    assert forcado["tentativas"] == 2


def test_limite_de_tentativas_marca_falha(ambiente, monkeypatch):
    chamadas = []
    monkeypatch.setattr("bot.loader.enviar_mensagem", lambda *a, **k: chamadas.append(a) or None)
    _seguir(ambiente, "alice")
    _vincular_telegram(ambiente, "alice", 70018, 71018)
    _processar(ambiente, _evento(ambiente, evento_id="evt-limit"))
    notif = _notificacoes(ambiente, "alice", "TELEGRAM")[0]

    _despachar(ambiente, notif.id)
    _despachar(ambiente, notif.id, forcar=True)
    final = _despachar(ambiente, notif.id, forcar=True)

    assert final["resultado"] == dispatcher_notificacoes.RESULTADO_FALHA
    assert final["tentativas"] == dispatcher_notificacoes.MAX_TENTATIVAS
    assert _notificacoes(ambiente, "alice", "TELEGRAM")[0].status == notificacoes.STATUS_FALHA
    assert "NOTIFICACAO_ENTREGA_FALHOU" in _texto_auditoria(ambiente)


def test_despachar_pendentes_nao_reprocessa_retry_futuro(ambiente, monkeypatch):
    chamadas = []
    monkeypatch.setattr("bot.loader.enviar_mensagem", lambda *a, **k: chamadas.append(a) or None)
    _seguir(ambiente, "alice")
    _vincular_telegram(ambiente, "alice", 70019, 71019)
    _processar(ambiente, _evento(ambiente, evento_id="evt-batch"))
    notif = _notificacoes(ambiente, "alice", "TELEGRAM")[0]

    _despachar(ambiente, notif.id)
    resumo = dispatcher_notificacoes.despachar_pendentes(session=ambiente["Session"]())
    processados = resumo["notificacoes"]
    assert len(processados) == 1
    assert processados[0]["canal"] == "WEB"
    assert processados[0]["resultado"] == dispatcher_notificacoes.RESULTADO_ENTREGUE


# ==========================================
# FALHA DE TELEGRAM NÃO DERRUBA OUTROS USUÁRIOS
# ==========================================


def test_falha_telegram_nao_interrompe_outros(ambiente, monkeypatch):
    chamadas = []

    def _fake(chat_id, texto, **kwargs):
        chamadas.append(chat_id)
        if chat_id == 71020:
            return None
        return object()

    monkeypatch.setattr("bot.loader.enviar_mensagem", _fake)
    _seguir(ambiente, "alice")
    _seguir(ambiente, "bob")
    _vincular_telegram(ambiente, "alice", 70020, 71020)
    _vincular_telegram(ambiente, "bob", 70021, 71021)
    _processar(ambiente, _evento(ambiente, evento_id="evt-fail-iso"))

    resumo = dispatcher_notificacoes.despachar_pendentes(session=ambiente["Session"]())
    assert resumo["processadas"] == 4
    assert resumo["entregues"] == 3
    assert resumo["retries"] == 1

    assert _notificacoes(ambiente, "alice", "TELEGRAM")[0].status == notificacoes.STATUS_GERADA
    assert _notificacoes(ambiente, "bob", "TELEGRAM")[0].status == notificacoes.STATUS_ENVIADA
    assert _notificacoes(ambiente, "alice", "WEB")[0].status == notificacoes.STATUS_ENVIADA
    assert _notificacoes(ambiente, "bob", "WEB")[0].status == notificacoes.STATUS_ENVIADA


# ==========================================
# PIPELINE INTEGRADO
# ==========================================


def test_processar_evento_e_despachar(ambiente, monkeypatch):
    chamadas = []
    monkeypatch.setattr(
        "bot.loader.enviar_mensagem",
        lambda chat_id, texto, **kwargs: chamadas.append(chat_id) or object(),
    )
    _seguir(ambiente, "alice")
    _vincular_telegram(ambiente, "alice", 70022, 71022)
    sessao = ambiente["Session"]()
    try:
        resultado = dispatcher_notificacoes.processar_evento_e_despachar(
            _evento(ambiente, evento_id="evt-pipe"), session=sessao
        )
    finally:
        sessao.close()

    assert resultado["geracao"]["geradas"] == 2
    assert resultado["entrega"]["entregues"] == 2
    assert chamadas == [71022]
    assert all(
        reg.status == notificacoes.STATUS_ENVIADA
        for reg in _notificacoes(ambiente, "alice")
    )


# ==========================================
# AUSÊNCIA DE SEGREDOS
# ==========================================


def test_nenhum_segredo_no_banco_auditoria_ou_erro(ambiente, monkeypatch):
    monkeypatch.setattr("bot.loader.enviar_mensagem", lambda *a, **k: None)
    _seguir(ambiente, "alice")
    _vincular_telegram(ambiente, "alice", 70023, 71023)
    _processar(
        ambiente,
        _evento(
            ambiente,
            evento_id="evt-secret",
            dados={"token": "tok-secreto", "api_key": "key-secreta"},
        ),
    )
    _despachar(ambiente, _notificacoes(ambiente, "alice", "TELEGRAM")[0].id)

    texto_auditoria = _texto_auditoria(ambiente)
    for segredo in _segredos(ambiente):
        assert segredo not in texto_auditoria
    assert "tok-secreto" not in texto_auditoria
    assert "key-secreta" not in texto_auditoria

    for registro in _notificacoes(ambiente, "alice"):
        assert registro.ultimo_erro is None or "secret" not in registro.ultimo_erro
        assert registro.titulo not in ("tok-secreto", "key-secreta")


def test_nenhum_segredo_na_resposta_api(ambiente):
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente, evento_id="evt-api-seg"))
    _despachar(ambiente, _notificacoes(ambiente, "alice")[0].id)
    corpo = ambiente["cliente"].get(
        "/api/v1/notificacoes", headers=_h(ambiente, "alice")
    ).get_data(as_text=True)
    for segredo in _segredos(ambiente):
        assert segredo not in corpo
    assert "chave_hash" not in corpo
    assert "senha_hash" not in corpo


# ==========================================
# PRESERVAÇÃO DO TELEGRAM LEGADO
# ==========================================


def test_telegram_legado_preservado(monkeypatch):
    def _falha(*args, **kwargs):
        raise RuntimeError("banco indisponível (simulado)")

    monkeypatch.setattr("atualizador_documentos.SessionDB", _falha)
    monkeypatch.setenv("SUPERADMIN_CHAT_IDS", "9001")
    monkeypatch.setenv("ADMIN_CHAT_IDS", "9002")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "9003")

    assert seguranca.eh_superadmin(9001) is True
    assert seguranca.eh_admin(9002) is True
    assert seguranca.eh_superadmin(9003) is True
    assert seguranca.papel_do_usuario(9099) == seguranca.ROLE_USER


def test_dispatcher_nao_usa_telegram_chat_id_legado(ambiente, monkeypatch):
    chamadas = []
    monkeypatch.setattr(
        "bot.loader.enviar_mensagem",
        lambda chat_id, texto, **kwargs: chamadas.append(chat_id) or object(),
    )
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "777777")
    _seguir(ambiente, "alice")
    _vincular_telegram(ambiente, "alice", 70024, 71024)
    _processar(ambiente, _evento(ambiente, evento_id="evt-legacy"))
    notif = _notificacoes(ambiente, "alice", "TELEGRAM")[0]
    _despachar(ambiente, notif.id)
    assert chamadas == [71024]
    assert 777777 not in chamadas


def test_dados_sanitizados_motor_mantidos(ambiente):
    _seguir(ambiente, "alice")
    _processar(
        ambiente,
        _evento(
            ambiente,
            evento_id="evt-dados",
            dados={"preco": "20.00", "token": "abc-secreto", "api_key": "xyz-secreto"},
        ),
    )
    _despachar(ambiente, _notificacoes(ambiente, "alice")[0].id)
    registro = _notificacoes(ambiente, "alice")[0]
    armazenado = json.loads(registro.dados)
    assert armazenado["preco"] == "20.00"
    assert armazenado["token"] == "[OCULTO]"
    assert armazenado["api_key"] == "[OCULTO]"


# ==========================================
# INTEGRAÇÃO COM O AGENDADOR (Fase 6, Etapa 7)
# ==========================================
# O dispatcher passa a ser processado automaticamente por um job aditivo no
# BackgroundScheduler existente (main.py). Estes testes provam que o ciclo
# automático é seguro (nunca levanta), que o registro no scheduler reutiliza o
# agendador existente sem duplicar jobs e que a integração é desativável.


def test_ciclo_automatico_processa_pendentes(ambiente, monkeypatch):
    chamadas = []
    monkeypatch.setattr(
        "bot.loader.enviar_mensagem",
        lambda chat_id, texto, **kwargs: chamadas.append(chat_id) or object(),
    )
    _seguir(ambiente, "alice")
    _vincular_telegram(ambiente, "alice", 70025, 71025)
    _processar(ambiente, _evento(ambiente, evento_id="evt-ciclo"))

    resumo = dispatcher_notificacoes.executar_ciclo_pendentes(
        session=ambiente["Session"]()
    )
    assert resumo["processadas"] == 2
    assert resumo["entregues"] == 2
    assert resumo["falhas"] == 0
    assert resumo["retries"] == 0
    assert chamadas == [71025]
    assert all(
        reg.status == notificacoes.STATUS_ENVIADA
        for reg in _notificacoes(ambiente, "alice")
    )


def test_ciclo_automatico_nunca_lanca(ambiente, monkeypatch):
    def _explode(*args, **kwargs):
        raise RuntimeError("falha simulada no despacho")

    monkeypatch.setattr(dispatcher_notificacoes, "despachar_pendentes", _explode)
    resumo = dispatcher_notificacoes.executar_ciclo_pendentes()
    assert resumo["processadas"] == 0
    assert resumo["entregues"] == 0
    assert resumo["falhas"] == 1
    assert resumo["retries"] == 0
    assert resumo["ignoradas"] == 0


def test_registro_no_scheduler_reutiliza_existente_e_nao_duplica():
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler()
    try:
        primeiro = dispatcher_notificacoes.registrar_dispatcher_no_scheduler(
            scheduler, interval_minutos=7
        )
        assert primeiro is True

        jobs = scheduler.get_jobs()
        assert len(jobs) == 1
        job = jobs[0]
        assert job.id == dispatcher_notificacoes.JOB_DISPATCHER_ID
        assert job.max_instances == 1
        assert job.coalesce is True
        assert job.func == dispatcher_notificacoes.executar_ciclo_pendentes
        assert job.trigger.interval.total_seconds() == 7 * 60

        segundo = dispatcher_notificacoes.registrar_dispatcher_no_scheduler(
            scheduler, interval_minutos=7
        )
        assert segundo is False
        assert len(scheduler.get_jobs()) == 1
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)


def test_registro_no_scheduler_desativavel_e_intervalo_invalido():
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler()
    try:
        desativado = dispatcher_notificacoes.registrar_dispatcher_no_scheduler(
            scheduler, ativo=False
        )
        assert desativado is False
        assert scheduler.get_jobs() == []

        com_intervalo_padrao = (
            dispatcher_notificacoes.registrar_dispatcher_no_scheduler(scheduler)
        )
        assert com_intervalo_padrao is True
        job = scheduler.get_job(dispatcher_notificacoes.JOB_DISPATCHER_ID)
        assert (
            job.trigger.interval.total_seconds()
            == dispatcher_notificacoes.INTERVALO_PADRAO_MINUTOS * 60
        )

        sem_scheduler = dispatcher_notificacoes.registrar_dispatcher_no_scheduler(None)
        assert sem_scheduler is False
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
