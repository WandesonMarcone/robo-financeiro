"""Testes do serviço de auditoria de acesso (Fase 5, Etapa 2).

Cobre o registro de eventos na tabela ``auditoria_acesso``: sucesso, ausência
de usuário, fracasso, desativação via ``AUDITORIA_ATIVA``, sanitização mínima
do ``detalhe`` (segredos nunca persistidos) e falha da auditoria sem derrubar
o fluxo principal. Usa SQLite em memória, seguindo o padrão dos testes do
projeto.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import config
from pipeline_dados.banco_dados import AuditoriaAcesso, Base
from services import auditoria
from services.auditoria import _sanitizar_detalhe, registrar_evento


@pytest.fixture()
def sessao():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _consultar(sessao):
    return sessao.query(AuditoriaAcesso).order_by(AuditoriaAcesso.id).all()


# ==========================================
# REGISTRO DE EVENTOS
# ==========================================

def test_registro_de_evento_bem_sucedido(sessao):
    evento = registrar_evento(
        acao="LOGIN",
        alvo="carteira",
        detalhe="autenticado via Telegram",
        usuario_id=42,
        ip="127.0.0.1",
        sucesso=True,
        session=sessao,
    )
    assert evento is not None
    registros = _consultar(sessao)
    assert len(registros) == 1
    assert registros[0].acao == "LOGIN"
    assert registros[0].alvo == "carteira"
    assert registros[0].detalhe == "autenticado via Telegram"
    assert registros[0].usuario_id == 42
    assert registros[0].ip == "127.0.0.1"
    assert registros[0].sucesso is True


def test_registro_de_evento_sem_usuario(sessao):
    evento = registrar_evento(acao="TENTATIVA_ANONIMA", session=sessao)
    assert evento is not None
    registros = _consultar(sessao)
    assert len(registros) == 1
    assert registros[0].usuario_id is None
    assert registros[0].acao == "TENTATIVA_ANONIMA"


def test_registro_de_evento_com_sucesso_falso(sessao):
    registrar_evento(acao="LOGIN", sucesso=False, detalhe="senha incorreta", session=sessao)
    registros = _consultar(sessao)
    assert len(registros) == 1
    assert registros[0].sucesso is False
    assert registros[0].acao == "LOGIN"


# ==========================================
# AUDITORIA DESATIVADA
# ==========================================

def test_auditoria_desativada_nao_grava(monkeypatch, sessao):
    monkeypatch.setattr(config, "AUDITORIA_ATIVA", False)
    resultado = registrar_evento(acao="LOGIN", session=sessao)
    assert resultado is None
    assert _consultar(sessao) == []


def test_auditoria_reativada_volta_a_gravar(monkeypatch, sessao):
    monkeypatch.setattr(config, "AUDITORIA_ATIVA", True)
    registrar_evento(acao="LOGIN", session=sessao)
    assert len(_consultar(sessao)) == 1


# ==========================================
# SANITIZAÇÃO MÍNIMA DO DETALHE
# ==========================================

def test_detalhe_preservado_quando_nao_contem_segredo(sessao):
    detalhe = "usuario autenticado, perfil ADMIN, origem Brasil"
    registrar_evento(acao="LOGIN", detalhe=detalhe, session=sessao)
    assert _consultar(sessao)[0].detalhe == detalhe


def test_senha_nao_persistida(sessao):
    registrar_evento(acao="LOGIN", detalhe="senha=segredo123 tentativa", session=sessao)
    detalhe_salvo = _consultar(sessao)[0].detalhe
    assert "senha=[OCULTO]" in detalhe_salvo
    assert "segredo123" not in detalhe_salvo


def test_token_nao_persistido(sessao):
    registrar_evento(
        acao="API_ACESSO",
        detalhe="token: eyJhbGciOiJIUzI1NiJ9.corpo.assinatura valido",
        session=sessao,
    )
    detalhe_salvo = _consultar(sessao)[0].detalhe
    assert "token: [OCULTO]" in detalhe_salvo
    assert "eyJhbGciOiJIUzI1NiJ9" not in detalhe_salvo


def test_token_bearer_nao_persistido(sessao):
    registrar_evento(acao="API_ACESSO", detalhe="Bearer abc123xyz valido", session=sessao)
    detalhe_salvo = _consultar(sessao)[0].detalhe
    assert "Bearer [OCULTO]" in detalhe_salvo
    assert "abc123xyz" not in detalhe_salvo


def test_api_key_nao_persistida(sessao):
    registrar_evento(
        acao="API_ACESSO",
        detalhe="api_key=sk-proj-1234567890abcdef integracao",
        session=sessao,
    )
    detalhe_salvo = _consultar(sessao)[0].detalhe
    assert "api_key=[OCULTO]" in detalhe_salvo
    assert "sk-proj-1234567890abcdef" not in detalhe_salvo


def test_sanitizacao_direta_cobre_padroes():
    assert _sanitizar_detalhe(None) is None
    assert _sanitizar_detalhe("") == ""
    assert _sanitizar_detalhe("texto normal sem segredo") == "texto normal sem segredo"
    assert _sanitizar_detalhe("password: xyz") == "password: [OCULTO]"
    assert _sanitizar_detalhe("SENHA = 123") == "SENHA = [OCULTO]"
    assert _sanitizar_detalhe("apikey=zzz") == "apikey=[OCULTO]"
    assert _sanitizar_detalhe("secret=v1") == "secret=[OCULTO]"
    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    assert _sanitizar_detalhe(jwt) == "[OCULTO]"


def test_auditoria_nunca_expoe_colunas_de_segredo(sessao):
    registrar_evento(
        acao="LOGIN",
        detalhe="senha=abc token=xyz api_key=chave",
        session=sessao,
    )
    registro = _consultar(sessao)[0]
    colunas = {
        "senha": None,
        "token": None,
        "api_key": None,
        "chave": None,
    }
    assert not any(getattr(registro, nome, None) is not None for nome in colunas)


# ==========================================
# FALHA NÃO DERRUBA O FLUXO PRINCIPAL
# ==========================================

def test_falha_ao_abrir_sessao_nao_derruba(monkeypatch):
    def _falha():
        raise RuntimeError("banco indisponível")

    monkeypatch.setattr(auditoria, "SessionDB", _falha)
    assert registrar_evento(acao="LOGIN") is None


class _SessaoFalhaCommit:
    def __init__(self):
        self.add_chamado = False

    def add(self, evento):
        self.add_chamado = True

    def commit(self):
        raise RuntimeError("falha no commit")

    def rollback(self):
        pass

    def close(self):
        pass


def test_falha_no_commit_nao_derruba(monkeypatch):
    sessao_falha = _SessaoFalhaCommit()
    monkeypatch.setattr(auditoria, "SessionDB", lambda: sessao_falha)
    assert registrar_evento(acao="LOGIN") is None
    assert sessao_falha.add_chamado is True


# ==========================================
# COMPATIBILIDADE SQLITE EM MEMÓRIA
# ==========================================

def test_compatibilidade_sqlite_em_memoria():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessao_local = sessionmaker(bind=engine)()
    try:
        evento = registrar_evento(acao="PING", usuario_id=7, session=sessao_local)
        assert evento is not None
        assert evento.usuario_id == 7
        assert sessao_local.query(AuditoriaAcesso).count() == 1
    finally:
        sessao_local.close()
