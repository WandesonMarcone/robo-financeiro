"""Testes da Fase 6, Etapa 4 — Ativos acompanhados por usuário.

Cobrem a camada central ``services/ativos_acompanhados.py`` e os endpoints
``/api/v1/ativos-acompanhados``: criação, listagem, consulta e remoção com
isolamento total entre usuários (``services/escopo.py``), proteção contra
IDOR/BOLA, comportamento de usuários desativados/None e VISITOR, SUPERADMIN
administrativo, ausência de segredos e auditoria.
"""
import hashlib

import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api import dependencias, integrar_api
from pipeline_dados.banco_dados import (
    Ativo,
    AtivoAcompanhado,
    AuditoriaAcesso,
    Base,
    TipoAtivo,
)
from services import chaves_api, usuarios


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
    """Popula o banco de testes: usuários de vários papéis + ativos."""

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


def _registros(Session, modelo):
    sessao = Session()
    try:
        return sessao.query(modelo).order_by(modelo.id).all()
    finally:
        sessao.close()


def _segredos(ambiente):
    """Segredos que nunca podem aparecer em respostas/auditoria."""
    segredos = {"senha1234", "senha_hash", "token_hash", "chave_hash"}
    segredos.update(ambiente["chaves"].values())
    return segredos


def _corpo_resposta(ambiente, path, metodo, usuario, **campos):
    corpo = {"ativo_id": ambiente["ativos"]["PETR4"]}
    corpo.update(campos)
    return getattr(ambiente["cliente"], metodo)(
        path, json=corpo, headers=_h(ambiente, usuario)
    )


# ==========================================
# CRIAÇÃO E LISTAGEM
# ==========================================


def test_criar_acompanhamento(ambiente):
    resposta = _corpo_resposta(ambiente, "/api/v1/ativos-acompanhados", "post", "alice")
    assert resposta.status_code == 200
    dados = resposta.get_json()["data"]
    assert dados["ativo_id"] == ambiente["ativos"]["PETR4"]
    assert dados["ticker"] == "PETR4"
    assert dados["tipo"] == "ACAO"
    assert dados["id"] > 0


def test_criar_acompanhamento_duplicidade(ambiente):
    _corpo_resposta(ambiente, "/api/v1/ativos-acompanhados", "post", "alice")
    resposta = _corpo_resposta(ambiente, "/api/v1/ativos-acompanhados", "post", "alice")
    assert resposta.status_code == 400


def test_criar_acompanhamento_ativo_inexistente(ambiente):
    resposta = _corpo_resposta(
        ambiente, "/api/v1/ativos-acompanhados", "post", "alice", ativo_id=999999
    )
    assert resposta.status_code == 400


def test_criar_acompanhamento_ativo_id_invalido(ambiente):
    for valor in (0, -1, True, "PETR4", None):
        resposta = _corpo_resposta(
            ambiente, "/api/v1/ativos-acompanhados", "post", "alice", ativo_id=valor
        )
        assert resposta.status_code == 400, valor


def test_listar_acompanhamentos(ambiente):
    _corpo_resposta(ambiente, "/api/v1/ativos-acompanhados", "post", "alice")
    _corpo_resposta(
        ambiente,
        "/api/v1/ativos-acompanhados",
        "post",
        "alice",
        ativo_id=ambiente["ativos"]["GARE11"],
    )
    resposta = ambiente["cliente"].get(
        "/api/v1/ativos-acompanhados", headers=_h(ambiente, "alice")
    )
    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados["meta"]["total"] == 2
    tickers = {item["ticker"] for item in dados["data"]}
    assert tickers == {"PETR4", "GARE11"}


def test_listar_vazio_sem_acompanhamentos(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/ativos-acompanhados", headers=_h(ambiente, "bob")
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["meta"]["total"] == 0


def test_consultar_acompanhamento(ambiente):
    criado = _corpo_resposta(
        ambiente, "/api/v1/ativos-acompanhados", "post", "alice"
    ).get_json()["data"]
    resposta = ambiente["cliente"].get(
        f"/api/v1/ativos-acompanhados/{criado['id']}", headers=_h(ambiente, "alice")
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["ticker"] == "PETR4"


def test_remover_acompanhamento(ambiente):
    criado = _corpo_resposta(
        ambiente, "/api/v1/ativos-acompanhados", "post", "alice"
    ).get_json()["data"]
    resposta = ambiente["cliente"].delete(
        f"/api/v1/ativos-acompanhados/{criado['id']}", headers=_h(ambiente, "alice")
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["removido"] is True
    consulta = ambiente["cliente"].get(
        f"/api/v1/ativos-acompanhados/{criado['id']}", headers=_h(ambiente, "alice")
    )
    assert consulta.status_code == 404


# ==========================================
# ISOLAMENTO E IDOR/BOLA
# ==========================================


def test_dois_usuarios_isolados(ambiente):
    _corpo_resposta(ambiente, "/api/v1/ativos-acompanhados", "post", "alice")
    _corpo_resposta(
        ambiente,
        "/api/v1/ativos-acompanhados",
        "post",
        "bob",
        ativo_id=ambiente["ativos"]["GARE11"],
    )
    alice = ambiente["cliente"].get(
        "/api/v1/ativos-acompanhados", headers=_h(ambiente, "alice")
    ).get_json()["data"]
    bob = ambiente["cliente"].get(
        "/api/v1/ativos-acompanhados", headers=_h(ambiente, "bob")
    ).get_json()["data"]
    assert [item["ticker"] for item in alice] == ["PETR4"]
    assert [item["ticker"] for item in bob] == ["GARE11"]


def test_usuario_nao_acessa_acompanhamento_de_outro(ambiente):
    criado = _corpo_resposta(
        ambiente, "/api/v1/ativos-acompanhados", "post", "alice"
    ).get_json()["data"]
    resposta = ambiente["cliente"].get(
        f"/api/v1/ativos-acompanhados/{criado['id']}", headers=_h(ambiente, "bob")
    )
    assert resposta.status_code == 404


def test_remover_acompanhamento_de_outro_negado(ambiente):
    criado = _corpo_resposta(
        ambiente, "/api/v1/ativos-acompanhados", "post", "alice"
    ).get_json()["data"]
    resposta = ambiente["cliente"].delete(
        f"/api/v1/ativos-acompanhados/{criado['id']}", headers=_h(ambiente, "bob")
    )
    assert resposta.status_code == 404
    assert len(_registros(ambiente["Session"], AtivoAcompanhado)) == 1


def test_id_inexistente_nao_revela_informacao(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/ativos-acompanhados/999999", headers=_h(ambiente, "alice")
    )
    assert resposta.status_code == 404
    assert resposta.get_json()["meta"]["error"] == "Recurso não encontrado."


def test_manipular_usuario_id_ignorado(ambiente):
    corpo = {
        "ativo_id": ambiente["ativos"]["PETR4"],
        "usuario_id": _id(ambiente, "bob"),
    }
    resposta = ambiente["cliente"].post(
        "/api/v1/ativos-acompanhados", json=corpo, headers=_h(ambiente, "alice")
    )
    assert resposta.status_code == 200
    registros = _registros(ambiente["Session"], AtivoAcompanhado)
    assert len(registros) == 1
    assert registros[0].usuario_id == _id(ambiente, "alice")


# ==========================================
# PAPÉIS
# ==========================================


def test_visitor_nao_acessa(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/ativos-acompanhados", headers=_h(ambiente, "visitor")
    )
    assert resposta.status_code == 403


def test_desativado_nao_acessa(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/ativos-acompanhados", headers=_h(ambiente, "desativado")
    )
    assert resposta.status_code == 401


def test_superadmin_administra_acompanhamento_de_outro(ambiente):
    criado = _corpo_resposta(
        ambiente, "/api/v1/ativos-acompanhados", "post", "alice"
    ).get_json()["data"]
    resposta = ambiente["cliente"].get(
        f"/api/v1/ativos-acompanhados/{criado['id']}",
        headers=_h(ambiente, "superadmin"),
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["ticker"] == "PETR4"


def test_superadmin_pode_criar_para_si(ambiente):
    resposta = _corpo_resposta(
        ambiente, "/api/v1/ativos-acompanhados", "post", "superadmin"
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["ativo_id"] == ambiente["ativos"]["PETR4"]


def test_usuario_acompanha_ativo_servico(ambiente):
    from services import ativos_acompanhados

    sessao = ambiente["Session"]()
    try:
        alice = sessao.get(usuarios.Usuario, _id(ambiente, "alice"))
        assert (
            ativos_acompanhados.usuario_acompanha_ativo(
                alice, ambiente["ativos"]["PETR4"], session=sessao
            )
            is False
        )
        ativos_acompanhados.adicionar_acompanhamento(
            alice, ambiente["ativos"]["PETR4"], session=sessao
        )
        assert (
            ativos_acompanhados.usuario_acompanha_ativo(
                alice, ambiente["ativos"]["PETR4"], session=sessao
            )
            is True
        )
    finally:
        sessao.close()


# ==========================================
# AUDITORIA E SEGREDOS
# ==========================================


def test_auditoria_registra_operacoes(ambiente):
    _corpo_resposta(ambiente, "/api/v1/ativos-acompanhados", "post", "alice")
    criado = (
        ambiente["cliente"]
        .get("/api/v1/ativos-acompanhados", headers=_h(ambiente, "alice"))
        .get_json()["data"][0]
    )
    ambiente["cliente"].delete(
        f"/api/v1/ativos-acompanhados/{criado['id']}", headers=_h(ambiente, "alice")
    )
    texto = _texto_auditoria(ambiente)
    assert "ATIVO_ACOMPANHADO_ADICIONADO" in texto
    assert "ATIVO_ACOMPANHADO_REMOVIDO" in texto


def test_nao_expoe_segredos(ambiente):
    _corpo_resposta(ambiente, "/api/v1/ativos-acompanhados", "post", "alice")
    corpo = ambiente["cliente"].get(
        "/api/v1/ativos-acompanhados", headers=_h(ambiente, "alice")
    ).get_data(as_text=True)
    for segredo in _segredos(ambiente):
        assert segredo not in corpo
    for proibido in ("usuario_id", "senha_hash", "token_hash", "chave_hash"):
        assert proibido not in corpo
    texto_auditoria = _texto_auditoria(ambiente)
    for segredo in _segredos(ambiente):
        assert segredo not in texto_auditoria
