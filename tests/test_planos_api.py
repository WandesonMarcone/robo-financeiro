"""Testes da Fase 6, Etapa 8 — planos/entitlements pela API.

Cobrem os endpoints de planos:
- ``GET /api/v1/me/plano`` — leitura do plano/entitlements efetivos do usuário
  autenticado (nunca um valor vindo do cliente);
- ``POST /api/v1/usuarios/<id>/plano`` — alteração exclusiva de SUPERADMIN
  (anti-escalonamento; ADMIN/USER/VISITOR negados);
- rejeição do campo ``plano`` em ``POST /usuarios`` e ``PATCH /usuarios/<id>``;
- isolamento entre usuários, usuário desativado sem acesso, ausência de
  segredos em respostas e na trilha de auditoria.
"""
import hashlib

import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api import dependencias, integrar_api
from pipeline_dados.banco_dados import AuditoriaAcesso, Base
from services import chaves_api, planos, usuarios


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
    """Popula o banco de testes: usuários de vários papéis + chaves ativas."""

    def __init__(self, sessao):
        self.sessao = sessao
        self.usuarios = {}
        self.chaves = {}

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
        self.usuarios["visitor"] = self._criar("Visitante", "visitor@x.com", usuarios.VISITOR)
        self.usuarios["alvo"] = self._criar("Alvo", "alvo@x.com", usuarios.USER)
        self.usuarios["desativado"] = self._criar(
            "Off", "off@x.com", usuarios.USER, ativo=False
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


def _auditoria(Session):
    sessao = Session()
    try:
        return sessao.query(AuditoriaAcesso).order_by(AuditoriaAcesso.id).all()
    finally:
        sessao.close()


def _texto_auditoria(ambiente):
    return "\n".join(
        f"{e.acao} {e.alvo or ''} {e.detalhe or ''}"
        for e in _auditoria(ambiente["Session"])
    )


def _alterar_plano(ambiente, autor, alvo, plano):
    return ambiente["cliente"].post(
        f"/api/v1/usuarios/{_id(ambiente, alvo)}/plano",
        json={"plano": plano},
        headers=_h(ambiente, autor),
    )


# ==========================================
# CONSULTA DO PRÓPRIO PLANO (GET /me/plano)
# ==========================================


def test_me_plano_usuario_free(ambiente):
    resposta = ambiente["cliente"].get("/api/v1/me/plano", headers=_h(ambiente, "user"))
    assert resposta.status_code == 200
    dados = resposta.get_json()["data"]
    assert dados["plano"] == planos.PLANO_FREE
    assert dados["entitlements"] == []
    assert dados["limites"] == dict(planos.LIMITES_DO_PLANO[planos.PLANO_FREE])


def test_me_plano_superadmin_ilimitado(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/me/plano", headers=_h(ambiente, "superadmin")
    )
    assert resposta.status_code == 200
    dados = resposta.get_json()["data"]
    assert set(dados["entitlements"]) == set(planos.RECURSOS_VALIDOS)
    for recurso in planos.LIMITES_VALIDOS:
        assert dados["limites"][recurso] is None


def test_me_plano_reflete_plano_alterado(ambiente):
    _alterar_plano(ambiente, "superadmin", "user", planos.PLANO_PREMIUM)
    resposta = ambiente["cliente"].get("/api/v1/me/plano", headers=_h(ambiente, "user"))
    assert resposta.status_code == 200
    dados = resposta.get_json()["data"]
    assert dados["plano"] == planos.PLANO_PREMIUM
    assert set(dados["entitlements"]) == set(planos.RECURSOS_DO_PLANO[planos.PLANO_PREMIUM])


def test_me_plano_nao_autenticado_401(ambiente):
    resposta = ambiente["cliente"].get("/api/v1/me/plano")
    assert resposta.status_code == 401


def test_me_plano_usuario_desativado_401(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/me/plano", headers=_h(ambiente, "desativado")
    )
    assert resposta.status_code == 401


def test_me_plano_isolamento_entre_usuarios(ambiente):
    _alterar_plano(ambiente, "superadmin", "alvo", planos.PLANO_PRO)
    resposta_user = ambiente["cliente"].get(
        "/api/v1/me/plano", headers=_h(ambiente, "user")
    )
    resposta_alvo = ambiente["cliente"].get(
        "/api/v1/me/plano", headers=_h(ambiente, "alvo")
    )
    assert resposta_user.get_json()["data"]["plano"] == planos.PLANO_FREE
    assert resposta_alvo.get_json()["data"]["plano"] == planos.PLANO_PRO


# ==========================================
# ALTERAÇÃO DE PLANO (POST /usuarios/<id>/plano)
# ==========================================


def test_alterar_plano_superadmin_para_todos_os_planos(ambiente):
    for plano in planos.PLANOS_VALIDOS:
        resposta = _alterar_plano(ambiente, "superadmin", "alvo", plano)
        assert resposta.status_code == 200, plano
        dados = resposta.get_json()["data"]
        assert dados["plano"] == plano
        assert dados["email"] == "alvo@x.com"


def test_alterar_plano_admin_negado(ambiente):
    resposta = _alterar_plano(ambiente, "admin", "alvo", planos.PLANO_PRO)
    assert resposta.status_code == 403


def test_alterar_plano_user_proprio_negado(ambiente):
    resposta = _alterar_plano(ambiente, "user", "user", planos.PLANO_PRO)
    assert resposta.status_code == 403


def test_alterar_plano_user_outro_negado(ambiente):
    resposta = _alterar_plano(ambiente, "user", "alvo", planos.PLANO_PRO)
    assert resposta.status_code == 403


def test_alterar_plano_visitor_negado(ambiente):
    resposta = _alterar_plano(ambiente, "visitor", "alvo", planos.PLANO_PRO)
    assert resposta.status_code == 403


def test_alterar_plano_plano_invalido_400(ambiente):
    resposta = _alterar_plano(ambiente, "superadmin", "alvo", "GOLD")
    assert resposta.status_code == 400


def test_alterar_plano_usuario_inexistente_404(ambiente):
    resposta = ambiente["cliente"].post(
        "/api/v1/usuarios/999999/plano",
        json={"plano": planos.PLANO_PRO},
        headers=_h(ambiente, "superadmin"),
    )
    assert resposta.status_code == 404


def test_alterar_plano_sem_plano_no_corpo_400(ambiente):
    resposta = ambiente["cliente"].post(
        f"/api/v1/usuarios/{_id(ambiente, 'alvo')}/plano",
        json={},
        headers=_h(ambiente, "superadmin"),
    )
    assert resposta.status_code == 400


def test_alterar_plano_nao_autenticado_401(ambiente):
    resposta = ambiente["cliente"].post(
        f"/api/v1/usuarios/{_id(ambiente, 'alvo')}/plano", json={"plano": planos.PLANO_PRO}
    )
    assert resposta.status_code == 401


def test_alterar_plano_usuario_desativado_negado(ambiente):
    resposta = _alterar_plano(ambiente, "desativado", "alvo", planos.PLANO_PRO)
    assert resposta.status_code == 401


def test_alterar_plano_audita_sem_segredos(ambiente):
    _alterar_plano(ambiente, "superadmin", "alvo", planos.PLANO_PRO)
    assert planos.ACAO_PLANO_ALTERADO in _texto_auditoria(ambiente)
    assert "plano=PRO" in _texto_auditoria(ambiente)
    assert "senha1234" not in _texto_auditoria(ambiente)
    for nome in ambiente["chaves"]:
        assert ambiente["chaves"][nome] not in _texto_auditoria(ambiente)


def test_alterar_plano_admin_negado_auditado(ambiente):
    _alterar_plano(ambiente, "admin", "alvo", planos.PLANO_PRO)
    texto = _texto_auditoria(ambiente)
    assert "API_ACESSO_NEGADO" in texto
    assert "permissao=planos.administrar" in texto


# ==========================================
# CLIENTE NUNCA DEFINE O PLANO (cadastro/edição)
# ==========================================


def test_criar_usuario_com_plano_rejeitado(ambiente):
    resposta = ambiente["cliente"].post(
        "/api/v1/usuarios",
        json={"nome": "Nova", "email": "nova@x.com", "senha": "senha1234", "plano": "PRO"},
        headers=_h(ambiente, "superadmin"),
    )
    assert resposta.status_code == 400
    assert "plano" in resposta.get_json()["meta"]["error"].lower()


def test_patch_usuario_com_plano_rejeitado(ambiente):
    resposta = ambiente["cliente"].patch(
        f"/api/v1/usuarios/{_id(ambiente, 'alvo')}",
        json={"plano": "PRO"},
        headers=_h(ambiente, "superadmin"),
    )
    assert resposta.status_code == 400
    assert "plano" in resposta.get_json()["meta"]["error"].lower()


def test_criar_usuario_nao_expoe_plano_customizado(ambiente):
    resposta = ambiente["cliente"].post(
        "/api/v1/usuarios",
        json={"nome": "Nova", "email": "nova@x.com", "senha": "senha1234"},
        headers=_h(ambiente, "superadmin"),
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["plano"] == planos.PLANO_FREE
