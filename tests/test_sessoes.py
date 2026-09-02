"""Testes do serviço de sessões e tokens (Fase 5, Etapa 7).

Cobre a criação de sessão, validação, expiração, logout, revogação (individual e
em massa), TTL, auditoria e as garantias de segurança: somente o hash SHA-256 é
persistido, o token bruto nunca fica no banco/auditoria e a ausência de
sessão/banco não derruba o processo. Usa SQLite em memória, seguindo o padrão
dos testes do projeto.
"""
import hashlib
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import config
from pipeline_dados.banco_dados import AuditoriaAcesso, Base, Sessao
from services import autorizacao, sessoes, usuarios


@pytest.fixture()
def sessao():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _auditoria(sessao):
    return sessao.query(AuditoriaAcesso).order_by(AuditoriaAcesso.id).all()


def _criar_usuario(sessao, **kwargs):
    dados = {"nome": "Ana", "email": "ana@x.com", "senha": "senha1234"}
    dados.update(kwargs)
    return usuarios.criar_usuario(session=sessao, **dados)


def _criar_sessao(sessao, **kwargs):
    usuario_kwargs = kwargs.pop("usuario_kwargs", None)
    origem = kwargs.pop("origem", sessoes.ORIGEM_PADRAO)
    usuario = kwargs.pop("usuario", None) or _criar_usuario(sessao, **(usuario_kwargs or {}))
    token = sessoes.criar_sessao(usuario, origem=origem, session=sessao, **kwargs)
    return usuario, token


# ==========================================
# CRIAÇÃO DE SESSÃO
# ==========================================


def test_criar_sessao(sessao):
    user = _criar_usuario(sessao)
    token = sessoes.criar_sessao(user, session=sessao)
    assert isinstance(token, str) and token
    assert sessao.query(Sessao).count() == 1


def test_token_retornado_funciona(sessao):
    user, token = _criar_sessao(sessao)
    autenticado = sessoes.validar_sessao(token, session=sessao)
    assert autenticado is not None
    assert autenticado.id == user.id


def test_somente_hash_persistido(sessao):
    user, token = _criar_sessao(sessao)
    reg = sessao.query(Sessao).first()
    esperado = hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert reg.token_hash == esperado
    assert len(reg.token_hash) == 64
    assert reg.token_hash != token
    assert token not in reg.token_hash


def test_token_bruto_nao_fica_no_banco(sessao):
    user, token = _criar_sessao(sessao)
    sessoes.validar_sessao(token, session=sessao)
    sessoes.revogar_sessao(token, session=sessao)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

    for reg in sessao.query(Sessao).all():
        for coluna in ("token_hash", "origem"):
            assert token not in str(getattr(reg, coluna) or "")
    for e in _auditoria(sessao):
        texto = f"{e.acao} {e.alvo or ''} {e.detalhe or ''}"
        assert token not in texto
        assert token_hash not in texto


# ==========================================
# VALIDAÇÃO DE SESSÃO
# ==========================================


def test_token_invalido_rejeitado(sessao):
    assert sessoes.validar_sessao("token-invalido-qualquer", session=sessao) is None
    assert sessoes.validar_sessao("outro-token-inexistente", session=sessao) is None


def test_sessao_valida_retorna_usuario_correto(sessao):
    user, token = _criar_sessao(sessao, usuario_kwargs={"nome": "Bia", "email": "bia@x.com"})
    autenticado = sessoes.validar_sessao(token, session=sessao)
    assert autenticado is not None
    assert autenticado.id == user.id
    assert autenticado.email == "bia@x.com"


def test_sessao_expirada_rejeitada(sessao):
    user, token = _criar_sessao(sessao)
    reg = sessao.query(Sessao).first()
    reg.expira_em = datetime.now() - timedelta(seconds=1)
    sessao.commit()

    assert sessoes.validar_sessao(token, session=sessao) is None
    sessao.refresh(reg)
    assert reg.revogada is True
    acoes = [e.acao for e in _auditoria(sessao)]
    assert "SESSAO_EXPIRADA" in acoes


def test_sessao_revogada_rejeitada(sessao):
    user, token = _criar_sessao(sessao)
    assert sessoes.revogar_sessao(token, session=sessao) is True
    assert sessoes.validar_sessao(token, session=sessao) is None


def test_usuario_desativado_nao_pode_utilizar_sessao(sessao):
    user, token = _criar_sessao(sessao)
    assert sessoes.validar_sessao(token, session=sessao) is not None
    usuarios.desativar_usuario(user, session=sessao)
    assert sessoes.validar_sessao(token, session=sessao) is None


# ==========================================
# LOGOUT E REVOGAÇÃO
# ==========================================


def test_logout_invalida_sessao(sessao):
    user, token = _criar_sessao(sessao)
    assert sessoes.revogar_sessao(token, session=sessao) is True
    assert sessoes.validar_sessao(token, session=sessao) is None
    assert sessoes.revogar_sessao(token, session=sessao) is True
    reg = sessao.query(Sessao).first()
    assert reg.revogada is True


def test_revogacao_de_todas_as_sessoes_funciona(sessao):
    user = _criar_usuario(sessao)
    tokens = [sessoes.criar_sessao(user, session=sessao) for _ in range(3)]
    assert sessoes.revogar_sessoes_usuario(user, session=sessao) == 3
    for token in tokens:
        assert sessoes.validar_sessao(token, session=sessao) is None
    assert sessao.query(Sessao).filter(Sessao.revogada.is_(False)).count() == 0


def test_criacao_de_multiplas_sessoes_independentes(sessao):
    user = _criar_usuario(sessao)
    t1 = sessoes.criar_sessao(user, session=sessao)
    t2 = sessoes.criar_sessao(user, session=sessao)
    assert t1 != t2
    assert sessao.query(Sessao).count() == 2
    a1 = sessoes.validar_sessao(t1, session=sessao)
    a2 = sessoes.validar_sessao(t2, session=sessao)
    assert a1 is not None and a1.id == user.id
    assert a2 is not None and a2.id == user.id


def test_uma_sessao_revogada_nao_invalida_outra(sessao):
    user = _criar_usuario(sessao)
    t1 = sessoes.criar_sessao(user, session=sessao)
    t2 = sessoes.criar_sessao(user, session=sessao)
    assert sessoes.revogar_sessao(t1, session=sessao) is True
    assert sessoes.validar_sessao(t1, session=sessao) is None
    assert sessoes.validar_sessao(t2, session=sessao) is not None


def test_revogacao_administrativa_por_id(sessao):
    dono = _criar_usuario(sessao)
    admin = _criar_usuario(sessao, nome="Admin", email="admin@x.com", papel=usuarios.ADMIN)
    token = sessoes.criar_sessao(dono, session=sessao)
    reg = sessao.query(Sessao).first()

    assert sessoes.revogar_sessao_por_id(reg.id, admin, session=sessao) is True
    assert sessoes.validar_sessao(token, session=sessao) is None
    assert sessoes.revogar_sessao_por_id(reg.id, admin, session=sessao) is True
    assert sessoes.revogar_sessao_por_id(999999, admin, session=sessao) is False


def test_revogacao_administrativa_exige_permissao(sessao):
    dono = _criar_usuario(sessao)
    user_comum = _criar_usuario(sessao, nome="Bia", email="bia@x.com")
    token = sessoes.criar_sessao(dono, session=sessao)
    reg = sessao.query(Sessao).first()

    with pytest.raises(autorizacao.PermissaoNegadaError):
        sessoes.revogar_sessao_por_id(reg.id, user_comum, session=sessao)
    assert sessoes.validar_sessao(token, session=sessao) is not None

    with pytest.raises(autorizacao.PermissaoNegadaError):
        sessoes.revogar_sessoes_usuario(dono, autor=user_comum, session=sessao)
    assert sessoes.validar_sessao(token, session=sessao) is not None


# ==========================================
# TTL E CONFIGURAÇÃO
# ==========================================


def test_ttl_utiliza_sessao_ttl_horas(sessao, monkeypatch):
    monkeypatch.setattr(config, "SESSAO_TTL_HORAS", 1)
    user = _criar_usuario(sessao)
    token = sessoes.criar_sessao(user, session=sessao)
    reg = sessao.query(Sessao).first()
    assert reg.expira_em - reg.criada_em == timedelta(hours=1)

    monkeypatch.setattr(config, "SESSAO_TTL_HORAS", 72)
    token2 = sessoes.criar_sessao(user, session=sessao)
    reg2 = sessao.query(Sessao).order_by(Sessao.id.desc()).first()
    assert reg2.expira_em - reg2.criada_em == timedelta(hours=72)
    assert token != token2


def test_origem_da_sessao(sessao):
    user = _criar_usuario(sessao)
    sessoes.criar_sessao(user, origem="api", session=sessao)
    assert sessao.query(Sessao).first().origem == "api"
    with pytest.raises(ValueError):
        sessoes.criar_sessao(user, origem="inexistente", session=sessao)


# ==========================================
# AUDITORIA
# ==========================================


def test_auditoria_registra_criacao_revogacao(sessao):
    user, token = _criar_sessao(sessao)
    sessoes.revogar_sessao(token, session=sessao)
    acoes = [e.acao for e in _auditoria(sessao)]
    assert "SESSAO_CRIADA" in acoes
    assert "SESSAO_REVOGADA" in acoes


def test_auditoria_nao_contem_token_ou_segredo(sessao):
    user, token = _criar_sessao(sessao)
    sessoes.validar_sessao(token, session=sessao)
    sessoes.revogar_sessao(token, session=sessao)
    sessoes.revogar_sessoes_usuario(user, session=sessao)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

    for e in _auditoria(sessao):
        texto = f"{e.acao} {e.alvo or ''} {e.detalhe or ''}"
        assert token not in texto
        assert token_hash not in texto
        assert e.detalhe is None or "token" not in e.detalhe.lower()


# ==========================================
# COMPATIBILIDADE E RESILIÊNCIA
# ==========================================


def test_compatibilidade_sqlite_em_memoria():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessao_local = sessionmaker(bind=engine)()
    try:
        user = usuarios.criar_usuario(
            "Ana", email="ana@x.com", senha="senha1234", session=sessao_local
        )
        token = sessoes.criar_sessao(user, session=sessao_local)
        autenticado = sessoes.validar_sessao(token, session=sessao_local)
        assert autenticado is not None
        assert autenticado.id == user.id
        assert sessao_local.query(Sessao).count() == 1
    finally:
        sessao_local.close()


def test_ausencia_de_sessao_banco_nao_derruba_processo(sessao):
    # Token nulo/vazio/não-textual: nunca abre banco e nunca derruba o processo.
    assert sessoes.validar_sessao(None) is None
    assert sessoes.validar_sessao("") is None
    assert sessoes.validar_sessao(12345) is None
    assert sessoes.revogar_sessao(None) is False
    assert sessoes.revogar_sessao("") is False

    # Sessão inexistente: rejeição segura, sem derrubar o processo.
    assert sessoes.validar_sessao("token-que-nao-existe", session=sessao) is None
    assert sessoes.revogar_sessao("token-que-nao-existe", session=sessao) is False

    # Banco indisponível: trata como não autenticado (fail-closed), sem propagar.
    admin = _criar_usuario(sessao, nome="Admin", email="admin@x.com", papel=usuarios.ADMIN)
    engine = create_engine("sqlite:////caminho/inexistente/xyz/banco.db")
    sessao_quebrada = sessionmaker(bind=engine)()
    try:
        assert sessoes.validar_sessao("qualquer-token", session=sessao_quebrada) is None
        assert sessoes.revogar_sessao("qualquer-token", session=sessao_quebrada) is False
        assert sessoes.revogar_sessao_por_id(1, admin, session=sessao_quebrada) is False
        assert sessoes.revogar_sessoes_usuario(
            _criar_usuario(sessao, nome="Bia", email="bia@x.com"), session=sessao_quebrada
        ) == 0
    finally:
        sessao_quebrada.close()
