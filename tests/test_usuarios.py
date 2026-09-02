"""Testes do serviço de usuários e autenticação (Fase 5, Etapa 3).

Cobre a criação, consulta, listagem e autenticação de usuários, gestão de
senha/papel/ativação, vínculo com o Telegram e a trilha de auditoria — com
garantia de que senhas e segredos nunca são persistidos. Usa SQLite em memória,
seguindo o padrão dos testes do projeto.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline_dados.banco_dados import AuditoriaAcesso, Base, Usuario
from services import usuarios


@pytest.fixture()
def sessao():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _consultar(sessao):
    return sessao.query(AuditoriaAcesso).order_by(AuditoriaAcesso.id).all()


def _criar(sessao, **kwargs):
    dados = {"nome": "Ana", "email": "ana@x.com", "senha": "senha1234"}
    dados.update(kwargs)
    return usuarios.criar_usuario(session=sessao, **dados)


# ==========================================
# CRIAÇÃO DE USUÁRIO
# ==========================================


def test_criar_usuario(sessao):
    user = _criar(sessao)
    assert user.id is not None
    assert user.nome == "Ana"
    assert user.email == "ana@x.com"
    assert user.papel == usuarios.PAPEL_PADRAO
    assert user.ativo is True
    assert sessao.query(Usuario).count() == 1


def test_criar_usuario_sem_senha(sessao):
    user = _criar(sessao, senha=None)
    assert user.senha_hash is None
    assert usuarios.autenticar("ana@x.com", "senha1234", session=sessao) is None


def test_email_duplicado_rejeitado(sessao):
    _criar(sessao)
    with pytest.raises(ValueError):
        _criar(sessao, nome="Bia", email="ana@x.com")


# ==========================================
# SENHA ARMAZENADA SOMENTE COMO HASH
# ==========================================


def test_senha_armazenada_somente_como_hash(sessao):
    user = _criar(sessao, senha="minhaSenha9")
    assert user.senha_hash is not None
    assert user.senha_hash != "minhaSenha9"
    assert "minhaSenha9" not in user.senha_hash
    assert usuarios.verificar_senha(user, "minhaSenha9") is True
    assert usuarios.verificar_senha(user, "outraSenha") is False


def test_senha_minima_8_caracteres(sessao):
    with pytest.raises(ValueError):
        _criar(sessao, senha="curta")
    user = _criar(sessao, senha="12345678")
    with pytest.raises(ValueError):
        usuarios.alterar_senha(user, "1234567", session=sessao)


# ==========================================
# AUTENTICAÇÃO
# ==========================================


def test_autenticacao_valida(sessao):
    user = _criar(sessao)
    resultado = usuarios.autenticar("ana@x.com", "senha1234", session=sessao)
    assert resultado is not None
    assert resultado.id == user.id
    assert resultado.ultimo_login is not None


def test_senha_invalida(sessao):
    _criar(sessao)
    assert usuarios.autenticar("ana@x.com", "senhaerrada", session=sessao) is None


def test_usuario_inexistente(sessao):
    assert usuarios.autenticar("nao@existe.com", "senha1234", session=sessao) is None


def test_usuario_desativado_nao_autentica(sessao):
    user = _criar(sessao)
    usuarios.desativar_usuario(user, session=sessao)
    assert usuarios.autenticar("ana@x.com", "senha1234", session=sessao) is None


def test_usuario_sem_senha_nao_autentica(sessao):
    _criar(sessao, senha=None)
    assert usuarios.autenticar("ana@x.com", "senha1234", session=sessao) is None


def test_prevencao_enumercao_usuarios(sessao):
    _criar(sessao)
    resultado_inexistente = usuarios.autenticar("nao@existe.com", "senha1234", session=sessao)
    resultado_senha_errada = usuarios.autenticar("ana@x.com", "senhaerrada", session=sessao)
    assert resultado_inexistente is None
    assert resultado_senha_errada is None
    logins = [e for e in _consultar(sessao) if e.acao == "LOGIN"]
    assert len(logins) == 2
    assert all(e.sucesso is False for e in logins)


# ==========================================
# ALTERAÇÃO DE SENHA
# ==========================================


def test_alterar_senha(sessao):
    user = _criar(sessao)
    assert usuarios.alterar_senha(user, "novaSenha456", session=sessao) is True
    assert usuarios.verificar_senha(user, "novaSenha456") is True
    assert usuarios.verificar_senha(user, "senha1234") is False
    assert usuarios.autenticar("ana@x.com", "novaSenha456", session=sessao) is not None
    assert usuarios.autenticar("ana@x.com", "senha1234", session=sessao) is None


# ==========================================
# ATIVAÇÃO / DESATIVAÇÃO
# ==========================================


def test_ativar_usuario(sessao):
    user = _criar(sessao)
    usuarios.desativar_usuario(user, session=sessao)
    assert usuarios.buscar_usuario_por_email("ana@x.com", session=sessao).ativo is False
    usuarios.ativar_usuario(user, session=sessao)
    assert usuarios.buscar_usuario_por_email("ana@x.com", session=sessao).ativo is True
    assert usuarios.autenticar("ana@x.com", "senha1234", session=sessao) is not None


def test_desativar_usuario(sessao):
    user = _criar(sessao)
    usuarios.desativar_usuario(user, session=sessao)
    assert usuarios.buscar_usuario_por_email("ana@x.com", session=sessao).ativo is False


# ==========================================
# PAPEL
# ==========================================


def test_papeis_validos_definidos():
    assert set(usuarios.PAPEIS_VALIDOS) == {"SUPERADMIN", "ADMIN", "USER", "VISITOR"}
    assert usuarios.PAPEL_PADRAO == usuarios.USER


def test_alterar_papel(sessao):
    user = _criar(sessao)
    assert user.papel == usuarios.USER
    usuarios.alterar_papel(user, usuarios.ADMIN, session=sessao)
    assert usuarios.buscar_usuario_por_email("ana@x.com", session=sessao).papel == usuarios.ADMIN


def test_papel_invalido_rejeitado(sessao):
    user = _criar(sessao)
    with pytest.raises(ValueError):
        usuarios.alterar_papel(user, "ROOT", session=sessao)
    with pytest.raises(ValueError):
        _criar(sessao, nome="Bia", email="bia@x.com", papel="INEXISTENTE")


# ==========================================
# TELEGRAM
# ==========================================


def test_vincular_telegram(sessao):
    user = _criar(sessao)
    usuarios.vincular_telegram(user, telegram_user_id=123456, telegram_chat_id=999, session=sessao)
    user = usuarios.buscar_usuario_por_email("ana@x.com", session=sessao)
    assert user.telegram_user_id == 123456
    assert user.telegram_chat_id == 999


def test_desvincular_telegram(sessao):
    user = _criar(sessao)
    usuarios.vincular_telegram(user, 123456, 999, session=sessao)
    usuarios.desvincular_telegram(user, session=sessao)
    user = usuarios.buscar_usuario_por_email("ana@x.com", session=sessao)
    assert user.telegram_user_id is None
    assert user.telegram_chat_id is None


def test_buscar_usuario_por_telegram(sessao):
    user = _criar(sessao)
    usuarios.vincular_telegram(user, 123456, session=sessao)
    encontrado = usuarios.buscar_usuario_por_telegram(123456, session=sessao)
    assert encontrado is not None
    assert encontrado.id == user.id
    assert usuarios.buscar_usuario_por_telegram(999999, session=sessao) is None


def test_telegram_duplicado_rejeitado(sessao):
    user_a = _criar(sessao)
    user_b = _criar(sessao, nome="Bia", email="bia@x.com")
    usuarios.vincular_telegram(user_a, 111, session=sessao)
    with pytest.raises(ValueError):
        usuarios.vincular_telegram(user_b, 111, session=sessao)


def test_usuario_sem_telegram(sessao):
    user = _criar(sessao)
    assert user.telegram_user_id is None
    assert user.telegram_chat_id is None
    assert usuarios.buscar_usuario_por_telegram(None, session=sessao) is None
    assert usuarios.buscar_usuario_por_telegram(12345, session=sessao) is None
    assert usuarios.desvincular_telegram(user, session=sessao) is True


# ==========================================
# CONSULTA E LISTAGEM
# ==========================================


def test_buscar_usuario_por_id_e_email(sessao):
    user = _criar(sessao)
    assert usuarios.buscar_usuario(user.id, session=sessao).id == user.id
    assert usuarios.buscar_usuario("ana@x.com", session=sessao).id == user.id
    assert usuarios.buscar_usuario(99999, session=sessao) is None


def test_listar_usuarios(sessao):
    _criar(sessao)
    _criar(sessao, nome="Bia", email="bia@x.com")
    _criar(sessao, nome="Cid", email="cid@x.com", ativo=False)
    assert len(usuarios.listar_usuarios(session=sessao)) == 3
    ativos = usuarios.listar_usuarios(apenas_ativos=True, session=sessao)
    assert len(ativos) == 2
    assert all(u.ativo for u in ativos)


# ==========================================
# AUDITORIA
# ==========================================


def test_auditoria_dos_eventos(sessao):
    user = _criar(sessao)
    usuarios.autenticar("ana@x.com", "senha1234", session=sessao)
    usuarios.autenticar("ana@x.com", "senhaerrada", session=sessao)
    usuarios.alterar_senha(user, "novaSenha456", session=sessao)
    usuarios.desativar_usuario(user, session=sessao)
    usuarios.ativar_usuario(user, session=sessao)
    usuarios.alterar_papel(user, usuarios.ADMIN, session=sessao)
    usuarios.vincular_telegram(user, 111, 222, session=sessao)
    usuarios.desvincular_telegram(user, session=sessao)

    acoes = [e.acao for e in _consultar(sessao)]
    for esperada in (
        "USUARIO_CRIADO",
        "LOGIN",
        "SENHA_ALTERADA",
        "USUARIO_DESATIVADO",
        "USUARIO_ATIVADO",
        "PAPEL_ALTERADO",
        "TELEGRAM_VINCULADO",
        "TELEGRAM_DESVINCULADO",
    ):
        assert esperada in acoes


def test_auditoria_registra_sucesso_e_falha_de_login(sessao):
    _criar(sessao)
    usuarios.autenticar("ana@x.com", "senha1234", session=sessao)
    usuarios.autenticar("ana@x.com", "senhaerrada", session=sessao)
    logins = [e for e in _consultar(sessao) if e.acao == "LOGIN"]
    assert len(logins) == 2
    assert [e.sucesso for e in logins] == [True, False]


def test_ausencia_de_segredos_na_auditoria(sessao):
    user = _criar(sessao, senha="primeiraSenha")
    usuarios.autenticar("ana@x.com", "primeiraSenha", session=sessao)
    usuarios.alterar_senha(user, "segundaSenha", session=sessao)
    usuarios.autenticar("ana@x.com", "segundaSenha", session=sessao)

    registros = _consultar(sessao)
    assert len(registros) >= 4
    for e in registros:
        texto = f"{e.acao} {e.alvo or ''} {e.detalhe or ''}"
        assert "primeiraSenha" not in texto
        assert "segundaSenha" not in texto
        assert "senha_hash" not in texto
        assert e.detalhe is None or "senha" not in e.detalhe.lower()


# ==========================================
# COMPATIBILIDADE SQLITE EM MEMÓRIA
# ==========================================


def test_compatibilidade_sqlite_em_memoria():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessao_local = sessionmaker(bind=engine)()
    try:
        user = usuarios.criar_usuario(
            "Ana", email="ana@x.com", senha="senha1234", session=sessao_local
        )
        assert user.id is not None
        assert usuarios.autenticar("ana@x.com", "senha1234", session=sessao_local) is not None
        assert sessao_local.query(Usuario).count() == 1
        assert sessao_local.query(AuditoriaAcesso).count() == 2
    finally:
        sessao_local.close()
