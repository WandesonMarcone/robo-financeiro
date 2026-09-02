"""Testes HTTP de autogerenciamento de API Keys (Correção 2).

Cobrem os endpoints ``/api/v1/api-keys`` (criar/listar/consultar/revogar a
própria chave): criação autenticada, revogação autenticada, isolamento entre
usuários, tentativa sem autenticação, impossibilidade de manipular a chave de
outro usuário, ausência do segredo nas respostas após o armazenamento e
auditoria sem segredos. Reutiliza exclusivamente ``services/chaves_api.py`` e a
autorização ``conta.propria`` da matriz central.
"""
import hashlib
from datetime import datetime, timedelta

import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api import dependencias, integrar_api
from pipeline_dados.banco_dados import AuditoriaAcesso, Base, ChaveApi
from services import chaves_api, sessoes, usuarios

CAMPO_URL = "/api/v1/api-keys"
CAMPOS_METADADOS = {"id", "rotulo", "ativa", "expira_em", "criado_em"}


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
        "sessoes": seed.sessoes,
    }


class _Semear:
    """Popula o banco de testes: usuários de vários papéis + chaves + sessões."""

    def __init__(self, sessao):
        self.sessao = sessao
        self.usuarios = {}
        self.chaves = {}
        self.sessoes = {}

    def _criar(self, nome, email, papel, ativo=True):
        return usuarios.criar_usuario(
            nome=nome,
            email=email,
            senha="senha1234",
            papel=papel,
            ativo=ativo,
            session=self.sessao,
        )

    def rodar(self):
        s = self.sessao
        self.usuarios["superadmin"] = self._criar("Root", "root@x.com", usuarios.SUPERADMIN)
        self.usuarios["admin"] = self._criar("Admin", "admin@x.com", usuarios.ADMIN)
        self.usuarios["user"] = self._criar("User", "user@x.com", usuarios.USER)
        self.usuarios["alvo"] = self._criar("Alvo", "alvo@x.com", usuarios.USER)
        self.usuarios["visitor"] = self._criar("Visitante", "visitor@x.com", usuarios.VISITOR)
        self.usuarios["desativado"] = self._criar(
            "Off", "off@x.com", usuarios.USER, ativo=False
        )

        for nome, usuario in self.usuarios.items():
            if usuario.ativo:
                self.chaves[nome] = chaves_api.criar_chave_api(
                    usuario, f"chave-{nome}", session=s
                )
                self.sessoes[nome] = sessoes.criar_sessao(
                    usuario, origem="api", session=s
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


def _chaves_do_usuario(Session, usuario_id):
    sessao = Session()
    try:
        return (
            sessao.query(ChaveApi)
            .filter(ChaveApi.usuario_id == usuario_id)
            .order_by(ChaveApi.id)
            .all()
        )
    finally:
        sessao.close()


def _registro_chave(Session, usuario_id, rotulo):
    sessao = Session()
    try:
        return (
            sessao.query(ChaveApi)
            .filter(ChaveApi.usuario_id == usuario_id, ChaveApi.rotulo == rotulo)
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


def _criar_via_api(ambiente, nome, **campos):
    corpo = {"rotulo": "integracao"}
    corpo.update(campos)
    return ambiente["cliente"].post(CAMPO_URL, json=corpo, headers=_h(ambiente, nome))


def _chave_bruta(ambiente, nome):
    """Retorna a chave bruta de um usuário para autenticação via API."""
    return ambiente["chaves"][nome]


# ==========================================
# ROTAS REGISTRADAS
# ==========================================


def test_rotas_de_api_keys_registradas(ambiente):
    rotas = {str(r) for r in ambiente["cliente"].application.url_map.iter_rules()}
    assert "/api/v1/api-keys" in rotas
    assert "/api/v1/api-keys/<int:chave_id>" in rotas


# ==========================================
# CRIAÇÃO
# ==========================================


def test_criar_api_key_autenticada(ambiente):
    resposta = _criar_via_api(ambiente, "user")
    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados["status"] == "success"
    assert dados["meta"]["criada"] is True
    chave = dados["data"]["chave"]
    assert isinstance(chave, str) and chave
    autenticado = ambiente["cliente"].get(
        "/api/v1/me", headers={"X-API-Key": chave}
    )
    assert autenticado.status_code == 200
    assert autenticado.get_json()["data"]["email"] == "user@x.com"


def test_criar_api_key_sem_autenticacao(ambiente):
    resposta = ambiente["cliente"].post(CAMPO_URL, json={"rotulo": "x"})
    assert resposta.status_code == 401


def test_criar_api_key_rotulo_obrigatorio(ambiente):
    for rotulo in (None, "", "  "):
        resposta = _criar_via_api(ambiente, "user", rotulo=rotulo)
        assert resposta.status_code == 400, rotulo


def test_criar_api_key_ignora_usuario_id_de_terceiro(ambiente):
    usuario_admin = ambiente["usuarios"]["admin"]
    resposta = _criar_via_api(
        ambiente, "user", usuario_id=usuario_admin, rotulo="minha-chave"
    )
    assert resposta.status_code == 200
    chave_id = _registro_chave(
        ambiente["Session"], ambiente["usuarios"]["user"], "minha-chave"
    ).id
    rotulos_admin = {
        item["rotulo"]
        for item in ambiente["cliente"]
        .get(CAMPO_URL, headers=_h(ambiente, "admin"))
        .get_json()["data"]
    }
    assert "minha-chave" not in rotulos_admin
    rotulos_user = {
        item["rotulo"]
        for item in ambiente["cliente"]
        .get(CAMPO_URL, headers=_h(ambiente, "user"))
        .get_json()["data"]
    }
    assert "minha-chave" in rotulos_user
    assert chave_id


def test_criar_api_key_com_expira_em_futura(ambiente):
    expira = (datetime.now() + timedelta(days=30)).isoformat()
    resposta = _criar_via_api(ambiente, "user", expira_em=expira)
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["chave"]


def test_criar_api_key_com_expira_em_invalida(ambiente):
    for expira in ("data-invalida", (datetime.now() - timedelta(days=1)).isoformat()):
        resposta = _criar_via_api(ambiente, "user", expira_em=expira)
        assert resposta.status_code == 400, expira


# ==========================================
# LISTAGEM E ISOLAMENTO
# ==========================================


def test_listar_api_keys_autenticada(ambiente):
    resposta = ambiente["cliente"].get(CAMPO_URL, headers=_h(ambiente, "user"))
    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados["status"] == "success"
    assert dados["meta"]["total"] >= 1
    for item in dados["data"]:
        assert set(item.keys()) == CAMPOS_METADADOS
        assert "chave_hash" not in item
        assert "chave" not in item


def test_listar_api_keys_sem_autenticacao(ambiente):
    resposta = ambiente["cliente"].get(CAMPO_URL)
    assert resposta.status_code == 401


def test_isolamento_entre_usuarios(ambiente):
    _criar_via_api(ambiente, "user", rotulo="chave-user")
    _criar_via_api(ambiente, "alvo", rotulo="chave-alvo")
    ids_user = {
        item["id"]
        for item in ambiente["cliente"]
        .get(CAMPO_URL, headers=_h(ambiente, "user"))
        .get_json()["data"]
    }
    ids_alvo = {
        item["id"]
        for item in ambiente["cliente"]
        .get(CAMPO_URL, headers=_h(ambiente, "alvo"))
        .get_json()["data"]
    }
    assert ids_user and ids_alvo
    assert ids_user.isdisjoint(ids_alvo)


# ==========================================
# CONSULTA
# ==========================================


def test_consultar_api_key_propria(ambiente):
    chave_id = _chaves_do_usuario(ambiente["Session"], ambiente["usuarios"]["user"])[0].id
    resposta = ambiente["cliente"].get(
        f"{CAMPO_URL}/{chave_id}", headers=_h(ambiente, "user")
    )
    assert resposta.status_code == 200
    item = resposta.get_json()["data"]
    assert set(item.keys()) == CAMPOS_METADADOS
    assert item["id"] == chave_id


def test_consultar_api_key_sem_autenticacao(ambiente):
    chave_id = _chaves_do_usuario(ambiente["Session"], ambiente["usuarios"]["user"])[0].id
    resposta = ambiente["cliente"].get(f"{CAMPO_URL}/{chave_id}")
    assert resposta.status_code == 401


def test_consultar_api_key_de_outro_usuario_404(ambiente):
    chave_id = _chaves_do_usuario(ambiente["Session"], ambiente["usuarios"]["user"])[0].id
    resposta = ambiente["cliente"].get(
        f"{CAMPO_URL}/{chave_id}", headers=_h(ambiente, "alvo")
    )
    assert resposta.status_code == 404
    assert resposta.get_json()["status"] == "error"


def test_consultar_api_key_inexistente_404(ambiente):
    resposta = ambiente["cliente"].get(
        f"{CAMPO_URL}/999999", headers=_h(ambiente, "user")
    )
    assert resposta.status_code == 404


# ==========================================
# REVOGAÇÃO
# ==========================================


def test_revogar_api_key_autenticada(ambiente):
    resposta = _criar_via_api(ambiente, "user", rotulo="para-revogar")
    chave = resposta.get_json()["data"]["chave"]
    chave_id = _registro_chave(
        ambiente["Session"], ambiente["usuarios"]["user"], "para-revogar"
    ).id

    revogada = ambiente["cliente"].delete(
        f"{CAMPO_URL}/{chave_id}", headers=_h(ambiente, "user")
    )
    assert revogada.status_code == 200
    assert revogada.get_json()["data"]["removido"] is True

    autenticado = ambiente["cliente"].get(
        "/api/v1/me", headers={"X-API-Key": chave}
    )
    assert autenticado.status_code == 401


def test_revogar_api_key_sem_autenticacao(ambiente):
    chave_id = _chaves_do_usuario(ambiente["Session"], ambiente["usuarios"]["user"])[0].id
    resposta = ambiente["cliente"].delete(f"{CAMPO_URL}/{chave_id}")
    assert resposta.status_code == 401


def test_revogar_api_key_de_outro_usuario_404(ambiente):
    chave_id = _chaves_do_usuario(ambiente["Session"], ambiente["usuarios"]["user"])[0].id
    resposta = ambiente["cliente"].delete(
        f"{CAMPO_URL}/{chave_id}", headers=_h(ambiente, "alvo")
    )
    assert resposta.status_code == 404
    autenticado = ambiente["cliente"].get(
        "/api/v1/me", headers=_h(ambiente, "user")
    )
    assert autenticado.status_code == 200


def test_revogar_api_key_inexistente_404(ambiente):
    resposta = ambiente["cliente"].delete(
        f"{CAMPO_URL}/999999", headers=_h(ambiente, "user")
    )
    assert resposta.status_code == 404


# ==========================================
# SEGREDOS E AUDITORIA
# ==========================================


def test_segredo_nao_aparece_nas_respostas_apos_armazenamento(ambiente):
    resposta = _criar_via_api(ambiente, "user", rotulo="sigilosa")
    chave = resposta.get_json()["data"]["chave"]
    chave_hash = hashlib.sha256(chave.encode("utf-8")).hexdigest()
    chave_id = _registro_chave(
        ambiente["Session"], ambiente["usuarios"]["user"], "sigilosa"
    ).id

    for verbo, rota in (
        ("get", CAMPO_URL),
        ("get", f"{CAMPO_URL}/{chave_id}"),
        ("delete", f"{CAMPO_URL}/{chave_id}"),
    ):
        requisicao = getattr(ambiente["cliente"], verbo)(rota, headers=_h(ambiente, "user"))
        corpo = requisicao.get_data(as_text=True)
        assert chave not in corpo, f"{verbo} {rota}"
        assert chave_hash not in corpo, f"{verbo} {rota}"


def test_nenhuma_resposta_expõe_chave_hash(ambiente):
    resposta = ambiente["cliente"].get(CAMPO_URL, headers=_h(ambiente, "user"))
    corpo = resposta.get_data(as_text=True)
    assert "chave_hash" not in corpo
    assert '"chave"' not in corpo
    assert '"chave_hash"' not in corpo


def test_auditoria_sem_segredo(ambiente):
    resposta = _criar_via_api(ambiente, "user", rotulo="auditavel")
    chave = resposta.get_json()["data"]["chave"]
    chave_hash = hashlib.sha256(chave.encode("utf-8")).hexdigest()
    chave_id = _registro_chave(
        ambiente["Session"], ambiente["usuarios"]["user"], "auditavel"
    ).id
    ambiente["cliente"].delete(f"{CAMPO_URL}/{chave_id}", headers=_h(ambiente, "user"))

    eventos = _auditoria(ambiente["Session"])
    acoes = [e.acao for e in eventos]
    assert "API_KEY_CRIADA" in acoes
    assert "API_KEY_REVOGADA" in acoes
    for evento in eventos:
        texto = f"{evento.acao} {evento.alvo or ''} {evento.detalhe or ''}"
        assert chave not in texto
        assert chave_hash not in texto
        assert "hash" not in texto.lower()
