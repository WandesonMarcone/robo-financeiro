"""Testes do seed idempotente do SUPERADMIN (Fase 5, Etapa 5).

Cobre a criação do primeiro SUPERADMIN (referência via PRIMEIRO_ADMIN_TELEGRAM_ID
ou fallback para TELEGRAM_CHAT_ID legado), a idempotência (sem duplicatas),
a não-sobrescrição de usuários existentes, a promoção segura de papel, a trilha
de auditoria (sem segredos) e a garantia de que uma falha de banco nunca
derruba o fluxo principal. Usa SQLite em memória, seguindo o padrão do projeto.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import config
from pipeline_dados.banco_dados import AuditoriaAcesso, Base, Usuario
from services import seed, usuarios


@pytest.fixture()
def sessao():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


@pytest.fixture(autouse=True)
def sem_admin_configurado(monkeypatch):
    monkeypatch.setattr(config, "PRIMEIRO_ADMIN_TELEGRAM_ID", "")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "")


def _consultar(sessao):
    return sessao.query(AuditoriaAcesso).order_by(AuditoriaAcesso.id).all()


# ==========================================
# CRIAÇÃO DO PRIMEIRO SUPERADMIN
# ==========================================


def test_seed_cria_superadmin_quando_necessario(sessao, monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "777")
    resultado = seed.garantir_superadmin_inicial(session=sessao)
    assert resultado["status"] == "criado"
    assert sessao.query(Usuario).count() == 1
    usuario = sessao.query(Usuario).one()
    assert usuario.papel == usuarios.SUPERADMIN
    assert usuario.telegram_user_id == 777
    assert usuario.telegram_chat_id == 777
    assert usuario.ativo is True
    assert usuario.senha_hash is None


def test_seed_usa_telegram_chat_id_como_fallback(sessao, monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "999")
    resultado = seed.garantir_superadmin_inicial(session=sessao)
    assert resultado["status"] == "criado"
    assert resultado["telegram_id"] == 999
    assert sessao.query(Usuario).one().telegram_user_id == 999


def test_seed_prioriza_primeiro_admin_telegram_id(sessao, monkeypatch):
    monkeypatch.setattr(config, "PRIMEIRO_ADMIN_TELEGRAM_ID", "555")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "777")
    resultado = seed.garantir_superadmin_inicial(session=sessao)
    assert resultado["status"] == "criado"
    assert resultado["telegram_id"] == 555
    assert sessao.query(Usuario).one().telegram_user_id == 555


def test_seed_sem_alvo_nao_faz_nada(sessao):
    resultado = seed.garantir_superadmin_inicial(session=sessao)
    assert resultado["status"] == "sem_alvo"
    assert resultado["telegram_id"] is None
    assert sessao.query(Usuario).count() == 0
    assert _consultar(sessao) == []


def test_telegram_id_invalido_e_tratado_como_sem_alvo(sessao, monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "nao-numerico")
    resultado = seed.garantir_superadmin_inicial(session=sessao)
    assert resultado["status"] == "sem_alvo"
    assert sessao.query(Usuario).count() == 0


# ==========================================
# IDEMPOTÊNCIA (SEM DUPLICATAS)
# ==========================================


def test_seed_repetido_nao_duplica_usuario(sessao, monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "777")
    primeiro = seed.garantir_superadmin_inicial(session=sessao)
    segundo = seed.garantir_superadmin_inicial(session=sessao)
    terceiro = seed.garantir_superadmin_inicial(session=sessao)
    assert primeiro["status"] == "criado"
    assert segundo["status"] == "existente"
    assert terceiro["status"] == "existente"
    assert sessao.query(Usuario).count() == 1
    assert sessao.query(Usuario).one().telegram_user_id == 777


# ==========================================
# USUÁRIO EXISTENTE NÃO É SOBRESCRITO
# ==========================================


def test_seed_nao_sobrescreve_superadmin_existente(sessao, monkeypatch):
    usuarios.criar_usuario(
        nome="Dono Atual",
        email="dono@x.com",
        senha="senhaAtual1",
        papel=usuarios.SUPERADMIN,
        telegram_user_id=777,
        telegram_chat_id=777,
        session=sessao,
    )
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "777")
    resultado = seed.garantir_superadmin_inicial(session=sessao)
    assert resultado["status"] == "existente"
    assert sessao.query(Usuario).count() == 1
    usuario = sessao.query(Usuario).one()
    assert usuario.nome == "Dono Atual"
    assert usuario.email == "dono@x.com"
    assert usuario.papel == usuarios.SUPERADMIN


def test_seed_promove_usuario_existente_sem_sobrescrever_dados(sessao, monkeypatch):
    usuarios.criar_usuario(
        nome="Operador",
        email="op@x.com",
        senha="senhaOperador1",
        papel=usuarios.USER,
        telegram_user_id=777,
        telegram_chat_id=777,
        session=sessao,
    )
    senha_antes = sessao.query(Usuario).one().senha_hash
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "777")
    resultado = seed.garantir_superadmin_inicial(session=sessao)
    assert resultado["status"] == "promovido"
    assert sessao.query(Usuario).count() == 1
    usuario = sessao.query(Usuario).one()
    assert usuario.papel == usuarios.SUPERADMIN
    assert usuario.nome == "Operador"
    assert usuario.email == "op@x.com"
    assert usuario.senha_hash == senha_antes
    assert usuario.ativo is True
    assert usuarios.verificar_senha(usuario, "senhaOperador1") is True


# ==========================================
# AUDITORIA
# ==========================================


def test_seed_audita_criacao(sessao, monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "777")
    resultado = seed.garantir_superadmin_inicial(session=sessao)
    acoes = [e.acao for e in _consultar(sessao)]
    assert resultado["status"] == "criado"
    assert "USUARIO_CRIADO" in acoes
    assert "SEED_SUPERADMIN" in acoes
    evento_seed = [e for e in _consultar(sessao) if e.acao == "SEED_SUPERADMIN"][0]
    assert evento_seed.usuario_id == resultado["usuario_id"]
    assert evento_seed.alvo == "telegram:777"
    assert evento_seed.sucesso is True


def test_seed_audita_promocao(sessao, monkeypatch):
    usuarios.criar_usuario(
        nome="Operador",
        email="op@x.com",
        papel=usuarios.USER,
        telegram_user_id=777,
        session=sessao,
    )
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "777")
    resultado = seed.garantir_superadmin_inicial(session=sessao)
    acoes = [e.acao for e in _consultar(sessao)]
    assert resultado["status"] == "promovido"
    assert "PAPEL_ALTERADO" in acoes
    assert "SEED_SUPERADMIN" in acoes


def test_seed_nao_registra_segredos_na_auditoria(sessao, monkeypatch):
    usuarios.criar_usuario(
        nome="Operador",
        email="op@x.com",
        senha="senhaSupersecreta1",
        papel=usuarios.USER,
        telegram_user_id=777,
        session=sessao,
    )
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "777")
    seed.garantir_superadmin_inicial(session=sessao)
    for e in _consultar(sessao):
        texto = f"{e.acao} {e.alvo or ''} {e.detalhe or ''}"
        assert "senha" not in texto.lower()
        assert "token" not in texto.lower()
        assert "senhaSupersecreta1" not in texto


# ==========================================
# FALHA DE BANCO NÃO DERRUBA O FLUXO
# ==========================================


def test_falha_de_banco_nao_derruba_e_retorna_erro(monkeypatch):
    def _falha(*args, **kwargs):
        raise RuntimeError("banco indisponível (simulado)")

    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "777")
    monkeypatch.setattr(seed, "SessionDB", _falha)
    monkeypatch.setattr(usuarios, "SessionDB", _falha)
    resultado = seed.garantir_superadmin_inicial()
    assert resultado["status"] == "erro"
    assert resultado["usuario_id"] is None


def test_falha_inesperada_nao_derruba(monkeypatch):
    def _falha(*args, **kwargs):
        raise RuntimeError("banco indisponível (simulado)")

    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "777")
    monkeypatch.setattr(seed, "SessionDB", _falha)
    monkeypatch.setattr(usuarios, "SessionDB", _falha)
    assert seed.garantir_superadmin_inicial()["status"] == "erro"


# ==========================================
# COMPATIBILIDADE SQLITE EM MEMÓRIA
# ==========================================


def test_compatibilidade_sqlite_em_memoria(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessao_local = sessionmaker(bind=engine)()
    try:
        monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "123456")
        resultado = seed.garantir_superadmin_inicial(session=sessao_local)
        assert resultado["status"] == "criado"
        assert sessao_local.query(Usuario).count() == 1
        assert sessao_local.query(AuditoriaAcesso).count() == 2
    finally:
        sessao_local.close()
