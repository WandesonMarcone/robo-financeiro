"""Testes da Fase 6, Etapa 1 — Gestão real de usuários pela API.

Cobrem a administração de usuários pelos endpoints ``/api/v1/usuarios``:
listagem/consulta, criação, alteração, ativação/desativação, alteração de
papel, vínculo/desvínculo Telegram e revogação de sessões — sempre pela matriz
central de autorização (``services/autorizacao.py``), com proteção do
SUPERADMIN, isolamento entre usuários e ausência de segredos nas respostas e na
auditoria.
"""
import hashlib

import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api import dependencias, integrar_api
from pipeline_dados.banco_dados import AuditoriaAcesso, Base
from services import chaves_api, sessoes, usuarios

CAMPOS_PUBLICOS = {
    "id",
    "nome",
    "email",
    "papel",
    "plano",
    "ativo",
    "telegram_vinculado",
    "ultimo_login",
    "criado_em",
    "atualizado_em",
}
CAMPOS_PROIBIDOS = (
    "senha",
    "senha_hash",
    "sessoes",
    "chaves_api",
    "chave_hash",
    "token",
    "token_hash",
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
        "sessoes": seed.sessoes,
    }


class _Semear:
    """Popula o banco de testes: usuários de vários papéis + chaves + sessões."""

    def __init__(self, sessao):
        self.sessao = sessao
        self.usuarios = {}
        self.chaves = {}
        self.sessoes = {}

    def _criar(self, nome, email, papel, ativo=True, telegram_user_id=None):
        return usuarios.criar_usuario(
            nome=nome,
            email=email,
            senha="senha1234",
            papel=papel,
            ativo=ativo,
            telegram_user_id=telegram_user_id,
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


def _id(ambiente, nome):
    return ambiente["usuarios"][nome]


def _auditoria(Session):
    sessao = Session()
    try:
        return sessao.query(AuditoriaAcesso).order_by(AuditoriaAcesso.id).all()
    finally:
        sessao.close()


def _segredos(ambiente):
    """Conjunto de segredos que nunca podem aparecer em respostas/auditoria."""
    segredos = {"senha1234", "senha_hash", "token_hash", "chave_hash"}
    segredos.update(ambiente["chaves"].values())
    segredos.update(ambiente["sessoes"].values())
    return segredos


def _texto_auditoria(ambiente):
    return "\n".join(
        f"{e.acao} {e.alvo or ''} {e.detalhe or ''}"
        for e in _auditoria(ambiente["Session"])
    )


# ==========================================
# LISTAGEM E CONSULTA
# ==========================================


def test_listar_usuarios_autorizado(ambiente):
    resposta = ambiente["cliente"].get("/api/v1/usuarios", headers=_h(ambiente, "admin"))
    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados["status"] == "success"
    assert dados["meta"]["total"] >= 5
    emails = {item["email"] for item in dados["data"]}
    assert "root@x.com" in emails and "alvo@x.com" in emails


def test_listar_usuarios_superadmin_autorizado(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/usuarios", headers=_h(ambiente, "superadmin")
    )
    assert resposta.status_code == 200


def test_listar_usuarios_nao_autorizado(ambiente):
    for nome in ("user", "visitor"):
        resposta = ambiente["cliente"].get("/api/v1/usuarios", headers=_h(ambiente, nome))
        assert resposta.status_code == 403, nome


def test_consultar_usuario_autorizado(ambiente):
    resposta = ambiente["cliente"].get(
        f"/api/v1/usuarios/{_id(ambiente, 'alvo')}", headers=_h(ambiente, "admin")
    )
    assert resposta.status_code == 200
    dados = resposta.get_json()["data"]
    assert dados["email"] == "alvo@x.com"
    assert set(dados.keys()) == CAMPOS_PUBLICOS


def test_consultar_usuario_inexistente_404(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/usuarios/999999", headers=_h(ambiente, "admin")
    )
    assert resposta.status_code == 404


def test_consultar_usuario_nao_autorizado_isolamento(ambiente):
    resposta = ambiente["cliente"].get(
        f"/api/v1/usuarios/{_id(ambiente, 'alvo')}", headers=_h(ambiente, "user")
    )
    assert resposta.status_code == 403


def test_listagem_nao_expoe_segredos(ambiente):
    resposta = ambiente["cliente"].get("/api/v1/usuarios", headers=_h(ambiente, "admin"))
    corpo = resposta.get_data(as_text=True)
    for segredo in _segredos(ambiente):
        assert segredo not in corpo
    for proibido in CAMPOS_PROIBIDOS:
        assert proibido not in corpo


# ==========================================
# CRIAÇÃO
# ==========================================


def _criar(ambiente, autor, **campos):
    corpo = {"nome": "Novo", "email": "novo@x.com", "senha": "senha1234"}
    corpo.update(campos)
    return ambiente["cliente"].post(
        "/api/v1/usuarios", json=corpo, headers=_h(ambiente, autor)
    )


def test_criar_usuario_user(ambiente):
    resposta = _criar(ambiente, "admin", email="novo@x.com", papel="USER")
    assert resposta.status_code == 200
    dados = resposta.get_json()["data"]
    assert dados["email"] == "novo@x.com"
    assert dados["papel"] == "USER"
    assert dados["ativo"] is True
    assert set(dados.keys()) == CAMPOS_PUBLICOS


def test_criar_usuario_visitor(ambiente):
    resposta = _criar(ambiente, "admin", email="novo@x.com", papel="VISITOR")
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["papel"] == "VISITOR"


def test_criar_usuario_sem_senha(ambiente):
    resposta = _criar(ambiente, "admin", email="sem@x.com", senha=None)
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["email"] == "sem@x.com"


def test_criar_usuario_admin_quando_permitido(ambiente):
    resposta = _criar(ambiente, "superadmin", email="novo@x.com", papel="ADMIN")
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["papel"] == "ADMIN"


def test_admin_nao_cria_superadmin(ambiente):
    resposta = _criar(ambiente, "admin", email="novo@x.com", papel="SUPERADMIN")
    assert resposta.status_code == 403


def test_admin_nao_cria_admin(ambiente):
    resposta = _criar(ambiente, "admin", email="novo@x.com", papel="ADMIN")
    assert resposta.status_code == 403


def test_papel_invalido_rejeitado(ambiente):
    resposta = _criar(ambiente, "admin", email="novo@x.com", papel="ROOT")
    assert resposta.status_code == 400


def test_email_duplicado_rejeitado(ambiente):
    resposta = _criar(ambiente, "admin", email="alvo@x.com")
    assert resposta.status_code == 400


def test_telegram_duplicado_rejeitado(ambiente):
    ambiente["cliente"].post(
        f"/api/v1/usuarios/{_id(ambiente, 'user')}/telegram",
        json={"telegram_user_id": 555},
        headers=_h(ambiente, "admin"),
    )
    resposta = _criar(ambiente, "admin", email="novo@x.com", telegram_user_id=555)
    assert resposta.status_code == 400


def test_senha_curta_rejeitada(ambiente):
    resposta = _criar(ambiente, "admin", email="novo@x.com", senha="curta")
    assert resposta.status_code == 400


def test_criar_usuario_sem_nome_rejeitado(ambiente):
    resposta = _criar(ambiente, "admin", nome=None)
    assert resposta.status_code == 400


# ==========================================
# ALTERAÇÃO (PATCH)
# ==========================================


def test_alteracao_autorizada_pelo_admin(ambiente):
    resposta = ambiente["cliente"].patch(
        f"/api/v1/usuarios/{_id(ambiente, 'alvo')}",
        json={"nome": "Alvo Editado"},
        headers=_h(ambiente, "admin"),
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["nome"] == "Alvo Editado"


def test_user_alteracao_da_propria_conta(ambiente):
    resposta = ambiente["cliente"].patch(
        f"/api/v1/usuarios/{_id(ambiente, 'user')}",
        json={"nome": "Eu Mesmo"},
        headers=_h(ambiente, "user"),
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["nome"] == "Eu Mesmo"


def test_user_alteracao_de_outro_usuario_negada(ambiente):
    resposta = ambiente["cliente"].patch(
        f"/api/v1/usuarios/{_id(ambiente, 'alvo')}",
        json={"nome": "Invasao"},
        headers=_h(ambiente, "user"),
    )
    assert resposta.status_code == 403


def test_admin_nao_altera_superadmin_protegido(ambiente):
    resposta = ambiente["cliente"].patch(
        f"/api/v1/usuarios/{_id(ambiente, 'superadmin')}",
        json={"nome": "Hack"},
        headers=_h(ambiente, "admin"),
    )
    assert resposta.status_code == 403


def test_alteracao_email_duplicado_rejeitada(ambiente):
    resposta = ambiente["cliente"].patch(
        f"/api/v1/usuarios/{_id(ambiente, 'alvo')}",
        json={"email": "user@x.com"},
        headers=_h(ambiente, "admin"),
    )
    assert resposta.status_code == 400


def test_patch_sem_campos_permitidos_rejeitado(ambiente):
    resposta = ambiente["cliente"].patch(
        f"/api/v1/usuarios/{_id(ambiente, 'alvo')}",
        json={"papel": "ADMIN"},
        headers=_h(ambiente, "admin"),
    )
    assert resposta.status_code == 400


def test_alteracao_senha_nao_vaza(ambiente):
    resposta = ambiente["cliente"].patch(
        f"/api/v1/usuarios/{_id(ambiente, 'alvo')}",
        json={"senha": "novaSenha456"},
        headers=_h(ambiente, "admin"),
    )
    assert resposta.status_code == 200
    corpo = resposta.get_data(as_text=True)
    assert "novaSenha456" not in corpo
    assert "senha_hash" not in corpo


# ==========================================
# ATIVAÇÃO / DESATIVAÇÃO
# ==========================================


def test_desativar_usuario(ambiente):
    resposta = ambiente["cliente"].post(
        f"/api/v1/usuarios/{_id(ambiente, 'alvo')}/desativar",
        headers=_h(ambiente, "admin"),
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["ativo"] is False


def test_desativado_nao_autentica(ambiente):
    ambiente["cliente"].post(
        f"/api/v1/usuarios/{_id(ambiente, 'alvo')}/desativar",
        headers=_h(ambiente, "admin"),
    )
    for segredo in ("chaves", "sessoes"):
        cabecalho = {
            "chaves": {"X-API-Key": ambiente["chaves"]["alvo"]},
            "sessoes": {"X-Session-Token": ambiente["sessoes"]["alvo"]},
        }[segredo]
        resposta = ambiente["cliente"].get("/api/v1/me", headers=cabecalho)
        assert resposta.status_code == 401, segredo


def test_reativar_usuario(ambiente):
    ambiente["cliente"].post(
        f"/api/v1/usuarios/{_id(ambiente, 'alvo')}/desativar",
        headers=_h(ambiente, "admin"),
    )
    resposta = ambiente["cliente"].post(
        f"/api/v1/usuarios/{_id(ambiente, 'alvo')}/ativar",
        headers=_h(ambiente, "admin"),
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["ativo"] is True
    acesso = ambiente["cliente"].get(
        "/api/v1/me", headers={"X-API-Key": ambiente["chaves"]["alvo"]}
    )
    assert acesso.status_code == 200


def test_desativacao_preserva_dados(ambiente):
    ambiente["cliente"].post(
        f"/api/v1/usuarios/{_id(ambiente, 'alvo')}/desativar",
        headers=_h(ambiente, "admin"),
    )
    lista = ambiente["cliente"].get("/api/v1/usuarios", headers=_h(ambiente, "admin"))
    item = next(
        u for u in lista.get_json()["data"] if u["email"] == "alvo@x.com"
    )
    assert item["ativo"] is False
    assert item["nome"] == "Alvo"


def test_desativar_nao_autorizado(ambiente):
    resposta = ambiente["cliente"].post(
        f"/api/v1/usuarios/{_id(ambiente, 'alvo')}/desativar",
        headers=_h(ambiente, "user"),
    )
    assert resposta.status_code == 403


def test_admin_nao_desativa_superadmin(ambiente):
    resposta = ambiente["cliente"].post(
        f"/api/v1/usuarios/{_id(ambiente, 'superadmin')}/desativar",
        headers=_h(ambiente, "admin"),
    )
    assert resposta.status_code == 403


# ==========================================
# PAPÉIS
# ==========================================


def test_alteracao_de_papel_permitida(ambiente):
    resposta = ambiente["cliente"].post(
        f"/api/v1/usuarios/{_id(ambiente, 'user')}/papel",
        json={"papel": "ADMIN"},
        headers=_h(ambiente, "superadmin"),
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["papel"] == "ADMIN"


def test_alteracao_de_papel_pelo_admin_permitida(ambiente):
    resposta = ambiente["cliente"].post(
        f"/api/v1/usuarios/{_id(ambiente, 'user')}/papel",
        json={"papel": "VISITOR"},
        headers=_h(ambiente, "admin"),
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["papel"] == "VISITOR"


def test_alteracao_de_papel_nao_autorizada(ambiente):
    resposta = ambiente["cliente"].post(
        f"/api/v1/usuarios/{_id(ambiente, 'alvo')}/papel",
        json={"papel": "VISITOR"},
        headers=_h(ambiente, "user"),
    )
    assert resposta.status_code == 403


def test_tentativa_de_escalonamento_para_superadmin(ambiente):
    resposta = ambiente["cliente"].post(
        f"/api/v1/usuarios/{_id(ambiente, 'user')}/papel",
        json={"papel": "SUPERADMIN"},
        headers=_h(ambiente, "admin"),
    )
    assert resposta.status_code == 403


def test_admin_nao_promove_a_admin(ambiente):
    resposta = ambiente["cliente"].post(
        f"/api/v1/usuarios/{_id(ambiente, 'user')}/papel",
        json={"papel": "ADMIN"},
        headers=_h(ambiente, "admin"),
    )
    assert resposta.status_code == 403


def test_protecao_do_superadmin_no_papel(ambiente):
    resposta = ambiente["cliente"].post(
        f"/api/v1/usuarios/{_id(ambiente, 'superadmin')}/papel",
        json={"papel": "USER"},
        headers=_h(ambiente, "admin"),
    )
    assert resposta.status_code == 403


def test_papel_invalido_na_alteracao(ambiente):
    resposta = ambiente["cliente"].post(
        f"/api/v1/usuarios/{_id(ambiente, 'user')}/papel",
        json={"papel": "ROOT"},
        headers=_h(ambiente, "superadmin"),
    )
    assert resposta.status_code == 400


# ==========================================
# TELEGRAM
# ==========================================


def test_vincular_telegram(ambiente):
    resposta = ambiente["cliente"].post(
        f"/api/v1/usuarios/{_id(ambiente, 'alvo')}/telegram",
        json={"telegram_user_id": 777, "telegram_chat_id": 888},
        headers=_h(ambiente, "admin"),
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["telegram_vinculado"] is True


def test_desvincular_telegram(ambiente):
    ambiente["cliente"].post(
        f"/api/v1/usuarios/{_id(ambiente, 'alvo')}/telegram",
        json={"telegram_user_id": 777},
        headers=_h(ambiente, "admin"),
    )
    resposta = ambiente["cliente"].delete(
        f"/api/v1/usuarios/{_id(ambiente, 'alvo')}/telegram",
        headers=_h(ambiente, "admin"),
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["telegram_vinculado"] is False


def test_telegram_duplicado_na_vinculacao(ambiente):
    ambiente["cliente"].post(
        f"/api/v1/usuarios/{_id(ambiente, 'user')}/telegram",
        json={"telegram_user_id": 555},
        headers=_h(ambiente, "admin"),
    )
    resposta = ambiente["cliente"].post(
        f"/api/v1/usuarios/{_id(ambiente, 'alvo')}/telegram",
        json={"telegram_user_id": 555},
        headers=_h(ambiente, "admin"),
    )
    assert resposta.status_code == 400


def test_vincular_telegram_nao_autorizado(ambiente):
    resposta = ambiente["cliente"].post(
        f"/api/v1/usuarios/{_id(ambiente, 'alvo')}/telegram",
        json={"telegram_user_id": 777},
        headers=_h(ambiente, "user"),
    )
    assert resposta.status_code == 403


def test_telegram_sem_id_obrigatorio(ambiente):
    resposta = ambiente["cliente"].post(
        f"/api/v1/usuarios/{_id(ambiente, 'alvo')}/telegram",
        json={},
        headers=_h(ambiente, "admin"),
    )
    assert resposta.status_code == 400


# ==========================================
# SESSÕES
# ==========================================


def test_revogacao_de_sessoes_autorizada(ambiente):
    ambiente["cliente"].post(
        f"/api/v1/usuarios/{_id(ambiente, 'alvo')}/sessoes/revogar",
        headers=_h(ambiente, "admin"),
    )
    resposta = ambiente["cliente"].get(
        "/api/v1/me", headers={"X-Session-Token": ambiente["sessoes"]["alvo"]}
    )
    assert resposta.status_code == 401


def test_revogacao_de_sessoes_nao_autorizada(ambiente):
    resposta = ambiente["cliente"].post(
        f"/api/v1/usuarios/{_id(ambiente, 'alvo')}/sessoes/revogar",
        headers=_h(ambiente, "user"),
    )
    assert resposta.status_code == 403


def test_revogacao_de_sessoes_respeita_protecao(ambiente):
    resposta = ambiente["cliente"].post(
        f"/api/v1/usuarios/{_id(ambiente, 'superadmin')}/sessoes/revogar",
        headers=_h(ambiente, "admin"),
    )
    assert resposta.status_code == 403


# ==========================================
# SEGURANÇA E AUDITORIA
# ==========================================


def test_isolamento_total_entre_usuarios(ambiente):
    alvo_id = _id(ambiente, "alvo")
    acoes = (
        ("get", f"/api/v1/usuarios/{alvo_id}", None),
        ("patch", f"/api/v1/usuarios/{alvo_id}", {"nome": "X"}),
        ("post", f"/api/v1/usuarios/{alvo_id}/desativar", None),
        ("post", f"/api/v1/usuarios/{alvo_id}/papel", {"papel": "VISITOR"}),
        ("post", f"/api/v1/usuarios/{alvo_id}/telegram", {"telegram_user_id": 9}),
        ("post", f"/api/v1/usuarios/{alvo_id}/sessoes/revogar", None),
    )
    cliente = ambiente["cliente"]
    for metodo, caminho, corpo in acoes:
        chamada = getattr(cliente, metodo)
        kwargs = {"headers": _h(ambiente, "user")}
        if corpo is not None:
            kwargs["json"] = corpo
        assert chamada(caminho, **kwargs).status_code == 403, f"{metodo} {caminho}"


def test_visitor_sem_acesso_administrativo(ambiente):
    alvo_id = _id(ambiente, "alvo")
    chamadas = (
        ("get", "/api/v1/usuarios", None),
        ("get", f"/api/v1/usuarios/{alvo_id}", None),
        ("post", f"/api/v1/usuarios/{alvo_id}/desativar", None),
        ("post", f"/api/v1/usuarios/{alvo_id}/papel", {"papel": "VISITOR"}),
        ("post", f"/api/v1/usuarios/{alvo_id}/telegram", {"telegram_user_id": 9}),
        ("post", f"/api/v1/usuarios/{alvo_id}/sessoes/revogar", None),
    )
    cliente = ambiente["cliente"]
    for metodo, caminho, corpo in chamadas:
        chamada = getattr(cliente, metodo)
        kwargs = {"headers": _h(ambiente, "visitor")}
        if corpo is not None:
            kwargs["json"] = corpo
        assert chamada(caminho, **kwargs).status_code == 403, f"{metodo} {caminho}"


def test_nenhum_segredo_em_respostas(ambiente):
    cliente = ambiente["cliente"]
    respostas = [
        cliente.get("/api/v1/usuarios", headers=_h(ambiente, "admin")),
        cliente.get(
            f"/api/v1/usuarios/{_id(ambiente, 'alvo')}", headers=_h(ambiente, "admin")
        ),
        cliente.get("/api/v1/me", headers=_h(ambiente, "user")),
        _criar(ambiente, "admin", email="seguro@x.com"),
        cliente.patch(
            f"/api/v1/usuarios/{_id(ambiente, 'alvo')}",
            json={"senha": "outraSenha789"},
            headers=_h(ambiente, "admin"),
        ),
        cliente.post(
            f"/api/v1/usuarios/{_id(ambiente, 'alvo')}/telegram",
            json={"telegram_user_id": 424242},
            headers=_h(ambiente, "admin"),
        ),
    ]
    for segredo in _segredos(ambiente):
        for resposta in respostas:
            assert segredo not in resposta.get_data(as_text=True)
    corpo_geral = "\n".join(r.get_data(as_text=True) for r in respostas)
    for proibido in CAMPOS_PROIBIDOS:
        assert proibido not in corpo_geral


def test_nenhum_segredo_na_auditoria(ambiente):
    cliente = ambiente["cliente"]
    cliente.get("/api/v1/usuarios", headers=_h(ambiente, "admin"))
    _criar(ambiente, "admin", email="auditado@x.com")
    cliente.patch(
        f"/api/v1/usuarios/{_id(ambiente, 'alvo')}",
        json={"senha": "auditadaSenha123"},
        headers=_h(ambiente, "admin"),
    )
    cliente.get(f"/api/v1/usuarios/{_id(ambiente, 'alvo')}", headers=_h(ambiente, "user"))
    cliente.post(
        f"/api/v1/usuarios/{_id(ambiente, 'user')}/papel",
        json={"papel": "SUPERADMIN"},
        headers=_h(ambiente, "admin"),
    )
    cliente.post(
        f"/api/v1/usuarios/{_id(ambiente, 'superadmin')}/desativar",
        headers=_h(ambiente, "admin"),
    )

    texto = _texto_auditoria(ambiente)
    assert "auditadaSenha123" not in texto
    for segredo in _segredos(ambiente):
        assert segredo not in texto
    for proibido in ("senha_hash", "token_hash", "chave_hash"):
        assert proibido not in texto


def test_tentativas_negadas_sao_auditadas(ambiente):
    cliente = ambiente["cliente"]
    cliente.get("/api/v1/usuarios", headers=_h(ambiente, "user"))
    cliente.post(
        f"/api/v1/usuarios/{_id(ambiente, 'user')}/papel",
        json={"papel": "SUPERADMIN"},
        headers=_h(ambiente, "admin"),
    )
    cliente.post(
        f"/api/v1/usuarios/{_id(ambiente, 'superadmin')}/desativar",
        headers=_h(ambiente, "admin"),
    )
    acoes = {e.acao for e in _auditoria(ambiente["Session"])}
    assert "API_ACESSO_NEGADO" in acoes
    assert "PAPEL_ALTERACAO_NEGADA" in acoes
    assert "ESCALONAMENTO_NEGADO" in acoes
