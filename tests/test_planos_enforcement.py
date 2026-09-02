"""Testes da Fase 6, Etapa 9 — enforcement real de planos e entitlements.

Verificam que os limites definidos na Etapa 8 (``services/planos.py``) são
RESPEITADOS pela aplicação:

- ``limite.ativos_acompanhados`` em ``services/ativos_acompanhados``;
- ``limite.posicoes_carteira`` em ``services/carteira``;
- ``limite.notificacoes_ativas`` no motor de notificações.

Cobrem FREE/PREMIUM/PRO, SUPERADMIN ilimitado, isolamento entre usuários,
usuário desativado, tentativas de contornar o limite, PATCH que não aumenta o
consumo, corrida concorrente (inserção atômica) e a ausência de bloqueio
indevido de operações que não consomem recursos. Usa SQLite em memória (e um
SQLite em arquivo para o teste de corrida), seguindo o padrão dos testes.
"""
import os
import tempfile
import threading

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pipeline_dados.banco_dados import (
    Ativo,
    AtivoAcompanhado,
    Base,
    Notificacao,
    PosicaoCarteira,
    TipoAtivo,
    Usuario,
)
from services import ativos_acompanhados, autorizacao, carteira, notificacoes, planos, usuarios


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


def _criar(sessao, nome, email, papel=usuarios.USER, plano=None, ativo=True):
    user = usuarios.criar_usuario(
        nome=nome,
        email=email,
        senha="senha1234",
        papel=papel,
        ativo=ativo,
        session=sessao,
    )
    if plano is not None:
        user.plano = plano
        sessao.commit()
    return user


def _semear_ativos(sessao, quantidade):
    registros = [
        Ativo(ticker=f"TEST{i:04d}", cnpj=f"{i:014d}/0001-00", tipo=TipoAtivo.ACAO)
        for i in range(quantidade)
    ]
    sessao.add_all(registros)
    sessao.commit()
    return [registro.id for registro in registros]


def _evento(nome, **extra):
    evento = {"tipo": "ALERTA_MERCADO", "titulo": "titulo", "mensagem": "mensagem", "evento_id": nome}
    evento.update(extra)
    return evento


def _contar(sessao, modelo, usuario):
    return (
        sessao.query(modelo)
        .filter(modelo.usuario_id == usuario.id)
        .count()
    )


def _contar_ativas(sessao, usuario):
    """Notificações ativas (não lidas) do ``usuario``."""
    return (
        sessao.query(Notificacao)
        .filter(
            Notificacao.usuario_id == usuario.id,
            Notificacao.status != notificacoes.STATUS_LIDA,
        )
        .count()
    )


# ==========================================
# HELPERS CENTRAIS (atingiu_limite)
# ==========================================


def test_atingiu_limite_superadmin_nunca(sessao):
    sa = _criar(sessao, "Root", "root@x.com", papel=usuarios.SUPERADMIN)
    assert planos.atingiu_limite(sa, "limite.ativos_acompanhados", 10_000) is False


def test_atingiu_limite_desativado_sempre(sessao):
    user = _criar(sessao, "Off", "off@x.com")
    usuarios.desativar_usuario(user, session=sessao)
    assert planos.atingiu_limite(user, "limite.ativos_acompanhados", 0) is True
    assert planos.atingiu_limite(None, "limite.ativos_acompanhados", 0) is True


def test_atingiu_limite_conforme_plano(sessao):
    free = _criar(sessao, "Free", "free@x.com")
    limite_free = planos.LIMITES_DO_PLANO[planos.PLANO_FREE]["limite.ativos_acompanhados"]
    assert planos.atingiu_limite(free, "limite.ativos_acompanhados", limite_free - 1) is False
    assert planos.atingiu_limite(free, "limite.ativos_acompanhados", limite_free) is True


# ==========================================
# LIMITE: ATIVOS ACOMPANHADOS
# ==========================================


def test_free_limite_ativos_acompanhados(sessao):
    ativos = _semear_ativos(sessao, 15)
    free = _criar(sessao, "Free", "free@x.com")
    limite = planos.LIMITES_DO_PLANO[planos.PLANO_FREE]["limite.ativos_acompanhados"]
    for ativo_id in ativos[:limite]:
        ativos_acompanhados.adicionar_acompanhamento(free, ativo_id, session=sessao)
    assert _contar(sessao, AtivoAcompanhado, free) == limite
    with pytest.raises(ValueError, match="Limite de ativos acompanhados"):
        ativos_acompanhados.adicionar_acompanhamento(free, ativos[limite], session=sessao)
    assert _contar(sessao, AtivoAcompanhado, free) == limite


def test_premium_limite_ativos_acompanhados(sessao):
    ativos = _semear_ativos(sessao, 35)
    premium = _criar(sessao, "Premium", "prem@x.com", plano=planos.PLANO_PREMIUM)
    limite = planos.LIMITES_DO_PLANO[planos.PLANO_PREMIUM]["limite.ativos_acompanhados"]
    for ativo_id in ativos[:limite]:
        ativos_acompanhados.adicionar_acompanhamento(premium, ativo_id, session=sessao)
    assert _contar(sessao, AtivoAcompanhado, premium) == limite
    with pytest.raises(ValueError, match="Limite de ativos acompanhados"):
        ativos_acompanhados.adicionar_acompanhamento(premium, ativos[limite], session=sessao)


def test_pro_limite_ativos_acompanhados(sessao):
    ativos = _semear_ativos(sessao, 105)
    pro = _criar(sessao, "Pro", "pro@x.com", plano=planos.PLANO_PRO)
    limite = planos.LIMITES_DO_PLANO[planos.PLANO_PRO]["limite.ativos_acompanhados"]
    for ativo_id in ativos[:limite]:
        ativos_acompanhados.adicionar_acompanhamento(pro, ativo_id, session=sessao)
    assert _contar(sessao, AtivoAcompanhado, pro) == limite
    with pytest.raises(ValueError, match="Limite de ativos acompanhados"):
        ativos_acompanhados.adicionar_acompanhamento(pro, ativos[limite], session=sessao)


def test_superadmin_ilimitado_ativos(sessao):
    ativos = _semear_ativos(sessao, 40)
    sa = _criar(sessao, "Root", "root@x.com", papel=usuarios.SUPERADMIN)
    for ativo_id in ativos:
        ativos_acompanhados.adicionar_acompanhamento(sa, ativo_id, session=sessao)
    assert _contar(sessao, AtivoAcompanhado, sa) == len(ativos)


def test_isolamento_limite_entre_usuarios(sessao):
    ativos = _semear_ativos(sessao, 15)
    free_a = _criar(sessao, "FreeA", "a@x.com")
    free_b = _criar(sessao, "FreeB", "b@x.com")
    limite = planos.LIMITES_DO_PLANO[planos.PLANO_FREE]["limite.ativos_acompanhados"]
    for ativo_id in ativos[:limite]:
        ativos_acompanhados.adicionar_acompanhamento(free_a, ativo_id, session=sessao)
    with pytest.raises(ValueError, match="Limite"):
        ativos_acompanhados.adicionar_acompanhamento(free_a, ativos[limite], session=sessao)
    ativos_acompanhados.adicionar_acompanhamento(free_b, ativos[limite], session=sessao)
    assert _contar(sessao, AtivoAcompanhado, free_b) == 1


def test_remocao_libera_vaga_ativos(sessao):
    ativos = _semear_ativos(sessao, 15)
    free = _criar(sessao, "Free", "free@x.com")
    limite = planos.LIMITES_DO_PLANO[planos.PLANO_FREE]["limite.ativos_acompanhados"]
    for ativo_id in ativos[:limite]:
        ativos_acompanhados.adicionar_acompanhamento(free, ativo_id, session=sessao)
    alvo = ativos_acompanhados.listar_acompanhamentos(free, session=sessao)[0]
    removido = ativos_acompanhados.remover_acompanhamento(free, alvo.id, session=sessao)
    assert removido is True
    ativos_acompanhados.adicionar_acompanhamento(free, ativos[limite], session=sessao)
    assert _contar(sessao, AtivoAcompanhado, free) == limite


def test_consulta_listagem_nao_bloqueadas_no_limite(sessao):
    ativos = _semear_ativos(sessao, 15)
    free = _criar(sessao, "Free", "free@x.com")
    limite = planos.LIMITES_DO_PLANO[planos.PLANO_FREE]["limite.ativos_acompanhados"]
    for ativo_id in ativos[:limite]:
        ativos_acompanhados.adicionar_acompanhamento(free, ativo_id, session=sessao)
    registros = ativos_acompanhados.listar_acompanhamentos(free, session=sessao)
    assert len(registros) == limite
    alvo = registros[0]
    assert ativos_acompanhados.buscar_acompanhamento(free, alvo.id, session=sessao) is not None


def test_duplicata_no_limite_prevalece(sessao):
    ativos = _semear_ativos(sessao, 15)
    free = _criar(sessao, "Free", "free@x.com")
    limite = planos.LIMITES_DO_PLANO[planos.PLANO_FREE]["limite.ativos_acompanhados"]
    for ativo_id in ativos[:limite]:
        ativos_acompanhados.adicionar_acompanhamento(free, ativo_id, session=sessao)
    with pytest.raises(ValueError, match="já está na sua lista"):
        ativos_acompanhados.adicionar_acompanhamento(free, ativos[0], session=sessao)


def test_plano_invalido_ou_nulo_usa_free(sessao):
    ativos = _semear_ativos(sessao, 15)
    user = _criar(sessao, "Legado", "legado@x.com")
    user.plano = None
    sessao.commit()
    limite = planos.LIMITES_DO_PLANO[planos.PLANO_FREE]["limite.ativos_acompanhados"]
    for ativo_id in ativos[:limite]:
        ativos_acompanhados.adicionar_acompanhamento(user, ativo_id, session=sessao)
    with pytest.raises(ValueError, match="Limite"):
        ativos_acompanhados.adicionar_acompanhamento(user, ativos[limite], session=sessao)


def test_usuario_desativado_sem_acessos_ativos(sessao):
    ativos = _semear_ativos(sessao, 3)
    user = _criar(sessao, "Off", "off@x.com", ativo=False)
    with pytest.raises(autorizacao.PermissaoNegadaError):
        ativos_acompanhados.adicionar_acompanhamento(user, ativos[0], session=sessao)


def test_corrida_concorrente_respeita_limite_ativos():
    """Corrida real (threads + conexões) não ultrapassa o limite (INSERT atômico)."""
    db = os.path.join(tempfile.mkdtemp(), "corrida.db")
    engine = create_engine(
        f"sqlite:///{db}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine)
    sessao = S()
    ativos = _semear_ativos(sessao, 40)
    user = _criar(sessao, "Free", "free@x.com")
    uid = user.id
    sessao.close()

    limite = planos.LIMITES_DO_PLANO[planos.PLANO_FREE]["limite.ativos_acompanhados"]
    sucessos = []
    erros = []
    trava = threading.Lock()

    def trabalhador(ativo_id):
        s = S()
        try:
            dono = s.get(Usuario, uid)
            ativos_acompanhados.adicionar_acompanhamento(dono, ativo_id, session=s)
            with trava:
                sucessos.append(ativo_id)
        except Exception as exc:  # noqa: BLE001 - esperado para quem estoura o limite
            with trava:
                erros.append(str(exc))
        finally:
            s.close()

    fios = [threading.Thread(target=trabalhador, args=(aid,)) for aid in ativos]
    for fio in fios:
        fio.start()
    for fio in fios:
        fio.join()

    s = S()
    total = _contar(s, AtivoAcompanhado, s.get(Usuario, uid))
    s.close()
    assert total == limite
    assert len(sucessos) == limite
    assert any("Limite" in erro for erro in erros)


# ==========================================
# LIMITE: POSIÇÕES NA CARTEIRA
# ==========================================


def test_free_limite_posicoes_carteira(sessao):
    ativos = _semear_ativos(sessao, 10)
    free = _criar(sessao, "Free", "free@x.com")
    limite = planos.LIMITES_DO_PLANO[planos.PLANO_FREE]["limite.posicoes_carteira"]
    for ativo_id in ativos[:limite]:
        carteira.adicionar_posicao(free, ativo_id, 10, 25.0, session=sessao)
    assert _contar(sessao, PosicaoCarteira, free) == limite
    with pytest.raises(ValueError, match="Limite de posições"):
        carteira.adicionar_posicao(free, ativos[limite], 10, 25.0, session=sessao)
    assert _contar(sessao, PosicaoCarteira, free) == limite


def test_premium_limite_posicoes_carteira(sessao):
    ativos = _semear_ativos(sessao, 25)
    premium = _criar(sessao, "Premium", "prem@x.com", plano=planos.PLANO_PREMIUM)
    limite = planos.LIMITES_DO_PLANO[planos.PLANO_PREMIUM]["limite.posicoes_carteira"]
    for ativo_id in ativos[:limite]:
        carteira.adicionar_posicao(premium, ativo_id, 10, 25.0, session=sessao)
    assert _contar(sessao, PosicaoCarteira, premium) == limite
    with pytest.raises(ValueError, match="Limite de posições"):
        carteira.adicionar_posicao(premium, ativos[limite], 10, 25.0, session=sessao)


def test_pro_limite_posicoes_carteira(sessao):
    ativos = _semear_ativos(sessao, 205)
    pro = _criar(sessao, "Pro", "pro@x.com", plano=planos.PLANO_PRO)
    limite = planos.LIMITES_DO_PLANO[planos.PLANO_PRO]["limite.posicoes_carteira"]
    for ativo_id in ativos[:limite]:
        carteira.adicionar_posicao(pro, ativo_id, 10, 25.0, session=sessao)
    assert _contar(sessao, PosicaoCarteira, pro) == limite
    with pytest.raises(ValueError, match="Limite de posições"):
        carteira.adicionar_posicao(pro, ativos[limite], 10, 25.0, session=sessao)


def test_superadmin_ilimitado_carteira(sessao):
    ativos = _semear_ativos(sessao, 40)
    sa = _criar(sessao, "Root", "root@x.com", papel=usuarios.SUPERADMIN)
    for ativo_id in ativos:
        carteira.adicionar_posicao(sa, ativo_id, 10, 25.0, session=sessao)
    assert _contar(sessao, PosicaoCarteira, sa) == len(ativos)


def test_isolamento_limite_carteira(sessao):
    ativos = _semear_ativos(sessao, 10)
    free_a = _criar(sessao, "FreeA", "a@x.com")
    free_b = _criar(sessao, "FreeB", "b@x.com")
    limite = planos.LIMITES_DO_PLANO[planos.PLANO_FREE]["limite.posicoes_carteira"]
    for ativo_id in ativos[:limite]:
        carteira.adicionar_posicao(free_a, ativo_id, 10, 25.0, session=sessao)
    with pytest.raises(ValueError, match="Limite"):
        carteira.adicionar_posicao(free_a, ativos[limite], 10, 25.0, session=sessao)
    carteira.adicionar_posicao(free_b, ativos[limite], 10, 25.0, session=sessao)
    assert _contar(sessao, PosicaoCarteira, free_b) == 1


def test_remover_posicao_libera_vaga(sessao):
    ativos = _semear_ativos(sessao, 10)
    free = _criar(sessao, "Free", "free@x.com")
    limite = planos.LIMITES_DO_PLANO[planos.PLANO_FREE]["limite.posicoes_carteira"]
    for ativo_id in ativos[:limite]:
        carteira.adicionar_posicao(free, ativo_id, 10, 25.0, session=sessao)
    posicao = carteira.listar_posicoes(free, session=sessao)[0]
    assert carteira.remover_posicao(free, posicao.id, session=sessao) is True
    carteira.adicionar_posicao(free, ativos[limite], 10, 25.0, session=sessao)
    assert _contar(sessao, PosicaoCarteira, free) == limite


def test_patch_posicao_no_limite_nao_bloqueado(sessao):
    ativos = _semear_ativos(sessao, 10)
    free = _criar(sessao, "Free", "free@x.com")
    limite = planos.LIMITES_DO_PLANO[planos.PLANO_FREE]["limite.posicoes_carteira"]
    for ativo_id in ativos[:limite]:
        carteira.adicionar_posicao(free, ativo_id, 10, 25.0, session=sessao)
    posicao = carteira.listar_posicoes(free, session=sessao)[0]
    atualizada = carteira.atualizar_posicao(
        free, posicao.id, quantidade=99, preco_medio=30.5, session=sessao
    )
    assert atualizada is not None
    assert atualizada.quantidade == 99
    assert _contar(sessao, PosicaoCarteira, free) == limite


def test_duplicata_carteira_prevalece_sobre_limite(sessao):
    ativos = _semear_ativos(sessao, 10)
    free = _criar(sessao, "Free", "free@x.com")
    limite = planos.LIMITES_DO_PLANO[planos.PLANO_FREE]["limite.posicoes_carteira"]
    for ativo_id in ativos[:limite]:
        carteira.adicionar_posicao(free, ativo_id, 10, 25.0, session=sessao)
    with pytest.raises(ValueError, match="Já existe uma posição"):
        carteira.adicionar_posicao(free, ativos[0], 10, 25.0, session=sessao)


def test_usuario_desativado_sem_acessos_carteira(sessao):
    ativos = _semear_ativos(sessao, 3)
    user = _criar(sessao, "Off", "off@x.com", ativo=False)
    with pytest.raises(autorizacao.PermissaoNegadaError):
        carteira.adicionar_posicao(user, ativos[0], 10, 25.0, session=sessao)


# ==========================================
# LIMITE: NOTIFICAÇÕES ATIVAS
# ==========================================


def _processar(sessao, usuario, nome):
    return notificacoes.processar_evento(_evento(nome), session=sessao)


def test_free_limite_notificacoes_ativas(sessao):
    free = _criar(sessao, "Free", "free@x.com")
    limite = planos.LIMITES_DO_PLANO[planos.PLANO_FREE]["limite.notificacoes_ativas"]
    for i in range(limite + 10):
        resumo = _processar(sessao, free, f"ev-{i}")
    assert _contar(sessao, Notificacao, free) == limite
    resumo = _processar(sessao, free, "ev-alem")
    assert resumo["elegiveis"] == 0
    assert resumo["geradas"] == 0


def test_premium_limite_notificacoes_ativas(sessao):
    premium = _criar(sessao, "Premium", "prem@x.com", plano=planos.PLANO_PREMIUM)
    limite = planos.LIMITES_DO_PLANO[planos.PLANO_PREMIUM]["limite.notificacoes_ativas"]
    for i in range(limite + 5):
        _processar(sessao, premium, f"ev-{i}")
    assert _contar(sessao, Notificacao, premium) == limite


def test_pro_limite_notificacoes_ativas(monkeypatch, sessao):
    pro = _criar(sessao, "Pro", "pro@x.com", plano=planos.PLANO_PRO)
    limite_teste = 3
    monkeypatch.setitem(
        planos.LIMITES_DO_PLANO[planos.PLANO_PRO],
        "limite.notificacoes_ativas",
        limite_teste,
    )
    for i in range(limite_teste + 5):
        _processar(sessao, pro, f"ev-{i}")
    assert _contar(sessao, Notificacao, pro) == limite_teste


def test_ler_libera_vaga_notificacoes(sessao):
    free = _criar(sessao, "Free", "free@x.com")
    limite = planos.LIMITES_DO_PLANO[planos.PLANO_FREE]["limite.notificacoes_ativas"]
    for i in range(limite):
        _processar(sessao, free, f"ev-{i}")
    pendentes = notificacoes.listar_notificacoes(free, session=sessao, nao_lidas=True)
    notificacoes.marcar_como_lida(free, pendentes[0].id, session=sessao)
    resumo = _processar(sessao, free, "ev-novo")
    assert resumo["geradas"] == 1
    assert _contar_ativas(sessao, free) == limite


def test_superadmin_ilimitado_notificacoes(sessao):
    sa = _criar(sessao, "Root", "root@x.com", papel=usuarios.SUPERADMIN)
    for i in range(25):
        _processar(sessao, sa, f"ev-{i}")
    assert _contar(sessao, Notificacao, sa) == 25


def test_isolamento_notificacoes_limite(sessao):
    ativos = _semear_ativos(sessao, 2)
    free_a = _criar(sessao, "FreeA", "a@x.com")
    free_b = _criar(sessao, "FreeB", "b@x.com")
    ativos_acompanhados.adicionar_acompanhamento(free_a, ativos[0], session=sessao)
    ativos_acompanhados.adicionar_acompanhamento(free_b, ativos[1], session=sessao)
    limite = planos.LIMITES_DO_PLANO[planos.PLANO_FREE]["limite.notificacoes_ativas"]
    for i in range(limite):
        notificacoes.processar_evento(
            _evento(
                f"ev-{i}",
                ativo_id=ativos[0],
                origem=notificacoes.ORIGEM_ACOMPANHAMENTO,
            ),
            session=sessao,
        )
    assert _contar_ativas(sessao, free_a) == limite
    assert _contar(sessao, Notificacao, free_b) == 0
    resumo = notificacoes.processar_evento(
        _evento(
            "ev-b",
            ativo_id=ativos[1],
            origem=notificacoes.ORIGEM_ACOMPANHAMENTO,
        ),
        session=sessao,
    )
    assert resumo["geradas"] == 1
    assert _contar(sessao, Notificacao, free_b) == 1


def test_canais_limitados_no_limite(sessao):
    """No limite, canais adicionais não estouram a cota do usuário."""
    free = _criar(sessao, "Free", "free@x.com")
    free.telegram_user_id = 9001
    sessao.commit()
    limite_teste = 3
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setitem(
        planos.LIMITES_DO_PLANO[planos.PLANO_FREE],
        "limite.notificacoes_ativas",
        limite_teste,
    )
    try:
        for i in range(limite_teste):
            _processar(sessao, free, f"ev-{i}")
        ativas = _contar(sessao, Notificacao, free)
        assert ativas == limite_teste
        resumo = _processar(sessao, free, "ev-alem")
        assert resumo["geradas"] == 0
    finally:
        monkeypatch.undo()


def test_usuario_desativado_nao_recebe_notificacoes(sessao):
    user = _criar(sessao, "Off", "off@x.com", ativo=False)
    resumo = notificacoes.processar_evento(_evento("ev-1"), session=sessao)
    assert resumo["elegiveis"] == 0
    assert _contar(sessao, Notificacao, user) == 0


def test_processar_evento_sem_usuario_elegivel(sessao):
    resumo = notificacoes.processar_evento(_evento("ev-vazio"), session=sessao)
    assert resumo["elegiveis"] == 0
    assert resumo["geradas"] == 0
