"""Testes da Fase 6, Etapa 5 — Preferências individuais do usuário.

Cobrem a camada central ``services/preferencias.py`` e os endpoints
``/api/v1/preferencias`` (GET, PATCH e POST restaurar): criação com defaults
seguros, atualização parcial validada rigorosamente (booleanos, enums de
frequência, campos proibidos/desconhecidos e nulos), isolamento 1:1 entre
usuários, proteção contra ``usuario_id`` vindo do cliente (anti-IDOR/BOLA),
autorização exclusivamente pela matriz central, ``UNIQUE(usuario_id)``,
comportamento de VISITOR/desativado, ausência de segredos e auditoria.
"""
import hashlib

import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api import dependencias, integrar_api
from pipeline_dados.banco_dados import (
    AuditoriaAcesso,
    Base,
    PreferenciasUsuario,
    Usuario,
)
from services import autorizacao, chaves_api, preferencias, usuarios


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
    }


class _Semear:
    """Popula o banco de testes com usuários de vários papéis + API Keys."""

    def __init__(self, sessao):
        self.sessao = sessao
        self.usuarios = {}
        self.chaves = {}

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


def _linha(Session, usuario_id):
    sessao = Session()
    try:
        return (
            sessao.query(PreferenciasUsuario)
            .filter(PreferenciasUsuario.usuario_id == usuario_id)
            .first()
        )
    finally:
        sessao.close()


def _auditoria(Session):
    sessao = Session()
    try:
        return sessao.query(AuditoriaAcesso).order_by(AuditoriaAcesso.id).all()
    finally:
        sessao.close()


def _texto_auditoria(ambiente):
    return "\n".join(
        f"{evento.acao} {evento.alvo or ''} {evento.detalhe or ''}"
        for evento in _auditoria(ambiente["Session"])
    )


def _segredos(ambiente):
    """Segredos que nunca podem aparecer em respostas/auditoria."""
    segredos = {"senha1234", "senha_hash", "token_hash", "chave_hash"}
    segredos.update(ambiente["chaves"].values())
    return segredos


# ==========================================
# SERVIÇO: CONSULTA E CRIAÇÃO
# ==========================================


def test_buscar_preferencias_sem_registro_retorna_none(ambiente):
    alice = _usuario(ambiente, "alice")
    sessao = ambiente["Session"]()
    try:
        assert preferencias.buscar_preferencias(alice, session=sessao) is None
    finally:
        sessao.close()


def test_obter_ou_criar_preferencias_cria_com_defaults(ambiente):
    alice = _usuario(ambiente, "alice")
    sessao = ambiente["Session"]()
    try:
        registro = preferencias.obter_ou_criar_preferencias(alice, session=sessao)
        assert registro.usuario_id == _id(ambiente, "alice")
        for campo, valor in preferencias.preferencias_padrao().items():
            assert getattr(registro, campo) == valor, campo
    finally:
        sessao.close()


def test_obter_ou_criar_preferencias_nao_cria_duplicidade(ambiente):
    alice = _usuario(ambiente, "alice")
    sessao = ambiente["Session"]()
    try:
        primeira = preferencias.obter_ou_criar_preferencias(alice, session=sessao)
        segunda = preferencias.obter_ou_criar_preferencias(alice, session=sessao)
        assert primeira.id == segunda.id
        sessao.expire_all()
        assert sessao.query(PreferenciasUsuario).count() == 1
    finally:
        sessao.close()


def test_obter_ou_criar_preferencias_negado_sem_permissao(ambiente):
    visitor = _usuario(ambiente, "visitor")
    sessao = ambiente["Session"]()
    try:
        with pytest.raises(autorizacao.PermissaoNegadaError):
            preferencias.obter_ou_criar_preferencias(visitor, session=sessao)
    finally:
        sessao.close()


def test_obter_ou_criar_preferencias_negado_desativado(ambiente):
    desativado = _usuario(ambiente, "desativado")
    sessao = ambiente["Session"]()
    try:
        with pytest.raises(autorizacao.PermissaoNegadaError):
            preferencias.obter_ou_criar_preferencias(desativado, session=sessao)
    finally:
        sessao.close()


def test_obter_ou_criar_preferencias_negado_usuario_none(ambiente):
    sessao = ambiente["Session"]()
    try:
        with pytest.raises(autorizacao.PermissaoNegadaError):
            preferencias.obter_ou_criar_preferencias(None, session=sessao)
    finally:
        sessao.close()


def test_preferencias_padrao_e_seguro(ambiente):
    defaults = preferencias.preferencias_padrao()
    for campo in ("notificacoes_ativas", "notificacoes_preco", "telegram_ativo"):
        assert defaults[campo] is True
    assert defaults["frequencia_notificacoes"] == "imediata"
    assert defaults["frequencia_relatorios"] == "semanal"
    for proibido in ("usuario_id", "id", "criado_em", "atualizado_em"):
        assert proibido not in defaults


# ==========================================
# SERVIÇO: ATUALIZAÇÃO E VALIDAÇÃO
# ==========================================


def test_atualizar_preferencias_aplica_campos_validos(ambiente):
    alice = _usuario(ambiente, "alice")
    sessao = ambiente["Session"]()
    try:
        registro = preferencias.atualizar_preferencias(
            alice,
            {"notificacoes_preco": False, "frequencia_relatorios": "mensal"},
            session=sessao,
        )
        assert registro.notificacoes_preco is False
        assert registro.frequencia_relatorios == "mensal"
        assert registro.notificacoes_ativas is True
    finally:
        sessao.close()


def test_atualizar_preferencias_cria_linha_quando_ausente(ambiente):
    bob = _usuario(ambiente, "bob")
    sessao = ambiente["Session"]()
    try:
        preferencias.atualizar_preferencias(bob, {"web_ativo": False}, session=sessao)
        sessao.expire_all()
        assert _linha(ambiente["Session"], _id(ambiente, "bob")).web_ativo is False
    finally:
        sessao.close()


@pytest.mark.parametrize("valor", [0, 1, "true", "false", None])
def test_atualizar_preferencias_rejeita_booleano_invalido(ambiente, valor):
    alice = _usuario(ambiente, "alice")
    sessao = ambiente["Session"]()
    try:
        with pytest.raises(ValueError):
            preferencias.atualizar_preferencias(
                alice, {"notificacoes_preco": valor}, session=sessao
            )
    finally:
        sessao.close()


def test_atualizar_preferencias_rejeita_frequencia_invalida(ambiente):
    alice = _usuario(ambiente, "alice")
    sessao = ambiente["Session"]()
    try:
        for campo, valor in (
            ("frequencia_notificacoes", "mensal"),
            ("frequencia_notificacoes", "nunca"),
            ("frequencia_relatorios", "anual"),
            ("frequencia_relatorios", 5),
        ):
            with pytest.raises(ValueError):
                preferencias.atualizar_preferencias(
                    alice, {campo: valor}, session=sessao
                )
    finally:
        sessao.close()


def test_atualizar_preferencias_aceita_frequencia_com_maiusculas(ambiente):
    alice = _usuario(ambiente, "alice")
    sessao = ambiente["Session"]()
    try:
        registro = preferencias.atualizar_preferencias(
            alice,
            {"frequencia_notificacoes": "SEMANAL", "frequencia_relatorios": "Mensal"},
            session=sessao,
        )
        assert registro.frequencia_notificacoes == "semanal"
        assert registro.frequencia_relatorios == "mensal"
    finally:
        sessao.close()


def test_atualizar_preferencias_rejeita_campo_desconhecido(ambiente):
    alice = _usuario(ambiente, "alice")
    sessao = ambiente["Session"]()
    try:
        with pytest.raises(ValueError):
            preferencias.atualizar_preferencias(
                alice, {"modo_escuro": True}, session=sessao
            )
    finally:
        sessao.close()


@pytest.mark.parametrize("campo", ["id", "usuario_id", "criado_em", "atualizado_em"])
def test_atualizar_preferencias_rejeita_campos_proibidos(ambiente, campo):
    alice = _usuario(ambiente, "alice")
    sessao = ambiente["Session"]()
    try:
        with pytest.raises(ValueError):
            preferencias.atualizar_preferencias(
                alice, {campo: 123}, session=sessao
            )
    finally:
        sessao.close()


def test_atualizar_preferencias_rejeita_usuario_id_de_outro(ambiente):
    alice = _usuario(ambiente, "alice")
    sessao = ambiente["Session"]()
    try:
        with pytest.raises(ValueError):
            preferencias.atualizar_preferencias(
                alice,
                {"notificacoes_preco": False, "usuario_id": _id(ambiente, "bob")},
                session=sessao,
            )
        sessao.expire_all()
        assert sessao.query(PreferenciasUsuario).count() == 0
    finally:
        sessao.close()


def test_atualizar_preferencias_rejeita_payload_nulo(ambiente):
    alice = _usuario(ambiente, "alice")
    sessao = ambiente["Session"]()
    try:
        with pytest.raises(ValueError):
            preferencias.atualizar_preferencias(alice, None, session=sessao)
    finally:
        sessao.close()


def test_atualizar_preferencias_rejeita_payload_nao_dict(ambiente):
    alice = _usuario(ambiente, "alice")
    sessao = ambiente["Session"]()
    try:
        with pytest.raises(ValueError):
            preferencias.atualizar_preferencias(alice, ["notificacoes"], session=sessao)
    finally:
        sessao.close()


def test_atualizar_preferencias_rejeita_vazio(ambiente):
    alice = _usuario(ambiente, "alice")
    sessao = ambiente["Session"]()
    try:
        with pytest.raises(ValueError):
            preferencias.atualizar_preferencias(alice, {}, session=sessao)
    finally:
        sessao.close()


# ==========================================
# SERVIÇO: RESTAURAÇÃO
# ==========================================


def test_restaurar_preferencias_padrao_restaura_defaults(ambiente):
    alice = _usuario(ambiente, "alice")
    sessao = ambiente["Session"]()
    try:
        preferencias.atualizar_preferencias(
            alice,
            {"notificacoes_preco": False, "frequencia_relatorios": "desativada"},
            session=sessao,
        )
        registro = preferencias.restaurar_preferencias_padrao(alice, session=sessao)
        for campo, valor in preferencias.preferencias_padrao().items():
            assert getattr(registro, campo) == valor, campo
    finally:
        sessao.close()


def test_restaurar_preferencias_padrao_sem_registro_cria_linha(ambiente):
    bob = _usuario(ambiente, "bob")
    sessao = ambiente["Session"]()
    try:
        registro = preferencias.restaurar_preferencias_padrao(bob, session=sessao)
        assert registro is not None
        sessao.expire_all()
        assert sessao.query(PreferenciasUsuario).count() == 1
    finally:
        sessao.close()


# ==========================================
# SERVIÇO: ISOLAMENTO, UNICIDADE E AUDITORIA
# ==========================================


def test_preferencias_isoladas_entre_usuarios(ambiente):
    alice = _usuario(ambiente, "alice")
    bob = _usuario(ambiente, "bob")
    sessao = ambiente["Session"]()
    try:
        preferencias.atualizar_preferencias(
            alice, {"notificacoes_preco": False}, session=sessao
        )
        preferencias.atualizar_preferencias(
            bob, {"frequencia_notificacoes": "diaria"}, session=sessao
        )
        sessao.expire_all()
        linha_alice = _linha(ambiente["Session"], _id(ambiente, "alice"))
        linha_bob = _linha(ambiente["Session"], _id(ambiente, "bob"))
        assert linha_alice.notificacoes_preco is False
        assert linha_bob.notificacoes_preco is True
        assert linha_alice.frequencia_notificacoes == "imediata"
        assert linha_bob.frequencia_notificacoes == "diaria"
    finally:
        sessao.close()


def test_unique_usuario_id_garantido_pelo_banco(ambiente):
    sessao = ambiente["Session"]()
    try:
        alice_id = _id(ambiente, "alice")
        sessao.add(PreferenciasUsuario(usuario_id=alice_id))
        sessao.add(PreferenciasUsuario(usuario_id=alice_id))
        with pytest.raises(IntegrityError):
            sessao.commit()
        sessao.rollback()
    finally:
        sessao.close()


def test_telegram_ativo_nao_gera_envio_na_auditoria(ambiente):
    alice = _usuario(ambiente, "alice")
    sessao = ambiente["Session"]()
    try:
        preferencias.atualizar_preferencias(
            alice, {"telegram_ativo": True}, session=sessao
        )
        texto = _texto_auditoria(ambiente)
        assert "TELEGRAM" not in texto and "ENVIO" not in texto
        assert "PREFERENCIAS_ATUALIZADAS" in texto
    finally:
        sessao.close()


def test_auditoria_registra_eventos_sem_segredos(ambiente):
    alice = _usuario(ambiente, "alice")
    sessao = ambiente["Session"]()
    try:
        preferencias.obter_ou_criar_preferencias(alice, session=sessao)
        preferencias.atualizar_preferencias(alice, {"web_ativo": False}, session=sessao)
        preferencias.restaurar_preferencias_padrao(alice, session=sessao)
        texto = _texto_auditoria(ambiente)
        assert "PREFERENCIAS_CRIADAS" in texto
        assert "PREFERENCIAS_ATUALIZADAS" in texto
        assert "PREFERENCIAS_RESTAURADAS" in texto
        for segredo in _segredos(ambiente):
            assert segredo not in texto
    finally:
        sessao.close()


# ==========================================
# API: GET /api/v1/preferencias
# ==========================================


def test_get_retorna_defaults(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/preferencias", headers=_h(ambiente, "alice")
    )
    assert resposta.status_code == 200
    dados = resposta.get_json()["data"]
    assert dados["notificacoes_ativas"] is True
    assert dados["frequencia_notificacoes"] == "imediata"
    assert dados["frequencia_relatorios"] == "semanal"
    assert "usuario_id" not in dados


def test_get_cria_linha_quando_ausente(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/preferencias", headers=_h(ambiente, "bob")
    )
    assert resposta.status_code == 200
    assert _linha(ambiente["Session"], _id(ambiente, "bob")) is not None


def test_get_isolado_entre_usuarios(ambiente):
    ambiente["cliente"].patch(
        "/api/v1/preferencias",
        json={"notificacoes_preco": False},
        headers=_h(ambiente, "alice"),
    )
    dados_alice = ambiente["cliente"].get(
        "/api/v1/preferencias", headers=_h(ambiente, "alice")
    ).get_json()["data"]
    dados_bob = ambiente["cliente"].get(
        "/api/v1/preferencias", headers=_h(ambiente, "bob")
    ).get_json()["data"]
    assert dados_alice["notificacoes_preco"] is False
    assert dados_bob["notificacoes_preco"] is True


# ==========================================
# API: PATCH /api/v1/preferencias
# ==========================================


def test_patch_atualiza_parcialmente(ambiente):
    resposta = ambiente["cliente"].patch(
        "/api/v1/preferencias",
        json={"notificacoes_dividendos": False, "frequencia_notificacoes": "diaria"},
        headers=_h(ambiente, "alice"),
    )
    assert resposta.status_code == 200
    dados = resposta.get_json()["data"]
    assert dados["notificacoes_dividendos"] is False
    assert dados["frequencia_notificacoes"] == "diaria"
    assert dados["notificacoes_ativas"] is True


@pytest.mark.parametrize("valor", [0, 1, "true", None])
def test_patch_booleano_invalido_400(ambiente, valor):
    resposta = ambiente["cliente"].patch(
        "/api/v1/preferencias",
        json={"notificacoes_preco": valor},
        headers=_h(ambiente, "alice"),
    )
    assert resposta.status_code == 400
    assert _linha(ambiente["Session"], _id(ambiente, "alice")) is None


@pytest.mark.parametrize("campo,valor", [
    ("frequencia_notificacoes", "mensal"),
    ("frequencia_relatorios", "anual"),
])
def test_patch_frequencia_invalida_400(ambiente, campo, valor):
    resposta = ambiente["cliente"].patch(
        "/api/v1/preferencias",
        json={campo: valor},
        headers=_h(ambiente, "alice"),
    )
    assert resposta.status_code == 400


def test_patch_campo_desconhecido_400(ambiente):
    resposta = ambiente["cliente"].patch(
        "/api/v1/preferencias",
        json={"modo_escuro": True},
        headers=_h(ambiente, "alice"),
    )
    assert resposta.status_code == 400


@pytest.mark.parametrize("campo", ["id", "usuario_id", "criado_em", "atualizado_em"])
def test_patch_campos_proibidos_400(ambiente, campo):
    resposta = ambiente["cliente"].patch(
        "/api/v1/preferencias",
        json={campo: 123},
        headers=_h(ambiente, "alice"),
    )
    assert resposta.status_code == 400
    assert _linha(ambiente["Session"], _id(ambiente, "alice")) is None


def test_patch_payload_vazio_400(ambiente):
    resposta = ambiente["cliente"].patch(
        "/api/v1/preferencias", json={}, headers=_h(ambiente, "alice")
    )
    assert resposta.status_code == 400


def test_patch_manipular_usuario_id_rejeitado(ambiente):
    resposta = ambiente["cliente"].patch(
        "/api/v1/preferencias",
        json={"notificacoes_preco": False, "usuario_id": _id(ambiente, "bob")},
        headers=_h(ambiente, "alice"),
    )
    assert resposta.status_code == 400
    assert _linha(ambiente["Session"], _id(ambiente, "alice")) is None
    assert _linha(ambiente["Session"], _id(ambiente, "bob")) is None


# ==========================================
# API: POST /api/v1/preferencias/restaurar
# ==========================================


def test_post_restaurar_restaura_defaults(ambiente):
    ambiente["cliente"].patch(
        "/api/v1/preferencias",
        json={"notificacoes_preco": False, "frequencia_relatorios": "desativada"},
        headers=_h(ambiente, "alice"),
    )
    resposta = ambiente["cliente"].post(
        "/api/v1/preferencias/restaurar", headers=_h(ambiente, "alice")
    )
    assert resposta.status_code == 200
    dados = resposta.get_json()["data"]
    assert dados["notificacoes_preco"] is True
    assert dados["frequencia_relatorios"] == "semanal"
    assert resposta.get_json()["meta"]["restaurado"] is True


def test_post_restaurar_sem_registro_cria_linha(ambiente):
    resposta = ambiente["cliente"].post(
        "/api/v1/preferencias/restaurar", headers=_h(ambiente, "bob")
    )
    assert resposta.status_code == 200
    assert _linha(ambiente["Session"], _id(ambiente, "bob")) is not None


# ==========================================
# API: AUTENTICAÇÃO, PAPÉIS E SEGREDOS
# ==========================================


def test_sem_credencial_401(ambiente):
    assert ambiente["cliente"].get("/api/v1/preferencias").status_code == 401


def test_visitor_403(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/preferencias", headers=_h(ambiente, "visitor")
    )
    assert resposta.status_code == 403


def test_desativado_401(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/preferencias", headers=_h(ambiente, "desativado")
    )
    assert resposta.status_code == 401


def test_superadmin_consulta_proprias_preferencias(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/preferencias", headers=_h(ambiente, "superadmin")
    )
    assert resposta.status_code == 200
    assert _linha(ambiente["Session"], _id(ambiente, "superadmin")) is not None


def test_nao_expoe_segredos_nem_usuario_id(ambiente):
    ambiente["cliente"].patch(
        "/api/v1/preferencias",
        json={"notificacoes_preco": False},
        headers=_h(ambiente, "alice"),
    )
    corpo = ambiente["cliente"].get(
        "/api/v1/preferencias", headers=_h(ambiente, "alice")
    ).get_data(as_text=True)
    for segredo in _segredos(ambiente):
        assert segredo not in corpo
    for proibido in ("usuario_id", "senha_hash", "token_hash", "chave_hash"):
        assert proibido not in corpo


def test_auditoria_da_api_sem_segredos(ambiente):
    ambiente["cliente"].get("/api/v1/preferencias", headers=_h(ambiente, "alice"))
    texto = _texto_auditoria(ambiente)
    assert "PREFERENCIAS_CRIADAS" in texto
    for segredo in _segredos(ambiente):
        assert segredo not in texto
