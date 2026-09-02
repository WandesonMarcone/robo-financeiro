"""Testes do serviço de API Keys (Fase 5, Etapa 9).

Cobre o ciclo de vida das chaves: criação (chave retornada uma única vez,
somente hash persistido), validação, expiração, revogação, isolamento entre
usuários, autorização central (próprio escopo vs. administrativa), auditoria sem
vazamento de segredo e compatibilidade com SQLite em memória.
"""
import hashlib
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline_dados.banco_dados import AuditoriaAcesso, Base, ChaveApi
from services import autorizacao, chaves_api, usuarios


@pytest.fixture()
def sessao():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _auditoria(sessao):
    return sessao.query(AuditoriaAcesso).order_by(AuditoriaAcesso.id).all()


def _criar(sessao, **kwargs):
    dados = {"nome": "Ana", "email": "ana@x.com", "senha": "senha1234"}
    dados.update(kwargs)
    return usuarios.criar_usuario(session=sessao, **dados)


def _superadmin(sessao):
    return _criar(sessao, nome="Root", email="root@x.com", papel=usuarios.SUPERADMIN)


def _admin(sessao):
    return _criar(sessao, nome="Admin", email="admin@x.com", papel=usuarios.ADMIN)


def _criar_chave(sessao, **kwargs):
    usuario_kwargs = kwargs.pop("usuario_kwargs", None)
    usuario = kwargs.pop("usuario", None) or _criar(sessao, **(usuario_kwargs or {}))
    rotulo = kwargs.pop("rotulo", "chave-teste")
    expira_em = kwargs.pop("expira_em", None)
    chave = chaves_api.criar_chave_api(
        usuario, rotulo, expira_em=expira_em, session=sessao, **kwargs
    )
    return usuario, chave


def _hash(chave):
    return hashlib.sha256(chave.encode("utf-8")).hexdigest()


# ==========================================
# CRIAÇÃO
# ==========================================


def test_criar_chave_api(sessao):
    user = _criar(sessao)
    chave = chaves_api.criar_chave_api(user, "integracao", session=sessao)
    assert isinstance(chave, str) and chave
    assert sessao.query(ChaveApi).count() == 1


def test_chave_retornada_somente_na_criacao(sessao):
    user = _criar(sessao)
    chave = chaves_api.criar_chave_api(user, "prod", session=sessao)
    reg = sessao.query(ChaveApi).first()
    assert reg.chave_hash != chave
    assert reg.ativa is True
    assert reg.rotulo == "prod"


def test_banco_contem_somente_hash(sessao):
    user = _criar(sessao)
    chave = chaves_api.criar_chave_api(user, "prod", session=sessao)
    reg = sessao.query(ChaveApi).first()
    assert reg.chave_hash == _hash(chave)
    assert len(reg.chave_hash) == 64
    assert chave not in reg.chave_hash


def test_hash_nao_permite_recuperar_chave_original(sessao):
    user = _criar(sessao)
    chave = chaves_api.criar_chave_api(user, "prod", session=sessao)
    reg = sessao.query(ChaveApi).first()
    assert reg.chave_hash != chave
    assert chaves_api.validar_chave_api(reg.chave_hash, session=sessao) is None


def test_rotulo_obrigatorio(sessao):
    user = _criar(sessao)
    with pytest.raises(ValueError):
        chaves_api.criar_chave_api(user, "", session=sessao)
    with pytest.raises(ValueError):
        chaves_api.criar_chave_api(user, None, session=sessao)


def test_expira_em_passado_rejeitado(sessao):
    user = _criar(sessao)
    with pytest.raises(ValueError):
        chaves_api.criar_chave_api(
            user, "prod", expira_em=datetime.now() - timedelta(hours=1), session=sessao
        )


# ==========================================
# VALIDAÇÃO
# ==========================================


def test_validacao_chave_valida(sessao):
    user, chave = _criar_chave(sessao)
    autenticado = chaves_api.validar_chave_api(chave, session=sessao)
    assert autenticado is not None
    assert autenticado.id == user.id


def test_chave_inexistente(sessao):
    assert chaves_api.validar_chave_api("chave-que-nao-existe", session=sessao) is None


def test_chave_revogada_invalida(sessao):
    user, chave = _criar_chave(sessao)
    reg = sessao.query(ChaveApi).first()
    assert chaves_api.revogar_chave_api(user, reg.id, session=sessao) is True
    assert chaves_api.validar_chave_api(chave, session=sessao) is None


def test_chave_expirada_invalida(sessao):
    user, chave = _criar_chave(
        sessao, expira_em=datetime.now() + timedelta(hours=1)
    )
    reg = sessao.query(ChaveApi).first()
    reg.expira_em = datetime.now() - timedelta(seconds=1)
    sessao.commit()
    assert chaves_api.validar_chave_api(chave, session=sessao) is None
    sessao.refresh(reg)
    assert reg.ativa is False


def test_usuario_desativado_invalida(sessao):
    user, chave = _criar_chave(sessao)
    assert chaves_api.validar_chave_api(chave, session=sessao) is not None
    usuarios.desativar_usuario(user, session=sessao)
    assert chaves_api.validar_chave_api(chave, session=sessao) is None


def test_usuario_inexistente_invalida(sessao):
    chave = "chave-do-usuario-removido"
    sessao.add(
        ChaveApi(
            usuario_id=999999,
            rotulo="orfao",
            chave_hash=_hash(chave),
            ativa=True,
        )
    )
    sessao.commit()
    assert chaves_api.validar_chave_api(chave, session=sessao) is None


def test_falha_indistinguivel_entre_motivos(sessao):
    user, chave = _criar_chave(sessao)
    reg = sessao.query(ChaveApi).first()
    chaves_api.revogar_chave_api(user, reg.id, session=sessao)
    assert chaves_api.validar_chave_api(chave, session=sessao) is None
    assert chaves_api.validar_chave_api("chave-inexistente", session=sessao) is None
    assert chaves_api.validar_chave_api(None, session=sessao) is None
    assert chaves_api.validar_chave_api("", session=sessao) is None


# ==========================================
# AUTORIZAÇÃO E ISOLAMENTO
# ==========================================


def test_criacao_por_usuario_autorizado(sessao):
    user = _criar(sessao, papel=usuarios.USER)
    chave = chaves_api.criar_chave_api(user, "minha-chave", session=sessao)
    assert chaves_api.validar_chave_api(chave, session=sessao) is not None


def test_usuario_nao_acessa_chave_de_outro_usuario(sessao):
    dono, chave = _criar_chave(sessao, usuario_kwargs={"email": "dono@x.com", "nome": "Dono"})
    intruso = _criar(sessao, nome="Intruso", email="intruso@x.com")
    reg = sessao.query(ChaveApi).first()
    with pytest.raises(autorizacao.PermissaoNegadaError):
        chaves_api.listar_chaves_api(dono, autor=intruso, session=sessao)
    with pytest.raises(autorizacao.PermissaoNegadaError):
        chaves_api.revogar_chave_api(dono, reg.id, autor=intruso, session=sessao)
    assert reg.ativa is True


def test_revogacao_propria(sessao):
    user, chave = _criar_chave(sessao)
    reg = sessao.query(ChaveApi).first()
    assert chaves_api.revogar_chave_api(user, reg.id, session=sessao) is True
    sessao.refresh(reg)
    assert reg.ativa is False
    assert chaves_api.validar_chave_api(chave, session=sessao) is None
    assert chaves_api.revogar_chave_api(user, reg.id, session=sessao) is True


def test_revogacao_administrativa_conforme_autorizacao(sessao):
    admin = _admin(sessao)
    dono, chave = _criar_chave(sessao, usuario_kwargs={"email": "dono@x.com", "nome": "Dono"})
    reg = sessao.query(ChaveApi).first()
    assert chaves_api.revogar_chave_api(dono, reg.id, autor=admin, session=sessao) is True
    assert chaves_api.validar_chave_api(chave, session=sessao) is None


def test_usuario_sem_permissao_bloqueado(sessao):
    user = _criar(sessao, email="user@x.com")
    alvo = _criar(sessao, nome="Alvo", email="alvo@x.com")
    with pytest.raises(autorizacao.PermissaoNegadaError):
        chaves_api.listar_chaves_api(alvo, autor=user, session=sessao)
    with pytest.raises(autorizacao.PermissaoNegadaError):
        chaves_api.revogar_chave_api(alvo, 1, autor=user, session=sessao)


def test_superadmin_pode_administrar(sessao):
    root = _superadmin(sessao)
    dono, chave = _criar_chave(sessao, usuario_kwargs={"email": "dono@x.com", "nome": "Dono"})
    reg = sessao.query(ChaveApi).first()
    assert len(chaves_api.listar_chaves_api(dono, autor=root, session=sessao)) == 1
    assert chaves_api.revogar_chave_api(dono, reg.id, autor=root, session=sessao) is True
    assert chaves_api.validar_chave_api(chave, session=sessao) is None


def test_multiplas_chaves_mesmo_usuario(sessao):
    user, c1 = _criar_chave(sessao)
    c2 = chaves_api.criar_chave_api(user, "segunda", session=sessao)
    c3 = chaves_api.criar_chave_api(user, "terceira", session=sessao)
    assert len(chaves_api.listar_chaves_api(user, session=sessao)) == 3
    assert chaves_api.validar_chave_api(c1, session=sessao).id == user.id
    assert chaves_api.validar_chave_api(c2, session=sessao).id == user.id
    assert chaves_api.validar_chave_api(c3, session=sessao).id == user.id


def test_isolamento_entre_usuarios(sessao):
    u1, chave1 = _criar_chave(sessao, usuario_kwargs={"email": "u1@x.com", "nome": "Um"})
    u2, chave2 = _criar_chave(sessao, usuario_kwargs={"email": "u2@x.com", "nome": "Dois"})
    assert chaves_api.validar_chave_api(chave1, session=sessao).id == u1.id
    assert chaves_api.validar_chave_api(chave2, session=sessao).id == u2.id
    assert [k.id for k in chaves_api.listar_chaves_api(u1, session=sessao)] != [
        k.id for k in chaves_api.listar_chaves_api(u2, session=sessao)
    ]
    reg1 = (
        sessao.query(ChaveApi)
        .filter(ChaveApi.usuario_id == u1.id)
        .first()
    )
    assert chaves_api.revogar_chave_api(u2, reg1.id, session=sessao) is False
    assert chaves_api.validar_chave_api(chave1, session=sessao) is not None


# ==========================================
# AUDITORIA
# ==========================================


def test_auditoria_da_criacao(sessao):
    _criar_chave(sessao)
    acoes = [e.acao for e in _auditoria(sessao)]
    assert "API_KEY_CRIADA" in acoes


def test_auditoria_da_revogacao(sessao):
    user, chave = _criar_chave(sessao)
    reg = sessao.query(ChaveApi).first()
    chaves_api.revogar_chave_api(user, reg.id, session=sessao)
    acoes = [e.acao for e in _auditoria(sessao)]
    assert "API_KEY_CRIADA" in acoes
    assert "API_KEY_REVOGADA" in acoes


def test_nenhum_segredo_na_auditoria(sessao):
    user, chave = _criar_chave(sessao)
    reg = sessao.query(ChaveApi).first()
    chaves_api.revogar_chave_api(user, reg.id, session=sessao)
    chave_hash = _hash(chave)
    for e in _auditoria(sessao):
        texto = f"{e.acao} {e.alvo or ''} {e.detalhe or ''}"
        assert chave not in texto
        assert chave_hash not in texto
        assert e.detalhe is None or "hash" not in e.detalhe.lower()


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
        chave = chaves_api.criar_chave_api(user, "prod", session=sessao_local)
        autenticado = chaves_api.validar_chave_api(chave, session=sessao_local)
        assert autenticado is not None
        assert autenticado.id == user.id
        assert sessao_local.query(ChaveApi).count() == 1
    finally:
        sessao_local.close()
