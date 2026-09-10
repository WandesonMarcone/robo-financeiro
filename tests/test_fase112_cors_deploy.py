"""Fase 11, Etapa 11.2 — CORS, API_ENABLED e contrato de consumo web.

Cobre allowlist CORS (permitido/bloqueado, sem wildcard), fail-closed de
``API_ENABLED``, autenticacao somente por header e regressao de
autorizacao/escopo. Nao cria endpoints novos.
"""
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import config
from api import cors as cors_mod
from api import dependencias, integrar_api
from pipeline_dados.banco_dados import Ativo, Base, Notificacao, TipoAtivo
from services import ativos_acompanhados, carteira, chaves_api, sessoes, usuarios

ORIGEM_OK = "https://app.exemplo.com"
ORIGEM_DEV = "http://localhost:5173"
ORIGEM_BLOQUEADA = "https://evil.example"


def _app_api(monkeypatch, origens=(ORIGEM_OK, ORIGEM_DEV), habilitada=True):
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
    monkeypatch.setattr(config, "API_CORS_ORIGINS", tuple(origens))

    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.route("/")
    def home():
        return "ok"

    integrada = integrar_api(app, habilitada=habilitada)
    return {
        "app": app,
        "cliente": app.test_client(),
        "Session": Session,
        "integrada": integrada,
    }


def _semear_user(Session):
    sessao = Session()
    user = usuarios.criar_usuario(
        nome="Usuario",
        email="user@f112.com",
        senha="senha1234",
        papel=usuarios.USER,
        session=sessao,
    )
    outro = usuarios.criar_usuario(
        nome="Outro",
        email="outro@f112.com",
        senha="senha1234",
        papel=usuarios.USER,
        session=sessao,
    )
    ativo = Ativo(ticker="PETR4", cnpj="33.000.167/0001-01", tipo=TipoAtivo.ACAO)
    sessao.add(ativo)
    sessao.flush()
    token = sessoes.criar_sessao(user, origem="web", session=sessao)
    chave = chaves_api.criar_chave_api(user, "chave-user", session=sessao)
    carteira.adicionar_posicao(
        user, ativo.id, quantidade="10", preco_medio="20", session=sessao
    )
    ativos_acompanhados.adicionar_acompanhamento(user, ativo.id, session=sessao)
    notif_propria = Notificacao(
        usuario_id=user.id,
        tipo="ALERTA",
        titulo="propria",
        mensagem="ok",
        canal="web",
        status="GERADA",
    )
    notif_terceiro = Notificacao(
        usuario_id=outro.id,
        tipo="ALERTA",
        titulo="terceiro",
        mensagem="secreto",
        canal="web",
        status="GERADA",
    )
    sessao.add_all([notif_propria, notif_terceiro])
    sessao.commit()
    ids = {
        "user": user.id,
        "outro": outro.id,
        "ativo": ativo.id,
        "notif_propria": notif_propria.id,
        "notif_terceiro": notif_terceiro.id,
    }
    sessao.close()
    return {"token": token, "chave": chave, "ids": ids}


def _h_sessao(token):
    return {"X-Session-Token": token}


# ==========================================
# CORS
# ==========================================


def test_cors_origem_permitida_recebe_allow_origin(monkeypatch):
    env = _app_api(monkeypatch)
    _semear_user(env["Session"])
    resposta = env["cliente"].get(
        "/api/v1/healthz",
        headers={"Origin": ORIGEM_OK},
    )
    assert resposta.status_code == 200
    assert resposta.headers.get("Access-Control-Allow-Origin") == ORIGEM_OK
    assert resposta.headers.get("Access-Control-Allow-Credentials") == "true"
    assert "X-Session-Token" in resposta.headers.get("Access-Control-Allow-Headers", "")
    assert resposta.headers.get("Vary") == "Origin"
    assert resposta.headers.get("Access-Control-Allow-Origin") != "*"


def test_cors_origem_dev_configurada_e_permitida(monkeypatch):
    env = _app_api(monkeypatch)
    resposta = env["cliente"].get(
        "/api/v1/healthz",
        headers={"Origin": ORIGEM_DEV},
    )
    assert resposta.status_code == 200
    assert resposta.headers.get("Access-Control-Allow-Origin") == ORIGEM_DEV


def test_cors_origem_bloqueada_nao_recebe_allow_origin(monkeypatch):
    env = _app_api(monkeypatch)
    resposta = env["cliente"].get(
        "/api/v1/healthz",
        headers={"Origin": ORIGEM_BLOQUEADA},
    )
    assert resposta.status_code == 200
    assert "Access-Control-Allow-Origin" not in resposta.headers
    assert "Access-Control-Allow-Credentials" not in resposta.headers


def test_cors_sem_allowlist_nao_emite_cabecalhos(monkeypatch):
    env = _app_api(monkeypatch, origens=())
    resposta = env["cliente"].get(
        "/api/v1/healthz",
        headers={"Origin": ORIGEM_OK},
    )
    assert resposta.status_code == 200
    assert "Access-Control-Allow-Origin" not in resposta.headers


def test_cors_preflight_permitido_retorna_204(monkeypatch):
    env = _app_api(monkeypatch)
    resposta = env["cliente"].options(
        "/api/v1/me",
        headers={
            "Origin": ORIGEM_OK,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Session-Token",
        },
    )
    assert resposta.status_code == 204
    assert resposta.headers.get("Access-Control-Allow-Origin") == ORIGEM_OK
    assert "GET" in resposta.headers.get("Access-Control-Allow-Methods", "")
    assert "X-Session-Token" in resposta.headers.get("Access-Control-Allow-Headers", "")


def test_cors_preflight_bloqueado_nao_libera_origem(monkeypatch):
    env = _app_api(monkeypatch)
    resposta = env["cliente"].options(
        "/api/v1/me",
        headers={
            "Origin": ORIGEM_BLOQUEADA,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resposta.status_code == 403
    assert "Access-Control-Allow-Origin" not in resposta.headers


def test_cors_nao_reflete_wildcard(monkeypatch):
    env = _app_api(monkeypatch, origens=())
    monkeypatch.setattr(config, "API_CORS_ORIGINS", ())
    resposta = env["cliente"].get(
        "/api/v1/healthz",
        headers={"Origin": "*"},
    )
    assert resposta.status_code == 200
    assert resposta.headers.get("Access-Control-Allow-Origin") != "*"
    assert "Access-Control-Allow-Origin" not in resposta.headers


def test_cors_nao_se_aplica_fora_do_prefixo_api(monkeypatch):
    env = _app_api(monkeypatch)
    resposta = env["cliente"].get("/", headers={"Origin": ORIGEM_OK})
    assert resposta.status_code == 200
    assert "Access-Control-Allow-Origin" not in resposta.headers


def test_cors_parse_descarta_wildcard_e_duplicatas():
    assert config.origens_cors_permitidas("https://a.com, https://a.com/, *") == (
        "https://a.com",
    )
    assert config.origens_cors_permitidas("*") == ()
    assert config.origens_cors_permitidas("") == ()


def test_cors_cabecalhos_nunca_usam_asterisco():
    assert cors_mod.cabecalhos_cors("*", permitidas=(ORIGEM_OK,)) == {}
    gerados = cors_mod.cabecalhos_cors(ORIGEM_OK, permitidas=(ORIGEM_OK,))
    assert gerados["Access-Control-Allow-Origin"] == ORIGEM_OK
    assert "*" not in gerados.values()


# ==========================================
# API_ENABLED
# ==========================================


def test_api_enabled_false_nao_registra_rotas_nem_cors(monkeypatch):
    env = _app_api(monkeypatch, habilitada=False)
    assert env["integrada"] is False
    cliente = env["cliente"]
    assert cliente.get("/api/v1/healthz").status_code == 404
    assert cliente.get("/api/v1/me").status_code == 404
    assert cliente.get("/api/v1/auth/login").status_code == 404
    resposta = cliente.get("/api/v1/healthz", headers={"Origin": ORIGEM_OK})
    assert "Access-Control-Allow-Origin" not in resposta.headers
    assert cliente.get("/").status_code == 200


def test_api_enabled_true_registra_rotas(monkeypatch):
    env = _app_api(monkeypatch, habilitada=True)
    assert env["integrada"] is True
    resposta = env["cliente"].get("/api/v1/healthz")
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["api"] == "v1"


def test_api_enabled_padrao_continua_fail_closed():
    assert config.API_ENABLED is False
    texto = open(config.__file__, encoding="utf-8").read()
    assert 'API_ENABLED = bool_ambiente("API_ENABLED"' in texto
    assert "API_ENABLED = True" not in texto


def test_nenhum_endpoint_novo_na_11_2(monkeypatch):
    env = _app_api(monkeypatch)
    metodos = []
    for regra in env["app"].url_map.iter_rules():
        caminho = str(regra)
        if not caminho.startswith("/api/v1"):
            continue
        for metodo in regra.methods or ():
            if metodo in ("HEAD", "OPTIONS"):
                continue
            metodos.append(f"{metodo} {caminho}")
    assert len(metodos) == 50


# ==========================================
# AUTENTICACAO (token so em header)
# ==========================================


def test_token_em_query_nao_autentica(monkeypatch):
    env = _app_api(monkeypatch)
    dados = _semear_user(env["Session"])
    resposta = env["cliente"].get(
        f"/api/v1/me?token={dados['token']}&X-Session-Token={dados['token']}"
    )
    assert resposta.status_code == 401


def test_sessao_no_header_autentica(monkeypatch):
    env = _app_api(monkeypatch)
    dados = _semear_user(env["Session"])
    resposta = env["cliente"].get("/api/v1/me", headers=_h_sessao(dados["token"]))
    assert resposta.status_code == 200
    corpo = resposta.get_json()["data"]
    assert corpo["email"] == "user@f112.com"
    assert "senha" not in corpo
    assert "token" not in corpo
    assert "senha_hash" not in corpo


def test_api_key_no_header_autentica(monkeypatch):
    env = _app_api(monkeypatch)
    dados = _semear_user(env["Session"])
    resposta = env["cliente"].get(
        "/api/v1/me", headers={"X-API-Key": dados["chave"]}
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["email"] == "user@f112.com"


# ==========================================
# REGRESSAO AUTORIZACAO / ESCOPO
# ==========================================


def test_rota_privada_sem_credencial_continua_401(monkeypatch):
    env = _app_api(monkeypatch)
    _semear_user(env["Session"])
    resposta = env["cliente"].get("/api/v1/ativos")
    assert resposta.status_code == 401
    assert resposta.get_json()["data"] is None


def test_notificacao_de_terceiro_continua_404(monkeypatch):
    env = _app_api(monkeypatch)
    dados = _semear_user(env["Session"])
    resposta = env["cliente"].get(
        f"/api/v1/notificacoes/{dados['ids']['notif_terceiro']}",
        headers=_h_sessao(dados["token"]),
    )
    assert resposta.status_code == 404
    assert resposta.get_json()["data"] is None


def test_notificacao_propria_acessivel(monkeypatch):
    env = _app_api(monkeypatch)
    dados = _semear_user(env["Session"])
    resposta = env["cliente"].get(
        f"/api/v1/notificacoes/{dados['ids']['notif_propria']}",
        headers=_h_sessao(dados["token"]),
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["titulo"] == "propria"
