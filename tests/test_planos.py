"""Testes da Fase 6, Etapa 8 — camada central de planos e entitlements.

Cobre o catálogo de planos (FREE/PREMIUM/PRO), a consulta de plano efetivo, os
entitlements e limites por plano, o resumo serializável e a gestão de planos
(anti-escalonamento): somente SUPERADMIN altera planos, nenhum usuário altera o
próprio plano e o cliente nunca define o plano. Garante que usuários desativados
não possuem recursos e que nenhum segredo transita pela auditoria.

Usa SQLite em memória, seguindo o padrão dos testes do projeto.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pipeline_dados.banco_dados import AuditoriaAcesso, Base, Usuario
from services import autorizacao, planos, usuarios


@pytest.fixture()
def sessao():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _criar(sessao, nome="Ana", email="ana@x.com", papel=usuarios.USER, **kwargs):
    dados = {"nome": nome, "email": email, "senha": "senha1234", "papel": papel}
    dados.update(kwargs)
    return usuarios.criar_usuario(session=sessao, **dados)


def _auditoria(sessao):
    return sessao.query(AuditoriaAcesso).order_by(AuditoriaAcesso.id).all()


def _texto_auditoria(sessao):
    return "\n".join(
        f"{e.acao} {e.alvo or ''} {e.detalhe or ''}" for e in _auditoria(sessao)
    )


# ==========================================
# CATÁLOGO DE PLANOS
# ==========================================


def test_catalogo_planos_fechado():
    assert planos.PLANOS_VALIDOS == (planos.PLANO_FREE, planos.PLANO_PREMIUM, planos.PLANO_PRO)
    assert planos.PLANO_PADRAO == planos.PLANO_FREE


def test_catalogo_entitlements_monotono():
    free = planos.RECURSOS_DO_PLANO[planos.PLANO_FREE]
    premium = planos.RECURSOS_DO_PLANO[planos.PLANO_PREMIUM]
    pro = planos.RECURSOS_DO_PLANO[planos.PLANO_PRO]
    assert free == frozenset()
    assert premium != frozenset()
    assert premium.issubset(pro)
    assert pro.issuperset(premium)
    assert pro != premium


def test_catalogo_limites_monotono():
    free = planos.LIMITES_DO_PLANO[planos.PLANO_FREE]
    premium = planos.LIMITES_DO_PLANO[planos.PLANO_PREMIUM]
    pro = planos.LIMITES_DO_PLANO[planos.PLANO_PRO]
    assert set(free) == set(premium) == set(pro)
    for recurso in free:
        assert free[recurso] < premium[recurso] < pro[recurso]


def test_limites_positivos_por_plano():
    for plano in planos.PLANOS_VALIDOS:
        for recurso, limite in planos.LIMITES_DO_PLANO[plano].items():
            assert isinstance(limite, int) and limite > 0, (plano, recurso)


# ==========================================
# PLANO EFETIVO (plano_de)
# ==========================================


def test_plano_padrao_novo_usuario(sessao):
    user = _criar(sessao)
    assert user.plano == planos.PLANO_PADRAO
    assert planos.plano_de(user) == planos.PLANO_FREE


def test_plano_padrao_usuario_legado_sem_plano(sessao):
    user = _criar(sessao)
    user.plano = None
    sessao.commit()
    assert planos.plano_de(user) == planos.PLANO_FREE


def test_plano_padrao_usuario_plano_invalido(sessao):
    user = _criar(sessao)
    user.plano = "GOLD"
    sessao.commit()
    assert planos.plano_de(user) == planos.PLANO_FREE


def test_plano_de_none():
    assert planos.plano_de(None) is None


def test_plano_de_usuario_desativado(sessao):
    user = _criar(sessao)
    usuarios.desativar_usuario(user, session=sessao)
    assert planos.plano_de(user) is None


def test_plano_de_objeto_invalido():
    assert planos.plano_de(object()) is None


def test_plano_de_valores_persistidos(sessao):
    premium = _criar(sessao, nome="Prem", email="prem@x.com")
    premium.plano = planos.PLANO_PREMIUM
    pro = _criar(sessao, nome="Pro", email="pro@x.com")
    pro.plano = planos.PLANO_PRO
    sessao.commit()
    assert planos.plano_de(premium) == planos.PLANO_PREMIUM
    assert planos.plano_de(pro) == planos.PLANO_PRO


# ==========================================
# ENTITLEMENTS (tem_entitlement)
# ==========================================


def test_entitlements_superadmin_todos(sessao):
    sa = _criar(sessao, papel=usuarios.SUPERADMIN)
    for recurso in planos.RECURSOS_VALIDOS:
        assert planos.tem_entitlement(sa, recurso) is True


def test_entitlements_free_vazio(sessao):
    user = _criar(sessao)
    assert planos.entitlements_de(user) == frozenset()
    for recurso in planos.RECURSOS_VALIDOS:
        assert planos.tem_entitlement(user, recurso) is False


def test_entitlements_premium(sessao):
    user = _criar(sessao)
    user.plano = planos.PLANO_PREMIUM
    sessao.commit()
    esperados = planos.RECURSOS_DO_PLANO[planos.PLANO_PREMIUM]
    assert planos.entitlements_de(user) == esperados
    for recurso in planos.RECURSOS_VALIDOS:
        assert planos.tem_entitlement(user, recurso) == (recurso in esperados)


def test_entitlements_pro(sessao):
    user = _criar(sessao)
    user.plano = planos.PLANO_PRO
    sessao.commit()
    assert planos.entitlements_de(user) == planos.RECURSOS_DO_PLANO[planos.PLANO_PRO]


def test_entitlements_desativado_e_none(sessao):
    user = _criar(sessao)
    user.plano = planos.PLANO_PRO
    sessao.commit()
    usuarios.desativar_usuario(user, session=sessao)
    assert planos.entitlements_de(user) == frozenset()
    assert planos.entitlements_de(None) == frozenset()
    for recurso in planos.RECURSOS_VALIDOS:
        assert planos.tem_entitlement(user, recurso) is False
        assert planos.tem_entitlement(None, recurso) is False


# ==========================================
# LIMITES NUMÉRICOS (obter_limite)
# ==========================================


def test_limite_superadmin_ilimitado(sessao):
    sa = _criar(sessao, papel=usuarios.SUPERADMIN)
    for recurso in planos.LIMITES_VALIDOS:
        assert planos.obter_limite(sa, recurso) is None


def test_limites_por_plano(sessao):
    for plano in planos.PLANOS_VALIDOS:
        user = _criar(sessao, email=f"{plano.lower()}@x.com")
        user.plano = plano
        sessao.commit()
        for recurso, limite in planos.LIMITES_DO_PLANO[plano].items():
            assert planos.obter_limite(user, recurso) == limite


def test_limite_desativado_none_e_desconhecido(sessao):
    user = _criar(sessao)
    user.plano = planos.PLANO_PRO
    sessao.commit()
    usuarios.desativar_usuario(user, session=sessao)
    assert planos.obter_limite(user, "limite.ativos_acompanhados") == 0
    assert planos.obter_limite(None, "limite.ativos_acompanhados") == 0
    assert planos.obter_limite(_criar(sessao, email="x2@x.com"), "recurso.desconhecido") == 0


# ==========================================
# RESUMOS SERIALIZÁVEIS
# ==========================================


def test_resumo_do_plano_validos():
    for plano in planos.PLANOS_VALIDOS:
        resumo = planos.resumo_do_plano(plano)
        assert resumo["plano"] == plano
        assert set(resumo["entitlements"]) == set(planos.RECURSOS_DO_PLANO[plano])
        assert resumo["limites"] == dict(planos.LIMITES_DO_PLANO[plano])


def test_resumo_do_plano_invalido():
    assert planos.resumo_do_plano("GOLD") == {"plano": "GOLD", "entitlements": [], "limites": {}}


def test_resumo_do_usuario_free(sessao):
    resumo = planos.resumo_do_usuario(_criar(sessao))
    assert resumo["plano"] == planos.PLANO_FREE
    assert resumo["entitlements"] == []
    assert resumo["limites"] == dict(planos.LIMITES_DO_PLANO[planos.PLANO_FREE])


def test_resumo_do_usuario_superadmin(sessao):
    resumo = planos.resumo_do_usuario(_criar(sessao, papel=usuarios.SUPERADMIN))
    assert resumo["plano"] is not None
    assert set(resumo["entitlements"]) == set(planos.RECURSOS_VALIDOS)
    for recurso in planos.LIMITES_VALIDOS:
        assert resumo["limites"][recurso] is None


def test_resumo_do_usuario_desativado_e_none(sessao):
    user = _criar(sessao)
    usuarios.desativar_usuario(user, session=sessao)
    assert planos.resumo_do_usuario(user) == {"plano": None, "entitlements": [], "limites": {}}
    assert planos.resumo_do_usuario(None) == {"plano": None, "entitlements": [], "limites": {}}


# ==========================================
# AUTORIZAÇÃO DE GESTÃO DE PLANO (anti-escalonamento)
# ==========================================


def test_pode_alterar_plano_superadmin(sessao):
    sa = _criar(sessao, papel=usuarios.SUPERADMIN)
    for plano in planos.PLANOS_VALIDOS:
        assert planos.pode_alterar_plano(sa, plano) is True


def test_pode_alterar_plano_superadmin_plano_invalido(sessao):
    sa = _criar(sessao, papel=usuarios.SUPERADMIN)
    assert planos.pode_alterar_plano(sa, "GOLD") is False


def test_pode_alterar_plano_outros_papeis(sessao):
    admin = _criar(sessao, nome="Adm", email="adm@x.com", papel=usuarios.ADMIN)
    user = _criar(sessao, nome="Usr", email="usr@x.com", papel=usuarios.USER)
    visitor = _criar(sessao, nome="Vis", email="vis@x.com", papel=usuarios.VISITOR)
    for autor in (admin, user, visitor):
        for plano in planos.PLANOS_VALIDOS:
            assert planos.pode_alterar_plano(autor, plano) is False


def test_pode_alterar_plano_desativado_e_none(sessao):
    sa = _criar(sessao, papel=usuarios.SUPERADMIN)
    usuarios.desativar_usuario(sa, session=sessao)
    assert planos.pode_alterar_plano(sa, planos.PLANO_PRO) is False
    assert planos.pode_alterar_plano(None, planos.PLANO_PRO) is False


# ==========================================
# GESTÃO DE PLANO (alterar_plano)
# ==========================================


def test_alterar_plano_superadmin_persiste(sessao):
    sa = _criar(sessao, papel=usuarios.SUPERADMIN)
    alvo = _criar(sessao, nome="Alvo", email="alvo@x.com")
    assert planos.plano_de(alvo) == planos.PLANO_FREE
    planos.alterar_plano(sa, alvo, planos.PLANO_PREMIUM, session=sessao, ip="10.0.0.1")
    sessao.refresh(alvo)
    assert alvo.plano == planos.PLANO_PREMIUM
    assert planos.plano_de(alvo) == planos.PLANO_PREMIUM


def test_alterar_plano_ciclo_completo(sessao):
    sa = _criar(sessao, papel=usuarios.SUPERADMIN)
    alvo = _criar(sessao, nome="Alvo", email="alvo@x.com")
    for plano in (planos.PLANO_PREMIUM, planos.PLANO_PRO, planos.PLANO_FREE):
        planos.alterar_plano(sa, alvo, plano, session=sessao)
        sessao.refresh(alvo)
        assert planos.plano_de(alvo) == plano


def test_alterar_plano_audita_sem_segredos(sessao):
    sa = _criar(sessao, papel=usuarios.SUPERADMIN)
    alvo = _criar(sessao, nome="Alvo", email="alvo@x.com")
    planos.alterar_plano(sa, alvo, planos.PLANO_PRO, session=sessao, ip="127.0.0.1")
    acoes = [e.acao for e in _auditoria(sessao)]
    assert planos.ACAO_PLANO_ALTERADO in acoes
    assert "senha1234" not in _texto_auditoria(sessao)
    assert "plano=PRO" in _texto_auditoria(sessao)


def test_alterar_plano_nao_superadmin_negado(sessao):
    admin = _criar(sessao, nome="Adm", email="adm@x.com", papel=usuarios.ADMIN)
    user = _criar(sessao, nome="Usr", email="usr@x.com", papel=usuarios.USER)
    alvo = _criar(sessao, nome="Alvo", email="alvo@x.com")
    for autor in (admin, user):
        with pytest.raises(autorizacao.PermissaoNegadaError):
            planos.alterar_plano(autor, alvo, planos.PLANO_PRO, session=sessao)
    sessao.refresh(alvo)
    assert alvo.plano == planos.PLANO_FREE


def test_alterar_plano_proprio_negado(sessao):
    user = _criar(sessao)
    with pytest.raises(autorizacao.PermissaoNegadaError):
        planos.alterar_plano(user, user, planos.PLANO_PRO, session=sessao)
    sessao.refresh(user)
    assert user.plano == planos.PLANO_FREE


def test_alterar_plano_invalido_rejeitado(sessao):
    sa = _criar(sessao, papel=usuarios.SUPERADMIN)
    alvo = _criar(sessao, nome="Alvo", email="alvo@x.com")
    with pytest.raises(ValueError):
        planos.alterar_plano(sa, alvo, "GOLD", session=sessao)
    sessao.refresh(alvo)
    assert alvo.plano == planos.PLANO_FREE


def test_alterar_plano_alvo_inexistente(sessao):
    sa = _criar(sessao, papel=usuarios.SUPERADMIN)
    with pytest.raises(ValueError):
        planos.alterar_plano(sa, None, planos.PLANO_PRO, session=sessao)


def test_alterar_plano_superadmin_desativado_negado(sessao):
    sa = _criar(sessao, papel=usuarios.SUPERADMIN)
    alvo = _criar(sessao, nome="Alvo", email="alvo@x.com")
    usuarios.desativar_usuario(sa, session=sessao)
    with pytest.raises(autorizacao.PermissaoNegadaError):
        planos.alterar_plano(sa, alvo, planos.PLANO_PRO, session=sessao)
    sessao.refresh(alvo)
    assert alvo.plano == planos.PLANO_FREE


def test_alterar_plano_sem_sessao_propria(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine)
    monkeypatch.setattr("services.usuarios.SessionDB", S)
    sessao = S()
    try:
        sa = _criar(sessao, papel=usuarios.SUPERADMIN)
        alvo = _criar(sessao, nome="Alvo", email="alvo@x.com")
        planos.alterar_plano(sa, alvo, planos.PLANO_PRO, ip="127.0.0.1")
        sessao.expire_all()
        assert sessao.get(Usuario, alvo.id).plano == planos.PLANO_PRO
    finally:
        sessao.close()
