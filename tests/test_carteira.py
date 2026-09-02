"""Testes da Fase 6, Etapa 4 — Carteira/posições por usuário.

Cobrem a camada central ``services/carteira.py`` e os endpoints
``/api/v1/carteira``: criação, consulta, listagem, atualização e remoção de
posições com isolamento total entre usuários (``services/escopo.py``), proteção
contra IDOR/BOLA, validações de quantidade/preço, comportamento de
usuários desativados/None e VISITOR, SUPERADMIN administrativo, ausência de
segredos e auditoria.
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
    AuditoriaAcesso,
    Base,
    PosicaoCarteira,
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


def _criar_posicao(ambiente, usuario, ativo="PETR4", quantidade=10, preco=25.5, **extra):
    corpo = {
        "ativo_id": ambiente["ativos"][ativo],
        "quantidade": quantidade,
        "preco_medio": preco,
    }
    corpo.update(extra)
    return ambiente["cliente"].post(
        "/api/v1/carteira", json=corpo, headers=_h(ambiente, usuario)
    )


# ==========================================
# CRIAÇÃO, CONSULTA E LISTAGEM
# ==========================================


def test_criar_posicao(ambiente):
    resposta = _criar_posicao(ambiente, "alice")
    assert resposta.status_code == 200
    dados = resposta.get_json()["data"]
    assert dados["ativo_id"] == ambiente["ativos"]["PETR4"]
    assert dados["ticker"] == "PETR4"
    assert dados["tipo"] == "ACAO"
    assert dados["quantidade"] == 10
    assert dados["preco_medio"] == pytest.approx(25.5)
    assert dados["valor_investido"] == pytest.approx(255.0)
    assert dados["id"] > 0


def test_criar_posicao_duplicidade(ambiente):
    _criar_posicao(ambiente, "alice")
    resposta = _criar_posicao(ambiente, "alice")
    assert resposta.status_code == 400


def test_criar_posicao_dois_ativos(ambiente):
    _criar_posicao(ambiente, "alice")
    resposta = _criar_posicao(ambiente, "alice", ativo="GARE11", quantidade=100, preco=9.9)
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["ticker"] == "GARE11"


def test_criar_posicao_ativo_inexistente(ambiente):
    resposta = ambiente["cliente"].post(
        "/api/v1/carteira",
        json={"ativo_id": 999999, "quantidade": 1, "preco_medio": 1.0},
        headers=_h(ambiente, "alice"),
    )
    assert resposta.status_code == 400


def test_listar_posicoes(ambiente):
    _criar_posicao(ambiente, "alice")
    _criar_posicao(ambiente, "alice", ativo="GARE11", quantidade=100, preco=9.9)
    resposta = ambiente["cliente"].get("/api/v1/carteira", headers=_h(ambiente, "alice"))
    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados["meta"]["total"] == 2
    tickers = {item["ticker"] for item in dados["data"]}
    assert tickers == {"PETR4", "GARE11"}


def test_listar_posicoes_vazio(ambiente):
    resposta = ambiente["cliente"].get("/api/v1/carteira", headers=_h(ambiente, "bob"))
    assert resposta.status_code == 200
    assert resposta.get_json()["meta"]["total"] == 0


def test_consultar_posicao(ambiente):
    criada = _criar_posicao(ambiente, "alice").get_json()["data"]
    resposta = ambiente["cliente"].get(
        f"/api/v1/carteira/{criada['id']}", headers=_h(ambiente, "alice")
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["quantidade"] == 10


# ==========================================
# ATUALIZAÇÃO E REMOÇÃO
# ==========================================


def test_atualizar_posicao_quantidade(ambiente):
    criada = _criar_posicao(ambiente, "alice").get_json()["data"]
    resposta = ambiente["cliente"].patch(
        f"/api/v1/carteira/{criada['id']}",
        json={"quantidade": 40},
        headers=_h(ambiente, "alice"),
    )
    assert resposta.status_code == 200
    dados = resposta.get_json()["data"]
    assert dados["quantidade"] == 40
    assert dados["preco_medio"] == pytest.approx(25.5)


def test_atualizar_posicao_preco(ambiente):
    criada = _criar_posicao(ambiente, "alice").get_json()["data"]
    resposta = ambiente["cliente"].patch(
        f"/api/v1/carteira/{criada['id']}",
        json={"preco_medio": 30.0},
        headers=_h(ambiente, "alice"),
    )
    assert resposta.status_code == 200
    dados = resposta.get_json()["data"]
    assert dados["quantidade"] == 10
    assert dados["preco_medio"] == pytest.approx(30.0)
    assert dados["valor_investido"] == pytest.approx(300.0)


def test_atualizar_posicao_sem_campos(ambiente):
    criada = _criar_posicao(ambiente, "alice").get_json()["data"]
    resposta = ambiente["cliente"].patch(
        f"/api/v1/carteira/{criada['id']}", json={}, headers=_h(ambiente, "alice")
    )
    assert resposta.status_code == 400


def test_atualizar_posicao_inexistente(ambiente):
    resposta = ambiente["cliente"].patch(
        "/api/v1/carteira/999999",
        json={"quantidade": 5},
        headers=_h(ambiente, "alice"),
    )
    assert resposta.status_code == 404


def test_remover_posicao(ambiente):
    criada = _criar_posicao(ambiente, "alice").get_json()["data"]
    resposta = ambiente["cliente"].delete(
        f"/api/v1/carteira/{criada['id']}", headers=_h(ambiente, "alice")
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["removido"] is True
    consulta = ambiente["cliente"].get(
        f"/api/v1/carteira/{criada['id']}", headers=_h(ambiente, "alice")
    )
    assert consulta.status_code == 404


# ==========================================
# ISOLAMENTO E IDOR/BOLA
# ==========================================


def test_dois_usuarios_carteiras_isoladas(ambiente):
    _criar_posicao(ambiente, "alice")
    _criar_posicao(ambiente, "bob", ativo="GARE11", quantidade=100, preco=9.9)
    alice = ambiente["cliente"].get(
        "/api/v1/carteira", headers=_h(ambiente, "alice")
    ).get_json()["data"]
    bob = ambiente["cliente"].get(
        "/api/v1/carteira", headers=_h(ambiente, "bob")
    ).get_json()["data"]
    assert [item["ticker"] for item in alice] == ["PETR4"]
    assert [item["ticker"] for item in bob] == ["GARE11"]


def test_usuario_nao_acessa_posicao_de_outro(ambiente):
    criada = _criar_posicao(ambiente, "alice").get_json()["data"]
    for verbo, verbo_nome in (("get", "get"), ("patch", "patch"), ("delete", "delete")):
        resposta = getattr(ambiente["cliente"], verbo)(
            f"/api/v1/carteira/{criada['id']}",
            json={"quantidade": 1} if verbo == "patch" else None,
            headers=_h(ambiente, "bob"),
        )
        assert resposta.status_code == 404, verbo_nome


def test_idor_posicao_de_outro_usuario(ambiente):
    criada = _criar_posicao(ambiente, "alice").get_json()["data"]
    resposta = ambiente["cliente"].get(
        f"/api/v1/carteira/{criada['id']}", headers=_h(ambiente, "bob")
    )
    assert resposta.status_code == 404
    assert resposta.get_json()["meta"]["error"] == "Recurso não encontrado."


def test_manipular_usuario_id_ignorado(ambiente):
    corpo = {
        "ativo_id": ambiente["ativos"]["PETR4"],
        "quantidade": 10,
        "preco_medio": 25.5,
        "usuario_id": _id(ambiente, "bob"),
    }
    resposta = ambiente["cliente"].post(
        "/api/v1/carteira", json=corpo, headers=_h(ambiente, "alice")
    )
    assert resposta.status_code == 200
    registros = _registros(ambiente["Session"], PosicaoCarteira)
    assert len(registros) == 1
    assert registros[0].usuario_id == _id(ambiente, "alice")


# ==========================================
# VALIDAÇÕES DE QUANTIDADE E PREÇO
# ==========================================


def test_quantidade_invalida_rejeitada(ambiente):
    for quantidade in (0, -1, -100):
        resposta = _criar_posicao(ambiente, "alice", quantidade=quantidade)
        assert resposta.status_code == 400, quantidade


def test_quantidade_ausente_rejeitada(ambiente):
    corpo = {"ativo_id": ambiente["ativos"]["PETR4"], "preco_medio": 25.5}
    resposta = ambiente["cliente"].post(
        "/api/v1/carteira", json=corpo, headers=_h(ambiente, "alice")
    )
    assert resposta.status_code == 400


def test_preco_negativo_rejeitado(ambiente):
    resposta = _criar_posicao(ambiente, "alice", preco=-1.0)
    assert resposta.status_code == 400


def test_preco_ausente_rejeitado(ambiente):
    corpo = {"ativo_id": ambiente["ativos"]["PETR4"], "quantidade": 10}
    resposta = ambiente["cliente"].post(
        "/api/v1/carteira", json=corpo, headers=_h(ambiente, "alice")
    )
    assert resposta.status_code == 400


def test_preco_zero_aceito(ambiente):
    resposta = _criar_posicao(ambiente, "alice", preco=0)
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["preco_medio"] == 0


def test_atualizacao_valida_quantidade_e_preco(ambiente):
    criada = _criar_posicao(ambiente, "alice").get_json()["data"]
    for campo, valor in (("quantidade", 0), ("quantidade", -5), ("preco_medio", -1.0)):
        resposta = ambiente["cliente"].patch(
            f"/api/v1/carteira/{criada['id']}",
            json={campo: valor},
            headers=_h(ambiente, "alice"),
        )
        assert resposta.status_code == 400, (campo, valor)


# ==========================================
# PAPÉIS
# ==========================================


def test_visitor_nao_acessa(ambiente):
    resposta = ambiente["cliente"].get("/api/v1/carteira", headers=_h(ambiente, "visitor"))
    assert resposta.status_code == 403


def test_desativado_nao_acessa(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/carteira", headers=_h(ambiente, "desativado")
    )
    assert resposta.status_code == 401


def test_superadmin_administra_carteira_de_outro(ambiente):
    criada = _criar_posicao(ambiente, "alice").get_json()["data"]
    resposta = ambiente["cliente"].get(
        f"/api/v1/carteira/{criada['id']}", headers=_h(ambiente, "superadmin")
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["ticker"] == "PETR4"


def test_superadmin_pode_criar_para_si(ambiente):
    resposta = _criar_posicao(ambiente, "superadmin")
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["quantidade"] == 10


# ==========================================
# AUDITORIA E SEGREDOS
# ==========================================


def test_auditoria_registra_operacoes(ambiente):
    criada = _criar_posicao(ambiente, "alice").get_json()["data"]
    ambiente["cliente"].patch(
        f"/api/v1/carteira/{criada['id']}",
        json={"quantidade": 20},
        headers=_h(ambiente, "alice"),
    )
    ambiente["cliente"].delete(
        f"/api/v1/carteira/{criada['id']}", headers=_h(ambiente, "alice")
    )
    texto = _texto_auditoria(ambiente)
    assert "POSICAO_CRIADA" in texto
    assert "POSICAO_ALTERADA" in texto
    assert "POSICAO_REMOVIDA" in texto


def test_nao_expoe_segredos(ambiente):
    _criar_posicao(ambiente, "alice")
    corpo = ambiente["cliente"].get(
        "/api/v1/carteira", headers=_h(ambiente, "alice")
    ).get_data(as_text=True)
    for segredo in _segredos(ambiente):
        assert segredo not in corpo
    for proibido in ("usuario_id", "senha_hash", "token_hash", "chave_hash"):
        assert proibido not in corpo
    texto_auditoria = _texto_auditoria(ambiente)
    for segredo in _segredos(ambiente):
        assert segredo not in texto_auditoria
