"""Testes da Etapa 8 — integração consolidada entre usuários e Telegram.

Cobre: identidade Telegram via banco respeitando papel e ``ativo``, fallback
legado (sem vínculo e banco indisponível), vínculo/desvínculo administrativo com
autorização central, anti-escalonamento, auditoria sem segredos e a ponte de
identidade sem criação automática de sessões/usuários. Usa SQLite em memória.
"""
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modules import seguranca
from pipeline_dados.banco_dados import AuditoriaAcesso, Base, Sessao
from services import autorizacao, telegram, usuarios


@pytest.fixture(autouse=True)
def limpar_ids_legado():
    chaves = ("ADMIN_CHAT_IDS", "SUPERADMIN_CHAT_IDS", "TELEGRAM_CHAT_ID")
    salvos = {k: os.environ.get(k) for k in chaves}
    for k in chaves:
        os.environ.pop(k, None)
    yield
    for k, valor in salvos.items():
        if valor is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = valor


@pytest.fixture()
def sessao():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


@pytest.fixture()
def vincula_db(monkeypatch, sessao):
    """Faz a resolução DB-first (seguranca) consultar o banco em memória."""
    monkeypatch.setattr("atualizador_documentos.SessionDB", lambda: sessao)


def _auditoria(sessao):
    return sessao.query(AuditoriaAcesso).order_by(AuditoriaAcesso.id).all()


def _criar(sessao, **kwargs):
    dados = {"nome": "Ana", "email": "ana@x.com", "senha": "senha1234"}
    dados.update(kwargs)
    return usuarios.criar_usuario(session=sessao, **dados)


def _superadmin(sessao):
    return _criar(sessao, nome="Root", email="root@x.com", papel=usuarios.SUPERADMIN)


def _vincular(sessao, tg_id, **kwargs):
    admin = _superadmin(sessao)
    alvo = _criar(sessao, **kwargs)
    telegram.vincular_telegram_usuario(admin, alvo, tg_id, session=sessao)
    return admin, alvo


# ==========================================
# IDENTIDADE TELEGRAM (DB-FIRST)
# ==========================================


@pytest.mark.parametrize(
    "papel,esperado",
    [
        (usuarios.USER, seguranca.ROLE_USER),
        (usuarios.ADMIN, seguranca.ROLE_ADMIN),
        (usuarios.SUPERADMIN, seguranca.ROLE_SUPERADMIN),
        (usuarios.VISITOR, seguranca.ROLE_VISITOR),
    ],
)
def test_telegram_vinculado_respeita_papel_do_banco(vincula_db, sessao, papel, esperado):
    _vincular(sessao, 9001, nome="Alvo", email=f"{papel.lower()}@x.com", papel=papel)
    assert seguranca.papel_do_usuario(9001) == esperado
    assert seguranca.usuario_tem_papel(9001, esperado) is True


def test_telegram_nao_vinculado_usa_fallback_legado(vincula_db, sessao):
    os.environ["SUPERADMIN_CHAT_IDS"] = "5555"
    assert seguranca.papel_do_usuario(5555) == seguranca.ROLE_SUPERADMIN
    os.environ["ADMIN_CHAT_IDS"] = "5566"
    assert seguranca.papel_do_usuario(5566) == seguranca.ROLE_ADMIN
    assert seguranca.papel_do_usuario(9999) == seguranca.ROLE_USER


def test_banco_indisponivel_usa_fallback_legado(monkeypatch):
    def _falha(*args, **kwargs):
        raise RuntimeError("banco indisponível (simulado)")

    monkeypatch.setattr("atualizador_documentos.SessionDB", _falha)
    os.environ["SUPERADMIN_CHAT_IDS"] = "6666"
    assert seguranca.papel_do_usuario(6666) == seguranca.ROLE_SUPERADMIN
    assert seguranca.eh_superadmin(6666) is True


def test_usuario_desativado_bloqueado_mesmo_no_env_legado(vincula_db, sessao):
    admin, user = _vincular(sessao, 7001)
    usuarios.desativar_usuario(user, session=sessao)
    os.environ["SUPERADMIN_CHAT_IDS"] = "7001"
    os.environ["TELEGRAM_CHAT_ID"] = "7001"
    assert seguranca.papel_do_usuario(7001) == seguranca.ROLE_VISITOR
    assert seguranca.eh_admin(7001) is False
    assert seguranca.eh_superadmin(7001) is False
    assert seguranca.usuario_tem_papel(7001, seguranca.ROLE_USER) is False


def test_usuario_desativado_sem_autorizacao_central(vincula_db, sessao):
    admin, user = _vincular(sessao, 7002)
    usuarios.desativar_usuario(user, session=sessao)
    usuario = telegram.usuario_do_telegram(7002, session=sessao)
    assert usuario is not None
    assert autorizacao.papel_de(usuario) is None
    assert autorizacao.tem_permissao(usuario, "dados.consultar") is False


def test_usuario_desativado_nao_autentica_sessao(vincula_db, sessao):
    admin, user = _vincular(sessao, 7003)
    usuarios.desativar_usuario(user, session=sessao)
    assert telegram.usuario_do_telegram(7003, session=sessao).ativo is False


# ==========================================
# VÍNCULO / DESVÍNCULO ADMINISTRATIVO
# ==========================================


def test_vinculo_duplicado_rejeitado(sessao):
    admin = _superadmin(sessao)
    u1 = _criar(sessao, nome="Bia", email="bia@x.com")
    u2 = _criar(sessao, nome="Cid", email="cid@x.com")
    telegram.vincular_telegram_usuario(admin, u1, 8001, session=sessao)
    with pytest.raises(ValueError):
        telegram.vincular_telegram_usuario(admin, u2, 8001, session=sessao)
    assert usuarios.buscar_usuario_por_telegram(8001, session=sessao).id == u1.id


def test_desvinculacao_funciona(sessao):
    admin = _superadmin(sessao)
    user = _criar(sessao)
    telegram.vincular_telegram_usuario(admin, user, 8002, session=sessao)
    assert telegram.desvincular_telegram_usuario(admin, user, session=sessao) is True
    assert usuarios.buscar_usuario_por_telegram(8002, session=sessao) is None


def test_superadmin_consegue_vincular(sessao):
    admin = _superadmin(sessao)
    user = _criar(sessao)
    assert telegram.vincular_telegram_usuario(admin, user, 8004, session=sessao) is True
    assert usuarios.buscar_usuario_por_telegram(8004, session=sessao).id == user.id


def test_superadmin_consegue_desvincular(sessao):
    admin = _superadmin(sessao)
    user = _criar(sessao)
    telegram.vincular_telegram_usuario(admin, user, 8005, session=sessao)
    assert telegram.desvincular_telegram_usuario(admin, user, session=sessao) is True
    assert usuarios.buscar_usuario_por_telegram(8005, session=sessao) is None


def test_telegram_chat_id_persistido_quando_informado(sessao):
    admin = _superadmin(sessao)
    user = _criar(sessao)
    telegram.vincular_telegram_usuario(
        admin, user, 8030, telegram_chat_id=8031, session=sessao
    )
    assert user.telegram_user_id == 8030
    assert user.telegram_chat_id == 8031


# ==========================================
# AUTORIZAÇÃO E ANTI-ESCALONAMENTO
# ==========================================


def test_user_nao_pode_vincular_outro_usuario(sessao):
    user = _criar(sessao, email="user@x.com")
    alvo = _criar(sessao, nome="Bia", email="bia@x.com")
    with pytest.raises(autorizacao.PermissaoNegadaError):
        telegram.vincular_telegram_usuario(user, alvo, 8003, session=sessao)
    assert usuarios.buscar_usuario_por_telegram(8003, session=sessao) is None


def test_user_nao_pode_desvincular(sessao):
    admin = _superadmin(sessao)
    user = _criar(sessao, email="user@x.com")
    alvo = _criar(sessao, nome="Bia", email="bia@x.com")
    telegram.vincular_telegram_usuario(admin, alvo, 8020, session=sessao)
    with pytest.raises(autorizacao.PermissaoNegadaError):
        telegram.desvincular_telegram_usuario(user, alvo, session=sessao)
    assert usuarios.buscar_usuario_por_telegram(8020, session=sessao) is not None


def test_admin_nao_promove_para_superadmin(sessao):
    admin = _criar(sessao, nome="Admin", email="admin@x.com", papel=usuarios.ADMIN)
    alvo = _criar(sessao, nome="Bia", email="bia@x.com")
    assert autorizacao.pode_alterar_papel(admin, alvo, usuarios.SUPERADMIN) is False
    assert autorizacao.pode_alterar_papel(admin, alvo, usuarios.ADMIN) is False
    assert autorizacao.pode_alterar_papel(admin, alvo, usuarios.USER) is True


def test_admin_nao_altera_superadmin(sessao):
    admin = _criar(sessao, nome="Admin", email="admin@x.com", papel=usuarios.ADMIN)
    root = _superadmin(sessao)
    with pytest.raises(autorizacao.PermissaoNegadaError):
        telegram.vincular_telegram_usuario(admin, root, 8010, session=sessao)
    assert usuarios.buscar_usuario_por_telegram(8010, session=sessao) is None


def test_usuario_nao_altera_proprio_papel(sessao):
    user = _criar(sessao)
    for papel in (usuarios.ADMIN, usuarios.SUPERADMIN):
        assert autorizacao.pode_alterar_papel(user, user, papel) is False
    assert autorizacao.tem_permissao(user, "usuarios.alterar_papel") is False
    with pytest.raises(autorizacao.PermissaoNegadaError):
        autorizacao.requer_permissao(user, "usuarios.alterar_papel")


# ==========================================
# AUDITORIA
# ==========================================


def test_auditoria_do_vinculo(sessao):
    _vincular(sessao, 8006)
    acoes = [e.acao for e in _auditoria(sessao)]
    assert "TELEGRAM_VINCULADO" in acoes


def test_auditoria_da_desvinculacao(sessao):
    admin, user = _vincular(sessao, 8007)
    telegram.desvincular_telegram_usuario(admin, user, session=sessao)
    acoes = [e.acao for e in _auditoria(sessao)]
    assert "TELEGRAM_VINCULADO" in acoes
    assert "TELEGRAM_DESVINCULADO" in acoes


def test_auditoria_tentativa_de_vinculo_sem_permissao(sessao):
    user = _criar(sessao, email="user@x.com")
    alvo = _criar(sessao, nome="Bia", email="bia@x.com")
    with pytest.raises(autorizacao.PermissaoNegadaError):
        telegram.vincular_telegram_usuario(user, alvo, 8009, session=sessao)
    acoes = [e.acao for e in _auditoria(sessao)]
    assert "TELEGRAM_VINCULO_NEGADO" in acoes


def test_auditoria_tentativa_de_escalonamento(sessao):
    admin = _criar(sessao, nome="Admin", email="admin@x.com", papel=usuarios.ADMIN)
    root = _superadmin(sessao)
    with pytest.raises(autorizacao.PermissaoNegadaError):
        telegram.vincular_telegram_usuario(admin, root, 8011, session=sessao)
    acoes = [e.acao for e in _auditoria(sessao)]
    assert "ESCALONAMENTO_NEGADO" in acoes


def test_nenhum_segredo_nos_registros(sessao):
    admin = _superadmin(sessao)
    user = _criar(sessao, senha="senhaSecreta123")
    telegram.vincular_telegram_usuario(admin, user, 8008, session=sessao)
    telegram.desvincular_telegram_usuario(admin, user, session=sessao)
    for e in _auditoria(sessao):
        texto = f"{e.acao} {e.alvo or ''} {e.detalhe or ''}"
        assert "senhaSecreta123" not in texto
        assert "senha_hash" not in texto
        assert e.detalhe is None or "senha" not in e.detalhe.lower()


# ==========================================
# COMPORTAMENTO LEGADO E INTEGRAÇÃO MÍNIMA
# ==========================================


def test_comportamento_legado_continua_funcionando(monkeypatch):
    def _falha(*args, **kwargs):
        raise RuntimeError("banco indisponível (simulado)")

    monkeypatch.setattr("atualizador_documentos.SessionDB", _falha)
    os.environ["SUPERADMIN_CHAT_IDS"] = "1"
    os.environ["ADMIN_CHAT_IDS"] = "2,3"
    os.environ["TELEGRAM_CHAT_ID"] = "4"
    assert seguranca.eh_superadmin(1) is True
    assert seguranca.eh_admin(2) is True
    assert seguranca.eh_admin(3) is True
    assert seguranca.eh_superadmin(4) is True
    assert seguranca.papel_do_usuario(5) == seguranca.ROLE_USER


def test_usuario_do_telegram_ponte_de_identidade(sessao):
    admin, user = _vincular(sessao, 8012)
    assert telegram.usuario_do_telegram(8012, session=sessao).id == user.id
    assert telegram.usuario_do_telegram(999999, session=sessao) is None
    assert telegram.usuario_do_telegram(None, session=sessao) is None


def test_vinculo_nao_cria_sessao_automaticamente(sessao):
    _vincular(sessao, 8013)
    assert sessao.query(Sessao).count() == 0


def test_vinculo_nao_cria_usuario_automaticamente(vincula_db, sessao):
    assert seguranca.papel_do_usuario(5555) == seguranca.ROLE_USER
    assert telegram.usuario_do_telegram(5555, session=sessao) is None
    assert usuarios.buscar_usuario_por_telegram(5555, session=sessao) is None
