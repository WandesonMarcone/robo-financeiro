"""Testes dos modelos aditivos da Fase 5 (Etapa 1).

Cobre os 4 novos modelos (usuarios, sessoes, chaves_api, auditoria_acesso),
a criação das tabelas sem alterar as tabelas legadas e as regras de segurança
estrutural (segredos nunca persistidos em texto puro; unicidade condicional).
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from pipeline_dados.banco_dados import (
    Ativo,
    AuditoriaAcesso,
    Base,
    ChaveApi,
    Sessao,
    TipoAtivo,
    Usuario,
)

_TABELAS_LEGADAS = {
    "ativos",
    "dados_financeiros_acoes",
    "dados_financeiros_fiis",
    "documentos_qualitativos",
    "ativos_perfil",
    "snapshots_fiis",
    "snapshots_acoes",
    "ativos_inquilinos",
    "indicadores_historico",
    "alertas_eventos",
}

_TABELAS_NOVAS = {
    "usuarios",
    "sessoes",
    "chaves_api",
    "auditoria_acesso",
    # Fase 6, Etapa 4 (aditivo): recursos privados por usuário.
    "ativos_acompanhados",
    "posicoes_carteira",
    # Fase 6, Etapa 5 (aditivo): preferências individuais por usuário.
    "preferencias_usuarios",
    # Fase 6, Etapa 6 (aditivo): motor de notificações individualizadas.
    "notificacoes",
    # Fase 7, Etapa 7.2 (aditivo): catálogo central de ativos no PostgreSQL.
    "ativos_catalogo",
}


@pytest.fixture()
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def sessao(engine):
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


# ==========================================
# CRIAÇÃO DE TABELAS
# ==========================================

def test_tabelas_fase5_sao_criadas(engine):
    tabelas = set(inspect(engine).get_table_names())
    assert _TABELAS_NOVAS <= tabelas


def test_tabelas_legadas_permanecem_intactas(engine):
    tabelas = set(inspect(engine).get_table_names())
    assert _TABELAS_LEGADAS <= tabelas
    assert _TABELAS_NOVAS <= tabelas


def test_total_de_tabelas(engine):
    tabelas = set(inspect(engine).get_table_names())
    assert tabelas == _TABELAS_LEGADAS | _TABELAS_NOVAS


# ==========================================
# SEGREDOS NUNCA EM TEXTO PURO
# ==========================================

def test_usuarios_nao_expoe_coluna_senha(engine):
    colunas = {c["name"] for c in inspect(engine).get_columns("usuarios")}
    assert "senha_hash" in colunas
    assert "senha" not in colunas


def test_sessoes_nao_expoe_coluna_token(engine):
    colunas = {c["name"] for c in inspect(engine).get_columns("sessoes")}
    assert "token_hash" in colunas
    assert "token" not in colunas


def test_chaves_api_nao_expoe_coluna_chave(engine):
    colunas = {c["name"] for c in inspect(engine).get_columns("chaves_api")}
    assert "chave_hash" in colunas
    assert "chave" not in colunas


def test_auditoria_nao_possui_campos_de_segredo(engine):
    colunas = {c["name"] for c in inspect(engine).get_columns("auditoria_acesso")}
    for proibido in ("senha", "token", "chave", "segredo"):
        assert not any(proibido in col for col in colunas), colunas


# ==========================================
# UNICIDADE CONDICIONAL
# ==========================================

def _usuario(email=None, telegram_user_id=None):
    return Usuario(nome="Teste", email=email, telegram_user_id=telegram_user_id)


def test_email_unico_quando_informado(sessao):
    sessao.add(_usuario(email="a@x.com"))
    sessao.commit()
    sessao.add(_usuario(email="a@x.com"))
    with pytest.raises(IntegrityError):
        sessao.commit()
    sessao.rollback()


def test_telegram_user_id_unico_quando_informado(sessao):
    sessao.add(_usuario(telegram_user_id=111))
    sessao.commit()
    sessao.add(_usuario(telegram_user_id=111))
    with pytest.raises(IntegrityError):
        sessao.commit()
    sessao.rollback()


def test_multiplos_null_em_email_e_telegram_permitidos(sessao):
    sessao.add_all([_usuario(), _usuario(), _usuario()])
    sessao.commit()
    assert sessao.query(Usuario).count() == 3


def test_email_nulo_nao_conflita_com_email_informado(sessao):
    sessao.add_all([_usuario(email=None), _usuario(email="b@x.com")])
    sessao.commit()
    assert sessao.query(Usuario).count() == 2


# ==========================================
# RELACIONAMENTOS
# ==========================================

def test_relacionamentos_do_usuario(sessao):
    user = Usuario(nome="Dono", email="dono@x.com")
    sessao.add(user)
    sessao.flush()

    sessao.add(
        Sessao(
            usuario_id=user.id,
            token_hash="a" * 64,
            expira_em=datetime.now() + timedelta(hours=24),
            origem="telegram",
        )
    )
    sessao.add(ChaveApi(usuario_id=user.id, rotulo="prod", chave_hash="b" * 64))
    sessao.add(AuditoriaAcesso(usuario_id=user.id, acao="LOGIN", sucesso=True, ip="127.0.0.1"))
    sessao.commit()

    assert len(user.sessoes) == 1
    assert len(user.chaves_api) == 1
    assert len(user.auditoria) == 1
    assert user.auditoria[0].acao == "LOGIN"


def test_auditoria_aceita_usuario_nulo(sessao):
    sessao.add(AuditoriaAcesso(usuario_id=None, acao="TENTATIVA_NEGADA", sucesso=False))
    sessao.commit()
    assert sessao.query(AuditoriaAcesso).count() == 1


def test_token_hash_unico(sessao):
    user = Usuario(nome="X")
    sessao.add(user)
    sessao.flush()
    sessao.add_all(
        [
            Sessao(usuario_id=user.id, token_hash="c" * 64, expira_em=datetime.now()),
            Sessao(usuario_id=user.id, token_hash="c" * 64, expira_em=datetime.now()),
        ]
    )
    with pytest.raises(IntegrityError):
        sessao.commit()
    sessao.rollback()


def test_chave_hash_unico(sessao):
    user = Usuario(nome="Y")
    sessao.add(user)
    sessao.flush()
    sessao.add_all(
        [ChaveApi(usuario_id=user.id, rotulo="r1", chave_hash="d" * 64),
         ChaveApi(usuario_id=user.id, rotulo="r2", chave_hash="d" * 64)]
    )
    with pytest.raises(IntegrityError):
        sessao.commit()
    sessao.rollback()


# ==========================================
# MODELOS LEGADOS CONTINUAM FUNCIONANDO
# ==========================================

def test_modelo_legado_continua_operacional(sessao):
    ativo = Ativo(ticker="GARE11", cnpj="00.000.000/0001-00", tipo=TipoAtivo.FII)
    sessao.add(ativo)
    sessao.commit()
    assert sessao.query(Ativo).filter_by(ticker="GARE11").one().tipo == TipoAtivo.FII
