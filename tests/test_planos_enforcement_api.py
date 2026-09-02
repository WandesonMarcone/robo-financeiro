"""Testes da Fase 6, Etapa 9 — enforcement de planos/limites pela API.

Verificam que a API respeita os limites de plano ao criar recursos:
- ``POST /api/v1/ativos-acompanhados`` — limite de ativos acompanhados;
- ``POST /api/v1/carteira`` — limite de posições na carteira;
- ``PATCH /api/v1/carteira/<id>`` — não bloqueia operações que não aumentam
  o consumo;
- operações de leitura/consulta/remoção não são bloqueadas no limite;
- SUPERADMIN permanece ilimitado; usuário desativado continua sem acesso;
- respostas de erro são seguras e consistentes (400), sem segredos.
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
    TipoAtivo,
)
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
        "ativos": seed.ativos,
    }


class _Semear:
    """Popula o banco de testes: usuários com planos distintos + ativos em massa."""

    QUANTIDADE_ATIVOS = 120

    def __init__(self, sessao):
        self.sessao = sessao
        self.usuarios = {}
        self.chaves = {}
        self.ativos = {}

    def _criar(self, nome, papel, ativo=True, plano=None):
        usuario = usuarios.criar_usuario(
            nome=nome,
            email=f"{nome}@x.com",
            senha="senha1234",
            papel=papel,
            ativo=ativo,
            session=self.sessao,
        )
        if plano is not None:
            usuario.plano = plano
        return usuario

    def rodar(self):
        s = self.sessao
        self.usuarios["superadmin"] = self._criar("superadmin", usuarios.SUPERADMIN)
        self.usuarios["free"] = self._criar("free", usuarios.USER, plano=planos.PLANO_FREE)
        self.usuarios["premium"] = self._criar(
            "premium", usuarios.USER, plano=planos.PLANO_PREMIUM
        )
        self.usuarios["pro"] = self._criar("pro", usuarios.USER, plano=planos.PLANO_PRO)
        self.usuarios["desativado"] = self._criar("desativado", usuarios.USER, ativo=False)

        registros = [
            Ativo(ticker=f"TEST{i:04d}", cnpj=f"{i:014d}/0001-00", tipo=TipoAtivo.ACAO)
            for i in range(self.QUANTIDADE_ATIVOS)
        ]
        s.add_all(registros)
        s.commit()
        self.ativos = {registro.ticker: registro.id for registro in registros}

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


def _ids_ativos(ambiente):
    return sorted(ambiente["ativos"].values())


def _adicionar_acompanhamento(ambiente, usuario, ativo_id):
    return ambiente["cliente"].post(
        "/api/v1/ativos-acompanhados",
        json={"ativo_id": ativo_id},
        headers=_h(ambiente, usuario),
    )


def _adicionar_posicao(ambiente, usuario, ativo_id):
    return ambiente["cliente"].post(
        "/api/v1/carteira",
        json={"ativo_id": ativo_id, "quantidade": 10, "preco_medio": 25.0},
        headers=_h(ambiente, usuario),
    )


def _texto_auditoria(ambiente):
    sessao = ambiente["Session"]()
    try:
        eventos = sessao.query(AuditoriaAcesso).order_by(AuditoriaAcesso.id).all()
        return "\n".join(
            f"{evento.acao} {evento.alvo or ''} {evento.detalhe or ''}"
            for evento in eventos
        )
    finally:
        sessao.close()


# ==========================================
# ATIVOS ACOMPANHADOS — LIMITE POR PLANO
# ==========================================


def test_free_atinge_limite_na_api(ambiente):
    limite = planos.LIMITES_DO_PLANO[planos.PLANO_FREE]["limite.ativos_acompanhados"]
    for ativo_id in _ids_ativos(ambiente)[:limite]:
        assert _adicionar_acompanhamento(ambiente, "free", ativo_id).status_code == 200
    resposta = _adicionar_acompanhamento(ambiente, "free", _ids_ativos(ambiente)[limite])
    assert resposta.status_code == 400
    dados = resposta.get_json()
    assert dados["status"] == "error"
    assert "limite" in dados["meta"]["error"].lower()


def test_premium_tem_limite_maior_na_api(ambiente):
    limite = planos.LIMITES_DO_PLANO[planos.PLANO_PREMIUM]["limite.ativos_acompanhados"]
    for ativo_id in _ids_ativos(ambiente)[:limite]:
        assert _adicionar_acompanhamento(ambiente, "premium", ativo_id).status_code == 200
    resposta = _adicionar_acompanhamento(ambiente, "premium", _ids_ativos(ambiente)[limite])
    assert resposta.status_code == 400


def test_pro_limite_maior_na_api(ambiente):
    limite = planos.LIMITES_DO_PLANO[planos.PLANO_PRO]["limite.ativos_acompanhados"]
    for ativo_id in _ids_ativos(ambiente)[:limite]:
        assert _adicionar_acompanhamento(ambiente, "pro", ativo_id).status_code == 200
    resposta = _adicionar_acompanhamento(ambiente, "pro", _ids_ativos(ambiente)[limite])
    assert resposta.status_code == 400


def test_superadmin_ilimitado_na_api(ambiente):
    ids = _ids_ativos(ambiente)
    limite_free = planos.LIMITES_DO_PLANO[planos.PLANO_FREE]["limite.ativos_acompanhados"]
    for ativo_id in ids[: limite_free + 5]:
        assert _adicionar_acompanhamento(ambiente, "superadmin", ativo_id).status_code == 200


def test_isolamento_limite_entre_usuarios_na_api(ambiente):
    limite = planos.LIMITES_DO_PLANO[planos.PLANO_FREE]["limite.ativos_acompanhados"]
    for ativo_id in _ids_ativos(ambiente)[:limite]:
        assert _adicionar_acompanhamento(ambiente, "free", ativo_id).status_code == 200
    assert _adicionar_acompanhamento(ambiente, "free", _ids_ativos(ambiente)[limite]).status_code == 400
    outro = _adicionar_acompanhamento(ambiente, "premium", _ids_ativos(ambiente)[limite])
    assert outro.status_code == 200


def test_remocao_libera_vaga_na_api(ambiente):
    ids = _ids_ativos(ambiente)
    limite = planos.LIMITES_DO_PLANO[planos.PLANO_FREE]["limite.ativos_acompanhados"]
    for ativo_id in ids[:limite]:
        _adicionar_acompanhamento(ambiente, "free", ativo_id)
    assert _adicionar_acompanhamento(ambiente, "free", ids[limite]).status_code == 400
    listagem = ambiente["cliente"].get(
        "/api/v1/ativos-acompanhados", headers=_h(ambiente, "free")
    ).get_json()["data"]
    alvo = listagem[0]["id"]
    resposta_remocao = ambiente["cliente"].delete(
        f"/api/v1/ativos-acompanhados/{alvo}", headers=_h(ambiente, "free")
    )
    assert resposta_remocao.status_code == 200
    assert _adicionar_acompanhamento(ambiente, "free", ids[limite]).status_code == 200


def test_consulta_listagem_nao_bloqueadas_na_api(ambiente):
    ids = _ids_ativos(ambiente)
    limite = planos.LIMITES_DO_PLANO[planos.PLANO_FREE]["limite.ativos_acompanhados"]
    for ativo_id in ids[:limite]:
        _adicionar_acompanhamento(ambiente, "free", ativo_id)
    resposta = ambiente["cliente"].get(
        "/api/v1/ativos-acompanhados", headers=_h(ambiente, "free")
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["meta"]["total"] == limite


def test_usuario_desativado_sem_acesso_na_api(ambiente):
    resposta = _adicionar_acompanhamento(ambiente, "desativado", _ids_ativos(ambiente)[0])
    assert resposta.status_code == 401


# ==========================================
# CARTEIRA — LIMITE POR PLANO
# ==========================================


def test_free_limite_posicoes_na_api(ambiente):
    limite = planos.LIMITES_DO_PLANO[planos.PLANO_FREE]["limite.posicoes_carteira"]
    for ativo_id in _ids_ativos(ambiente)[:limite]:
        assert _adicionar_posicao(ambiente, "free", ativo_id).status_code == 200
    resposta = _adicionar_posicao(ambiente, "free", _ids_ativos(ambiente)[limite])
    assert resposta.status_code == 400
    dados = resposta.get_json()
    assert dados["status"] == "error"
    assert "limite" in dados["meta"]["error"].lower()


def test_premium_limite_posicoes_na_api(ambiente):
    limite = planos.LIMITES_DO_PLANO[planos.PLANO_PREMIUM]["limite.posicoes_carteira"]
    for ativo_id in _ids_ativos(ambiente)[:limite]:
        assert _adicionar_posicao(ambiente, "premium", ativo_id).status_code == 200
    assert _adicionar_posicao(ambiente, "premium", _ids_ativos(ambiente)[limite]).status_code == 400


def test_superadmin_ilimitado_carteira_na_api(ambiente):
    ids = _ids_ativos(ambiente)
    limite_free = planos.LIMITES_DO_PLANO[planos.PLANO_FREE]["limite.posicoes_carteira"]
    for ativo_id in ids[: limite_free + 5]:
        assert _adicionar_posicao(ambiente, "superadmin", ativo_id).status_code == 200


def test_patch_posicao_no_limite_nao_bloqueado_na_api(ambiente):
    ids = _ids_ativos(ambiente)
    limite = planos.LIMITES_DO_PLANO[planos.PLANO_FREE]["limite.posicoes_carteira"]
    for ativo_id in ids[:limite]:
        _adicionar_posicao(ambiente, "free", ativo_id)
    listagem = ambiente["cliente"].get(
        "/api/v1/carteira", headers=_h(ambiente, "free")
    ).get_json()["data"]
    alvo = listagem[0]["id"]
    resposta = ambiente["cliente"].patch(
        f"/api/v1/carteira/{alvo}",
        json={"quantidade": 99},
        headers=_h(ambiente, "free"),
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["quantidade"] == 99


def test_isolamento_carteira_entre_usuarios_na_api(ambiente):
    ids = _ids_ativos(ambiente)
    limite = planos.LIMITES_DO_PLANO[planos.PLANO_FREE]["limite.posicoes_carteira"]
    for ativo_id in ids[:limite]:
        _adicionar_posicao(ambiente, "free", ativo_id)
    assert _adicionar_posicao(ambiente, "free", ids[limite]).status_code == 400
    assert _adicionar_posicao(ambiente, "premium", ids[limite]).status_code == 200


def test_usuario_desativado_carteira_na_api(ambiente):
    resposta = _adicionar_posicao(ambiente, "desativado", _ids_ativos(ambiente)[0])
    assert resposta.status_code == 401


# ==========================================
# SEGURANÇA: erro consistente e sem segredos
# ==========================================


def test_erro_limite_consistente_e_sem_segredos(ambiente):
    limite = planos.LIMITES_DO_PLANO[planos.PLANO_FREE]["limite.ativos_acompanhados"]
    for ativo_id in _ids_ativos(ambiente)[:limite]:
        _adicionar_acompanhamento(ambiente, "free", ativo_id)
    resposta = _adicionar_acompanhamento(ambiente, "free", _ids_ativos(ambiente)[limite])
    corpo = resposta.get_json()
    assert corpo["status"] == "error"
    assert "senha1234" not in str(corpo)
    assert ambiente["chaves"]["free"] not in str(corpo)
    assert "Limite" in corpo["meta"]["error"]
