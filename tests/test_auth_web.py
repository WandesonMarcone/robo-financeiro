"""Testes da Fase 6, Etapa 2 — Autenticação Web e Ciclo de Sessão.

Cobrem o fluxo completo ``cadastro -> login -> sessão -> /me -> logout`` via
``POST /api/v1/auth/register``, ``POST /api/v1/auth/login`` e
``POST /api/v1/auth/logout``, reutilizando ``GET /api/v1/me`` (já existente, sem
duplicidade). Garantem: novo usuário nasce USER/ativo, senha e token nunca em
texto puro, resposta genérica para credenciais inválidas, ausência de segredos
em respostas/auditoria, isolamento entre usuários, API Key e Telegram
continuando a funcionar.
"""
import hashlib
from datetime import datetime, timedelta

import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api import dependencias, integrar_api
from pipeline_dados.banco_dados import AuditoriaAcesso, Base, Sessao
from services import chaves_api, telegram, usuarios

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
    }


class _Semear:
    """Popula o banco de testes: usuários de vários perfis + uma API Key."""

    def __init__(self, sessao):
        self.sessao = sessao
        self.usuarios = {}
        self.chaves = {}

    def rodar(self):
        s = self.sessao
        senha = "senha1234"
        self.usuarios["user"] = usuarios.criar_usuario(
            "Usuario", "user@x.com", senha, session=s
        )
        self.usuarios["alvo"] = usuarios.criar_usuario(
            "Alvo", "alvo@x.com", senha, session=s
        )
        self.usuarios["telegram"] = usuarios.criar_usuario(
            "Telegram", "tg@x.com", senha,
            telegram_user_id=9001, telegram_chat_id=9002, session=s,
        )
        self.usuarios["desativado"] = usuarios.criar_usuario(
            "Off", "off@x.com", senha, ativo=False, session=s
        )

        for nome in ("user", "alvo", "telegram"):
            self.chaves[nome] = chaves_api.criar_chave_api(
                self.usuarios[nome], f"chave-{nome}", session=s
            )

        s.commit()
        self.usuarios = {nome: usuario.id for nome, usuario in self.usuarios.items()}
        s.close()


def _registrar(ambiente, **campos):
    corpo = {"nome": "Novo", "email": "novo@x.com", "senha": "senha1234"}
    corpo.update(campos)
    return ambiente["cliente"].post("/api/v1/auth/register", json=corpo)


def _login(ambiente, email, senha="senha1234"):
    return ambiente["cliente"].post(
        "/api/v1/auth/login", json={"email": email, "senha": senha}
    )


def _token_da(resposta):
    return resposta.get_json()["data"]["token"]


def _cabecalho_token(token):
    return {"X-Session-Token": token}


def _usuario_por_email(Session, email):
    sessao = Session()
    try:
        return (
            sessao.query(usuarios.Usuario)
            .filter(usuarios.Usuario.email == email)
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
        f"{e.acao} {e.alvo or ''} {e.detalhe or ''}"
        for e in _auditoria(ambiente["Session"])
    )


def _segredos(ambiente, token=None):
    """Segredos que nunca podem vazar (senha de testes, chaves e token)."""
    segredos = {"senha1234", "senha_hash", "token_hash", "chave_hash"}
    segredos.update(ambiente["chaves"].values())
    if token is not None:
        segredos.add(token)
    return segredos


# ==========================================
# CADASTRO
# ==========================================


def test_cadastro_valido(ambiente):
    resposta = _registrar(ambiente, email="novo@x.com")
    assert resposta.status_code == 200
    dados = resposta.get_json()["data"]
    assert dados["email"] == "novo@x.com"
    assert dados["nome"] == "Novo"
    assert set(dados.keys()) == CAMPOS_PUBLICOS


def test_cadastro_sem_nome(ambiente):
    resposta = _registrar(ambiente, nome=None)
    assert resposta.status_code == 400


def test_cadastro_sem_email(ambiente):
    resposta = _registrar(ambiente, email=None)
    assert resposta.status_code == 400


def test_cadastro_email_normalizado(ambiente):
    resposta = _registrar(ambiente, email="  Novo@Example.COM  ")
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["email"] == "novo@example.com"

    login_1 = _login(ambiente, "novo@example.com")
    assert login_1.status_code == 200
    login_2 = _login(ambiente, "  NOVO@EXAMPLE.COM ")
    assert login_2.status_code == 200


def test_cadastro_email_duplicado(ambiente):
    assert _registrar(ambiente, email="novo@x.com").status_code == 200
    resposta = _registrar(ambiente, email="novo@x.com")
    assert resposta.status_code == 400
    resposta_maiusculo = _registrar(ambiente, email="NOVO@x.com")
    assert resposta_maiusculo.status_code == 400


def test_cadastro_senha_menor_que_8(ambiente):
    resposta = _registrar(ambiente, senha="curta")
    assert resposta.status_code == 400


def test_cadastro_nasce_user(ambiente):
    resposta = _registrar(ambiente, email="novo@x.com")
    assert resposta.get_json()["data"]["papel"] == "USER"


def test_cadastro_nao_pode_escolher_admin(ambiente):
    resposta = _registrar(ambiente, email="novo@x.com", papel="ADMIN")
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["papel"] == "USER"


def test_cadastro_nao_pode_escolher_superadmin(ambiente):
    resposta = _registrar(ambiente, email="novo@x.com", papel="SUPERADMIN")
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["papel"] == "USER"


def test_cadastro_nao_pode_definir_papel_arbitrario(ambiente):
    resposta = _registrar(ambiente, email="novo@x.com", papel="ROOT")
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["papel"] == "USER"


def test_cadastro_nao_pode_definir_ativo(ambiente):
    resposta = _registrar(ambiente, email="novo@x.com", ativo=False)
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["ativo"] is True


def test_cadastro_nao_pode_vincular_telegram(ambiente):
    resposta = _registrar(ambiente, email="novo@x.com", telegram_user_id=1234)
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["telegram_vinculado"] is False


def test_senha_nao_aparece_no_banco(ambiente):
    _registrar(ambiente, email="novo@x.com", senha="senhaSecreta123")
    usuario = _usuario_por_email(ambiente["Session"], "novo@x.com")
    assert usuario is not None
    assert usuario.senha_hash is not None
    assert usuario.senha_hash != "senhaSecreta123"
    assert "senhaSecreta123" not in usuario.senha_hash
    assert usuario.senha_hash != usuario.senha_hash.upper()
    assert len(usuario.senha_hash) > 20

    sessao = ambiente["Session"]()
    try:
        for tabela in (usuarios.Usuario, Sessao):
            for linha in sessao.query(tabela).all():
                for coluna in linha.__table__.columns:
                    valor = getattr(linha, coluna.name)
                    assert "senhaSecreta123" not in str(valor or "")
    finally:
        sessao.close()


# ==========================================
# LOGIN
# ==========================================


def test_login_valido(ambiente):
    resposta = _login(ambiente, "user@x.com")
    assert resposta.status_code == 200
    dados = resposta.get_json()["data"]
    assert dados["token"]
    assert dados["usuario"]["email"] == "user@x.com"
    assert dados["usuario"]["papel"] == "USER"
    assert set(dados["usuario"].keys()) == CAMPOS_PUBLICOS


def test_login_senha_invalida(ambiente):
    resposta = _login(ambiente, "user@x.com", senha="senhaErrada99")
    assert resposta.status_code == 401


def test_login_email_inexistente(ambiente):
    resposta = _login(ambiente, "naoexiste@x.com")
    assert resposta.status_code == 401


def test_login_usuario_desativado(ambiente):
    resposta = _login(ambiente, "off@x.com")
    assert resposta.status_code == 401


def test_resposta_generica_para_credenciais_invalidas(ambiente):
    inexistente = _login(ambiente, "naoexiste@x.com")
    senha_errada = _login(ambiente, "user@x.com", senha="senhaErrada99")
    assert inexistente.status_code == senha_errada.status_code == 401
    assert inexistente.get_json() == senha_errada.get_json()
    assert "naoexiste" not in inexistente.get_data(as_text=True)
    assert inexistente.get_json()["meta"]["error"] == "Credenciais inválidas."


def test_login_sem_email_ou_senha_generico(ambiente):
    corpo_vazio = ambiente["cliente"].post("/api/v1/auth/login", json={})
    sem_email = ambiente["cliente"].post("/api/v1/auth/login", json={"senha": "x"})
    assert corpo_vazio.status_code == sem_email.status_code == 401
    assert corpo_vazio.get_json() == sem_email.get_json()


# ==========================================
# SESSÃO E TOKEN
# ==========================================


def test_sessao_criada_apos_login(ambiente):
    _login(ambiente, "user@x.com")
    sessao = ambiente["Session"]()
    try:
        registros = sessao.query(Sessao).all()
        assert len(registros) == 1
        assert registros[0].origem == "web"
    finally:
        sessao.close()


def test_token_bruto_nao_persistido(ambiente):
    resposta = _login(ambiente, "user@x.com")
    token = _token_da(resposta)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

    sessao = ambiente["Session"]()
    try:
        registro = sessao.query(Sessao).first()
        assert registro.token_hash == token_hash
        assert registro.token_hash != token
        assert token not in registro.token_hash
        assert token not in str(registro.origem or "")
    finally:
        sessao.close()


def test_me_autenticado_com_sessao(ambiente):
    token = _token_da(_login(ambiente, "user@x.com"))
    resposta = ambiente["cliente"].get("/api/v1/me", headers=_cabecalho_token(token))
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["email"] == "user@x.com"


def test_me_sem_sessao(ambiente):
    resposta = ambiente["cliente"].get("/api/v1/me")
    assert resposta.status_code == 401


def test_me_com_token_invalido(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/me", headers=_cabecalho_token("token-invalido-qualquer")
    )
    assert resposta.status_code == 401


def test_logout(ambiente):
    token = _token_da(_login(ambiente, "user@x.com"))
    resposta = ambiente["cliente"].post("/api/v1/auth/logout", headers=_cabecalho_token(token))
    assert resposta.status_code == 200
    assert resposta.get_json()["data"] == {"logout": True}


def test_token_apos_logout_retorna_401(ambiente):
    token = _token_da(_login(ambiente, "user@x.com"))
    ambiente["cliente"].post("/api/v1/auth/logout", headers=_cabecalho_token(token))
    resposta = ambiente["cliente"].get("/api/v1/me", headers=_cabecalho_token(token))
    assert resposta.status_code == 401


def test_logout_sem_token_retorna_401(ambiente):
    resposta = ambiente["cliente"].post("/api/v1/auth/logout")
    assert resposta.status_code == 401


def test_logout_duplicado_idempotente(ambiente):
    token = _token_da(_login(ambiente, "user@x.com"))
    assert (
        ambiente["cliente"].post("/api/v1/auth/logout", headers=_cabecalho_token(token)).status_code
        == 200
    )
    resposta = ambiente["cliente"].post("/api/v1/auth/logout", headers=_cabecalho_token(token))
    assert resposta.status_code == 200
    assert "error" not in resposta.get_json()


def test_sessao_expirada_retorna_401(ambiente):
    token = _token_da(_login(ambiente, "user@x.com"))
    sessao = ambiente["Session"]()
    try:
        registro = sessao.query(Sessao).first()
        registro.expira_em = datetime.now() - timedelta(seconds=1)
        sessao.commit()
    finally:
        sessao.close()

    resposta = ambiente["cliente"].get("/api/v1/me", headers=_cabecalho_token(token))
    assert resposta.status_code == 401


def test_usuario_desativado_apos_criar_sessao(ambiente):
    token = _token_da(_login(ambiente, "user@x.com"))
    assert (
        ambiente["cliente"].get("/api/v1/me", headers=_cabecalho_token(token)).status_code == 200
    )

    sessao = ambiente["Session"]()
    try:
        usuario = sessao.get(usuarios.Usuario, ambiente["usuarios"]["user"])
        usuarios.desativar_usuario(usuario, session=sessao)
    finally:
        sessao.close()

    resposta = ambiente["cliente"].get("/api/v1/me", headers=_cabecalho_token(token))
    assert resposta.status_code == 401


def test_falhas_de_autenticacao_sao_indistinguiveis(ambiente):
    respostas = [
        ambiente["cliente"].get("/api/v1/me", headers=_cabecalho_token("token-inexistente")),
        ambiente["cliente"].get("/api/v1/me", headers=_cabecalho_token("token-invalido")),
        ambiente["cliente"].get(
            "/api/v1/me", headers=_cabecalho_token("token-revogado-ou-expirado")
        ),
    ]
    corpos = [resposta.get_json() for resposta in respostas]
    assert all(resposta.status_code == 401 for resposta in respostas)
    assert corpos[0] == corpos[1] == corpos[2]


# ==========================================
# API KEY E TELEGRAM CONTINUAM FUNCIONANDO
# ==========================================


def test_api_key_continua_funcionando(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/me", headers={"X-API-Key": ambiente["chaves"]["user"]}
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["email"] == "user@x.com"


def test_api_key_precedencia_sobre_sessao(ambiente):
    token = _token_da(_login(ambiente, "alvo@x.com"))
    resposta = ambiente["cliente"].get(
        "/api/v1/me",
        headers={
            "X-API-Key": ambiente["chaves"]["user"],
            "X-Session-Token": token,
        },
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["email"] == "user@x.com"


def test_telegram_continua_funcionando(ambiente):
    sessao = ambiente["Session"]()
    try:
        usuario_tg = sessao.get(usuarios.Usuario, ambiente["usuarios"]["telegram"])
        assert telegram.usuario_do_telegram(9001, session=sessao).id == usuario_tg.id
    finally:
        sessao.close()

    resposta = _login(ambiente, "tg@x.com")
    assert resposta.status_code == 200
    token = _token_da(resposta)
    me = ambiente["cliente"].get("/api/v1/me", headers=_cabecalho_token(token))
    assert me.status_code == 200
    assert me.get_json()["data"]["telegram_vinculado"] is True


def test_autenticacao_web_independente_do_telegram(ambiente):
    resposta = _registrar(ambiente, email="semtelegram@x.com")
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["telegram_vinculado"] is False

    token = _token_da(_login(ambiente, "semtelegram@x.com"))
    me = ambiente["cliente"].get("/api/v1/me", headers=_cabecalho_token(token))
    assert me.status_code == 200
    assert me.get_json()["data"]["email"] == "semtelegram@x.com"


# ==========================================
# ISOLAMENTO E SEGREDOS
# ==========================================


def test_isolamento_entre_usuarios_no_me(ambiente):
    t_a = _token_da(_login(ambiente, "user@x.com"))
    t_b = _token_da(_login(ambiente, "alvo@x.com"))

    me_a = ambiente["cliente"].get("/api/v1/me", headers=_cabecalho_token(t_a)).get_json()["data"]
    me_b = ambiente["cliente"].get("/api/v1/me", headers=_cabecalho_token(t_b)).get_json()["data"]

    assert me_a["email"] == "user@x.com"
    assert me_b["email"] == "alvo@x.com"
    assert me_a["id"] != me_b["id"]


def test_ausencia_de_segredo_nas_respostas(ambiente):
    cliente = ambiente["cliente"]
    token = _token_da(_login(ambiente, "user@x.com"))

    respostas = [
        _registrar(ambiente, email="seguro@x.com", senha="senhaSecreta456"),
        cliente.get("/api/v1/me", headers=_cabecalho_token(token)),
        cliente.get("/api/v1/me", headers={"X-API-Key": ambiente["chaves"]["user"]}),
        cliente.post("/api/v1/auth/logout", headers=_cabecalho_token(token)),
        _login(ambiente, "user@x.com", senha="senhaErrada99"),
    ]
    for segredo in _segredos(ambiente, token=token):
        for resposta in respostas:
            assert segredo not in resposta.get_data(as_text=True), segredo
    for resposta in respostas:
        assert "senhaErrada99" not in resposta.get_data(as_text=True)

    corpo_geral = "\n".join(r.get_data(as_text=True) for r in respostas)
    for proibido in CAMPOS_PROIBIDOS:
        assert proibido not in corpo_geral


def test_me_nao_retorna_segredos(ambiente):
    token = _token_da(_login(ambiente, "user@x.com"))
    resposta = ambiente["cliente"].get("/api/v1/me", headers=_cabecalho_token(token))
    dados = resposta.get_json()["data"]
    for proibido in ("senha", "senha_hash", "token", "token_hash", "chave_hash"):
        assert proibido not in dados
    corpo = resposta.get_data(as_text=True)
    assert "senha1234" not in corpo
    assert token not in corpo


def test_ausencia_de_segredo_na_auditoria(ambiente):
    cliente = ambiente["cliente"]
    _registrar(ambiente, email="auditado@x.com", senha="auditadaSenha123")
    _login(ambiente, "auditado@x.com")
    _login(ambiente, "auditado@x.com", senha="senhaErrada99")
    _login(ambiente, "naoexiste@x.com")
    token = _token_da(_login(ambiente, "user@x.com"))
    cliente.post("/api/v1/auth/logout", headers=_cabecalho_token(token))

    texto = _texto_auditoria(ambiente)
    assert "auditadaSenha123" not in texto
    assert "senha1234" not in texto
    assert token not in texto
    for proibido in ("senha_hash", "token_hash", "chave_hash"):
        assert proibido not in texto


def test_auditoria_registra_fluxos_web(ambiente):
    _registrar(ambiente, email="fluxo@x.com")
    _login(ambiente, "fluxo@x.com")
    _login(ambiente, "fluxo@x.com", senha="senhaErrada99")
    token = _token_da(_login(ambiente, "fluxo@x.com"))
    ambiente["cliente"].post("/api/v1/auth/logout", headers=_cabecalho_token(token))

    acoes = {e.acao for e in _auditoria(ambiente["Session"])}
    assert "USUARIO_CRIADO" in acoes
    assert "LOGIN" in acoes
    assert "SESSAO_CRIADA" in acoes
    assert "SESSAO_REVOGADA" in acoes
