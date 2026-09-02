"""Testes da camada HTTP/API (Fase 5, Etapa 10).

Cobrem a integração aditiva ao Flask (habilitada/desabilitada), autenticação
via API Key (services/chaves_api.py) e sessão (services/sessoes.py),
autorização centralizada (services/autorizacao.py), envelope JSON, serializers
sem campos secretos, os endpoints de leitura e o isolamento entre usuários.
"""
import hashlib
import os
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import config
from api import dependencias, integrar_api
from pipeline_dados.banco_dados import (
    AlertaEvento,
    Ativo,
    AtivoPerfil,
    Base,
    DocumentosQualitativos,
    IndicadorHistorico,
    TipoAtivo,
)
from services import chaves_api, sessoes, usuarios


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
    seed.sessao.close()

    return {
        "cliente": cliente,
        "Session": Session,
        "usuarios": seed.usuarios,
        "chaves": seed.chaves,
        "sessoes": seed.sessoes,
        "ativo_fii_id": seed.ativo_fii_id,
        "ativo_acao_id": seed.ativo_acao_id,
    }


class _Semear:
    """Popula o banco de testes: usuários, chaves, sessões e dados de leitura."""

    def __init__(self, sessao):
        self.sessao = sessao
        self.usuarios = {}
        self.chaves = {}
        self.sessoes = {}

    def _criar_usuario(self, nome, email, papel, ativo=True):
        return usuarios.criar_usuario(
            nome=nome, email=email, senha="senha1234", papel=papel,
            ativo=ativo, session=self.sessao,
        )

    def rodar(self):
        s = self.sessao

        self.usuarios["superadmin"] = self._criar_usuario(
            "Root", "root@x.com", usuarios.SUPERADMIN
        )
        self.usuarios["admin"] = self._criar_usuario(
            "Admin", "admin@x.com", usuarios.ADMIN
        )
        self.usuarios["user"] = self._criar_usuario(
            "Usuario", "user@x.com", usuarios.USER
        )
        self.usuarios["visitor"] = self._criar_usuario(
            "Visitante", "visitor@x.com", usuarios.VISITOR
        )
        self.usuarios["desativado"] = self._criar_usuario(
            "Desativado", "off@x.com", usuarios.USER, ativo=False
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

        fii = Ativo(ticker="GARE11", cnpj="00.000.000/0001-11", tipo=TipoAtivo.FII)
        s.add(fii)
        s.flush()
        s.add(AtivoPerfil(ativo_id=fii.id, setor="Logística", tipo_fii="Tijolo"))

        acao = Ativo(ticker="PETR4", cnpj="33.000.167/0001-01", tipo=TipoAtivo.ACAO)
        s.add(acao)
        s.flush()
        s.add(
            AtivoPerfil(
                ativo_id=acao.id,
                setor="Petróleo, Gás & Biocombustíveis",
                tipo_fii=None,
            )
        )

        self.ativo_fii_id = fii.id
        self.ativo_acao_id = acao.id

        s.add(
            IndicadorHistorico(
                ativo_id=fii.id,
                tipo_ativo="FII",
                indicador="pvp",
                valor_atual=Decimal("0.95"),
                valor_anterior=Decimal("0.90"),
                variacao_percentual=Decimal("5.5556"),
                data_referencia=date(2025, 1, 10),
                data_ultima_alteracao=date(2025, 1, 15),
                ultima_coleta=datetime(2025, 1, 15, 8, 0, 0),
                origem="teste",
            )
        )

        s.add(
            AlertaEvento(
                tipo_alerta="QUALIDADE",
                tipo_ativo="FII",
                ativo_id=fii.id,
                indicador="pvp",
                valor_anterior=Decimal("0.90"),
                valor_atual=Decimal("0.95"),
                variacao_percentual=Decimal("5.5556"),
                regra="FORA_FAIXA",
                motivo="Valor fora da faixa usual.",
                severidade="WARNING",
                recomendacao="Revisar fonte.",
                origem="teste",
                data_referencia=date(2025, 1, 10),
            )
        )
        s.add(
            AlertaEvento(
                tipo_alerta="CRITICO",
                tipo_ativo="FII",
                ativo_id=fii.id,
                indicador="cotistas",
                valor_anterior=Decimal("0"),
                valor_atual=Decimal("1000000"),
                variacao_percentual=Decimal("0"),
                regra="VALOR_ZERO_SUSPEITO",
                motivo="Zero suspeito.",
                severidade="CRITICO",
                recomendacao="Verificar.",
                origem="teste",
            )
        )

        s.add(
            DocumentosQualitativos(
                ativo_id=fii.id,
                data_publicacao=date(2025, 1, 20),
                tipo_documento="Relatorio Gerencial",
                url_pdf="https://drive.example.com/arquivo.pdf",
                assunto="Informe de janeiro",
                id_b3="DOC-001",
                status_processamento="SALVO",
                texto_extraido="TEXTO INTERNO NÃO PODE VAZAR",
                resumo_ia="RESUMO IA NÃO PODE VAZAR",
            )
        )

        s.commit()


def _cabecalho(ambiente, chave):
    return {"X-API-Key": ambiente["chaves"][chave]}


def _cabecalho_sessao(ambiente, chave):
    return {"X-Session-Token": ambiente["sessoes"][chave]}


# ==========================================
# INTEGRAÇÃO E HABILITAÇÃO
# ==========================================


def test_api_desabilitada_nao_registra_rotas():
    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.route("/")
    def home():
        return "ok"

    assert integrar_api(app, habilitada=False) is False
    cliente = app.test_client()
    assert cliente.get("/api/v1/me").status_code == 404
    assert cliente.get("/api/v1/ativos").status_code == 404
    assert cliente.get("/").status_code == 200


def test_integracao_respeita_config_api_enabled(monkeypatch):
    monkeypatch.setattr(config, "API_ENABLED", False)
    app = Flask(__name__)
    assert integrar_api(app) is False

    monkeypatch.setattr(config, "API_ENABLED", True)
    app2 = Flask(__name__)
    assert integrar_api(app2) is True


def test_api_habilitada_registra_rotas(ambiente):
    rotas = {str(r) for r in ambiente["cliente"].application.url_map.iter_rules()}
    for esperada in (
        "/api/v1/ativos",
        "/api/v1/indicadores",
        "/api/v1/indicadores/<int:ativo_id>/historico",
        "/api/v1/alertas",
        "/api/v1/documentos",
        "/api/v1/relatorios",
        "/api/v1/me",
        "/api/v1/healthz",
    ):
        assert esperada in rotas


def test_main_integra_api_de_forma_aditiva():
    caminho = os.path.join(os.path.dirname(__file__), "..", "main.py")
    with open(caminho, encoding="utf-8") as arquivo:
        conteudo = arquivo.read()
    assert "from api import integrar_api" in conteudo
    assert "config.API_ENABLED" in conteudo
    assert "integrar_api(app)" in conteudo


# ==========================================
# ROTA PÚBLICA E ENVELOPE
# ==========================================


def test_rota_publica_sem_autenticacao(ambiente):
    resposta = ambiente["cliente"].get("/api/v1/healthz")
    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados["status"] == "success"
    assert dados["data"] == {"status": "ok", "api": "v1"}
    assert dados["meta"] == {}


def test_rota_privada_sem_autenticacao_retorna_401(ambiente):
    resposta = ambiente["cliente"].get("/api/v1/ativos")
    assert resposta.status_code == 401
    dados = resposta.get_json()
    assert dados["status"] == "error"
    assert dados["data"] is None
    assert "error" in dados["meta"]


def test_rota_inexistente_retorna_404_json(ambiente):
    resposta = ambiente["cliente"].get("/api/v1/nao_existe")
    assert resposta.status_code == 404
    assert resposta.get_json()["status"] == "error"


def test_metodo_nao_permitido_retorna_405_json(ambiente):
    resposta = ambiente["cliente"].post("/api/v1/ativos")
    assert resposta.status_code == 405
    assert resposta.get_json()["status"] == "error"


def test_rota_inexistente_fora_da_api_mantem_legado():
    app = Flask(__name__)
    app.config["TESTING"] = True
    integrar_api(app, habilitada=True)
    resposta = app.test_client().get("/caminho_legado")
    assert resposta.status_code == 404


# ==========================================
# AUTENTICAÇÃO POR API KEY
# ==========================================


def test_api_key_valida_autentica(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/me", headers=_cabecalho(ambiente, "user")
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["email"] == "user@x.com"


def test_api_key_invalida_retorna_401(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/me", headers={"X-API-Key": "chave-invalida-qualquer"}
    )
    assert resposta.status_code == 401
    assert resposta.get_json()["status"] == "error"


def test_api_key_expirada_retorna_401(ambiente):
    sessao = ambiente["Session"]()
    usuario = (
        sessao.query(usuarios.Usuario)
        .filter(usuarios.Usuario.email == "user@x.com")
        .first()
    )
    registro = (
        sessao.query(chaves_api.ChaveApi)
        .filter(chaves_api.ChaveApi.usuario_id == usuario.id)
        .first()
    )
    registro.expira_em = datetime.now() - timedelta(seconds=1)
    sessao.commit()
    sessao.close()

    resposta = ambiente["cliente"].get(
        "/api/v1/me", headers={"X-API-Key": ambiente["chaves"]["user"]}
    )
    assert resposta.status_code == 401


def test_api_key_revogada_retorna_401(ambiente):
    sessao = ambiente["Session"]()
    usuario = (
        sessao.query(usuarios.Usuario)
        .filter(usuarios.Usuario.email == "user@x.com")
        .first()
    )
    registro = (
        sessao.query(chaves_api.ChaveApi)
        .filter(chaves_api.ChaveApi.usuario_id == usuario.id)
        .first()
    )
    chaves_api.revogar_chave_api(usuario, registro.id, session=sessao)
    sessao.close()

    resposta = ambiente["cliente"].get(
        "/api/v1/me", headers={"X-API-Key": ambiente["chaves"]["user"]}
    )
    assert resposta.status_code == 401


def test_usuario_desativado_retorna_401(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/me", headers=_cabecalho(ambiente, "desativado")
    )
    assert resposta.status_code == 401


def test_autenticacao_por_sessao_existente(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/me", headers=_cabecalho_sessao(ambiente, "user")
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["email"] == "user@x.com"


def test_sessao_invalida_retorna_401(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/me", headers={"X-Session-Token": "token-invalido"}
    )
    assert resposta.status_code == 401


# ==========================================
# AUTORIZAÇÃO POR PAPEL
# ==========================================


def test_permissao_concedida(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/ativos", headers=_cabecalho(ambiente, "user")
    )
    assert resposta.status_code == 200


def test_permissao_negada_retorna_403(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/ativos", headers=_cabecalho(ambiente, "visitor")
    )
    assert resposta.status_code == 403
    dados = resposta.get_json()
    assert dados["status"] == "error"
    assert dados["data"] is None


def test_visitor_nao_acessa_alertas(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/alertas", headers=_cabecalho(ambiente, "visitor")
    )
    assert resposta.status_code == 403


def test_superadmin_acessa_tudo(ambiente):
    for rota in (
        "/api/v1/ativos",
        "/api/v1/indicadores",
        "/api/v1/alertas",
        "/api/v1/documentos",
        "/api/v1/relatorios",
        "/api/v1/me",
    ):
        resposta = ambiente["cliente"].get(rota, headers=_cabecalho(ambiente, "superadmin"))
        assert resposta.status_code == 200, rota


def test_admin_acessa_recursos_previstos(ambiente):
    for rota in (
        "/api/v1/ativos",
        "/api/v1/indicadores",
        "/api/v1/documentos",
        "/api/v1/relatorios",
        "/api/v1/me",
    ):
        resposta = ambiente["cliente"].get(rota, headers=_cabecalho(ambiente, "admin"))
        assert resposta.status_code == 200, rota
    resposta = ambiente["cliente"].get(
        "/api/v1/alertas", headers=_cabecalho(ambiente, "admin")
    )
    assert resposta.status_code == 403


def test_user_acessa_endpoints_de_consulta(ambiente):
    for rota in (
        "/api/v1/ativos",
        "/api/v1/indicadores",
        "/api/v1/alertas",
        "/api/v1/documentos",
        "/api/v1/relatorios",
        "/api/v1/me",
    ):
        resposta = ambiente["cliente"].get(rota, headers=_cabecalho(ambiente, "user"))
        assert resposta.status_code == 200, rota


# ==========================================
# /ME E SERIALIZERS SEM SEGREDOS
# ==========================================


def test_me_retorna_dados_nao_sensiveis(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/me", headers=_cabecalho(ambiente, "user")
    )
    dados = resposta.get_json()["data"]
    assert dados["email"] == "user@x.com"
    assert dados["papel"] == "USER"
    for campo_proibido in ("senha_hash", "sessoes", "chaves_api", "chave_hash", "token"):
        assert campo_proibido not in dados
    assert "senha" not in resposta.get_data(as_text=True)


def test_envelope_json_sucesso(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/ativos", headers=_cabecalho(ambiente, "user")
    )
    dados = resposta.get_json()
    assert set(dados.keys()) == {"status", "data", "meta"}
    assert dados["status"] == "success"
    assert isinstance(dados["data"], list)
    assert isinstance(dados["meta"], dict)


def test_isolamento_entre_usuarios_no_me(ambiente):
    r1 = ambiente["cliente"].get(
        "/api/v1/me", headers=_cabecalho(ambiente, "user")
    )
    r2 = ambiente["cliente"].get(
        "/api/v1/me", headers=_cabecalho(ambiente, "admin")
    )
    assert r1.get_json()["data"]["email"] == "user@x.com"
    assert r2.get_json()["data"]["email"] == "admin@x.com"
    assert r1.get_json()["data"]["id"] != r2.get_json()["data"]["id"]


# ==========================================
# ENDPOINTS DE LEITURA
# ==========================================


def test_listar_ativos(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/ativos", headers=_cabecalho(ambiente, "user")
    )
    assert resposta.status_code == 200
    dados = resposta.get_json()
    tickers = {item["ticker"] for item in dados["data"]}
    assert tickers == {"GARE11", "PETR4"}
    assert dados["meta"]["total"] == 2


def test_filtro_de_ativos(ambiente):
    base = _cabecalho(ambiente, "user")
    cliente = ambiente["cliente"]
    assert {
        item["ticker"] for item in cliente.get("/api/v1/ativos?tipo=FII", headers=base).get_json()["data"]
    } == {"GARE11"}
    assert {
        item["ticker"] for item in cliente.get("/api/v1/ativos?tipo=ACAO", headers=base).get_json()["data"]
    } == {"PETR4"}
    assert {
        item["ticker"] for item in cliente.get("/api/v1/ativos?ticker=GAR", headers=base).get_json()["data"]
    } == {"GARE11"}
    assert cliente.get("/api/v1/ativos?tipo=INVALIDO", headers=base).status_code == 400


def test_listar_indicadores(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/indicadores", headers=_cabecalho(ambiente, "user")
    )
    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados["meta"]["total"] == 1
    item = dados["data"][0]
    assert item["indicador"] == "pvp"
    assert item["ticker"] == "GARE11"
    assert item["valor_atual"] == 0.95
    assert item["valor_anterior"] == 0.90
    assert item["data_ultima_alteracao"] == "2025-01-15"


def test_filtro_de_indicadores(ambiente):
    base = _cabecalho(ambiente, "user")
    cliente = ambiente["cliente"]
    assert cliente.get(
        "/api/v1/indicadores?tipo_ativo=FII", headers=base
    ).get_json()["meta"]["total"] == 1
    assert cliente.get(
        f"/api/v1/indicadores?ativo_id={ambiente['ativo_fii_id']}", headers=base
    ).get_json()["meta"]["total"] == 1
    assert cliente.get(
        "/api/v1/indicadores?indicador=pvp", headers=base
    ).get_json()["meta"]["total"] == 1
    assert cliente.get(
        "/api/v1/indicadores?tipo_ativo=INVALIDO", headers=base
    ).status_code == 400


def test_historico_do_ativo(ambiente):
    resposta = ambiente["cliente"].get(
        f"/api/v1/indicadores/{ambiente['ativo_fii_id']}/historico",
        headers=_cabecalho(ambiente, "user"),
    )
    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados["meta"]["ticker"] == "GARE11"
    assert dados["data"][0]["indicador"] == "pvp"
    assert dados["data"][0]["valor_atual"] == 0.95
    assert dados["data"][0]["valor_anterior"] == 0.90
    assert dados["data"][0]["variacao_percentual"] == 5.5556


def test_historico_de_ativo_inexistente_retorna_404(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/indicadores/999999/historico", headers=_cabecalho(ambiente, "user")
    )
    assert resposta.status_code == 404


def test_listar_alertas(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/alertas", headers=_cabecalho(ambiente, "user")
    )
    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados["meta"]["total"] == 2
    severidades = {item["severidade"] for item in dados["data"]}
    assert severidades == {"WARNING", "CRITICO"}


def test_filtros_de_alertas(ambiente):
    base = _cabecalho(ambiente, "user")
    cliente = ambiente["cliente"]
    assert cliente.get("/api/v1/alertas?tipo=CRITICO", headers=base).get_json()["meta"]["total"] == 1
    assert cliente.get("/api/v1/alertas?severidade=WARNING", headers=base).get_json()["meta"]["total"] == 1
    assert cliente.get(
        f"/api/v1/alertas?ativo_id={ambiente['ativo_fii_id']}", headers=base
    ).get_json()["meta"]["total"] == 2
    assert cliente.get("/api/v1/alertas?ticker=GARE11", headers=base).get_json()["meta"]["total"] == 2
    assert cliente.get("/api/v1/alertas?tipo_ativo=FII", headers=base).get_json()["meta"]["total"] == 2
    assert cliente.get("/api/v1/alertas?tipo=INVALIDO", headers=base).status_code == 400
    assert cliente.get("/api/v1/alertas?ativo_id=abc", headers=base).status_code == 400


def test_listar_documentos_sem_conteudo_pesado(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/documentos", headers=_cabecalho(ambiente, "user")
    )
    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados["meta"]["total"] == 1
    item = dados["data"][0]
    assert item["ticker"] == "GARE11"
    assert item["tipo_documento"] == "Relatorio Gerencial"
    texto_corpo = resposta.get_data(as_text=True)
    assert "TEXTO INTERNO" not in texto_corpo
    assert "RESUMO IA" not in texto_corpo
    for campo_proibido in ("texto_extraido", "resumo_ia", "log_erro", "hash_sha256"):
        assert campo_proibido not in item


def test_filtros_de_documentos(ambiente):
    base = _cabecalho(ambiente, "user")
    cliente = ambiente["cliente"]
    assert cliente.get("/api/v1/documentos?status=SALVO", headers=base).get_json()["meta"]["total"] == 1
    assert cliente.get(
        "/api/v1/documentos?tipo_documento=Relatorio Gerencial", headers=base
    ).get_json()["meta"]["total"] == 1
    assert cliente.get(
        f"/api/v1/documentos?ativo_id={ambiente['ativo_fii_id']}", headers=base
    ).get_json()["meta"]["total"] == 1


def test_relatorios_usam_dados_existentes(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/relatorios", headers=_cabecalho(ambiente, "user")
    )
    assert resposta.status_code == 200
    dados = resposta.get_json()["data"]
    assert dados["ativos"]["total"] == 2
    assert dados["ativos"]["por_tipo"] == {"ACAO": 1, "FII": 1}
    assert dados["indicadores"]["total"] == 1
    assert dados["alertas"]["total"] == 2
    assert dados["alertas"]["por_severidade"] == {"WARNING": 1, "CRITICO": 1}
    assert dados["documentos"]["total"] == 1
    assert "gerado_em" in dados


# ==========================================
# ERROS SEM VAZAMENTO
# ==========================================


def test_erro_interno_sem_stack_trace(ambiente, monkeypatch):
    def _quebrada():
        raise RuntimeError("falha interna super secreta")

    monkeypatch.setattr(dependencias, "obter_sessao", _quebrada)
    resposta = ambiente["cliente"].get(
        "/api/v1/ativos", headers=_cabecalho(ambiente, "user")
    )
    assert resposta.status_code == 500
    corpo = resposta.get_data(as_text=True)
    assert "Traceback" not in corpo
    assert "falha interna" not in corpo
    assert "RuntimeError" not in corpo
    dados = resposta.get_json()
    assert dados["status"] == "error"
    assert dados["data"] is None
    assert dados["meta"]["error"] == "Erro interno do servidor."


def test_nenhuma_resposta_vaza_segredos_de_autenticacao(ambiente):
    sessao = ambiente["Session"]()
    usuario = (
        sessao.query(usuarios.Usuario)
        .filter(usuarios.Usuario.email == "user@x.com")
        .first()
    )
    registro = (
        sessao.query(chaves_api.ChaveApi)
        .filter(chaves_api.ChaveApi.usuario_id == usuario.id)
        .first()
    )
    sessao.close()
    chave_bruta = ambiente["chaves"]["user"]
    chave_hash = registro.chave_hash

    resposta = ambiente["cliente"].get(
        "/api/v1/me", headers={"X-API-Key": chave_bruta}
    )
    corpo = resposta.get_data(as_text=True)
    assert chave_bruta not in corpo
    assert chave_hash not in corpo


def test_filtro_invalido_de_ativos_nao_revela_informacao(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/ativos?tipo=INVALIDO", headers=_cabecalho(ambiente, "user")
    )
    assert resposta.status_code == 400
    assert "tipo" in resposta.get_json()["meta"]["error"]
