"""Testes do motor central de autorização (Fase 5, Etapa 6).

Cobre a matriz central de permissões (``PAPEL_PERMISSOES``), a checagem
``tem_permissao``/``requer_permissao``, a identificação de papel, a política
anti-escalonamento (ADMIN nunca promove para SUPERADMIN), a proteção do
SUPERADMIN, usuários desativados, ``usuario=None`` como VISITOR e a ausência
de segredos em logs/erros.
"""
import logging

import pytest
from werkzeug.security import generate_password_hash

from pipeline_dados.banco_dados import Usuario
from services.autorizacao import (
    PAPEL_PERMISSOES,
    PermissaoNegadaError,
    eh_admin,
    eh_permissao_escopo_proprio,
    eh_superadmin,
    eh_user,
    eh_visitor,
    papeis_atribuiveis_por,
    papel_de,
    pode_alterar_papel,
    pode_criar_usuario_com_papel,
    requer_permissao,
    tem_permissao,
    usuario_protegido,
)
from services.usuarios import (
    ADMIN,
    PAPEIS_VALIDOS,
    SUPERADMIN,
    USER,
    VISITOR,
)


def _usuario(papel, ativo=True, nome="Teste"):
    return Usuario(nome=nome, papel=papel, ativo=ativo)


# ==========================================
# SUPERADMIN
# ==========================================


def test_superadmin_possui_todas_as_permissoes():
    su = _usuario(SUPERADMIN)
    for permissao in (
        "usuarios.ler",
        "usuarios.criar",
        "sistema.configuracao_critica",
        "execucao.destrutiva",
        "publico.consultar",
        "dados.consultar",
        "qualquer.coisa.futura",
    ):
        assert tem_permissao(su, permissao)
    assert tem_permissao(su, "*") is True
    assert eh_superadmin(su) is True
    assert papel_de(su) == SUPERADMIN


def test_superadmin_administra_usuarios_administradores_e_configuracoes():
    su = _usuario(SUPERADMIN)
    assert papeis_atribuiveis_por(su) == frozenset(PAPEIS_VALIDOS)
    assert pode_criar_usuario_com_papel(su, SUPERADMIN) is True
    assert pode_alterar_papel(su, _usuario(USER), SUPERADMIN) is True


# ==========================================
# ADMIN
# ==========================================


PERMISSOES_ADMIN = {
    "usuarios.ler",
    "usuarios.criar",
    "usuarios.ativar",
    "usuarios.desativar",
    "usuarios.alterar_papel",
    "dados.consultar",
    "documentos.consultar",
    "relatorios.consultar",
    "indicadores.consultar",
    "historico.consultar",
    "alertas.gerenciar",
    "telegram.administrar",
    "conta.propria",
}


def test_admin_possui_permissoes_administrativas_previstas():
    admin = _usuario(ADMIN)
    for permissao in PERMISSOES_ADMIN:
        assert tem_permissao(admin, permissao), permissao
    assert eh_admin(admin) is True


def test_admin_nao_possui_permissoes_exclusivas_do_superadmin():
    admin = _usuario(ADMIN)
    assert tem_permissao(admin, "*") is False
    assert eh_superadmin(admin) is False
    for permissao in (
        "sistema.configuracao_critica",
        "execucao.destrutiva",
        "usuarios.promover_superadmin",
        "superadmin.gerenciar",
    ):
        assert tem_permissao(admin, permissao) is False


def test_admin_nao_atribui_superadmin():
    admin = _usuario(ADMIN)
    assert papeis_atribuiveis_por(admin) == frozenset({USER, VISITOR})
    assert SUPERADMIN not in papeis_atribuiveis_por(admin)
    assert pode_criar_usuario_com_papel(admin, SUPERADMIN) is False


# ==========================================
# USER
# ==========================================


PERMISSOES_USER = {
    "dados.consultar",
    "documentos.consultar",
    "relatorios.consultar",
    "indicadores.consultar",
    "historico.consultar",
    "alertas.consultar",
    "notificacoes.consultar",
    "conta.propria",
    "ativos.proprios",
    "preferencias.proprias",
}


def test_user_possui_permissoes_de_consulta_previstas():
    user = _usuario(USER)
    for permissao in PERMISSOES_USER:
        assert tem_permissao(user, permissao), permissao
    assert eh_user(user) is True


def test_user_nao_possui_permissoes_administrativas():
    user = _usuario(USER)
    for permissao in (
        "usuarios.ler",
        "usuarios.criar",
        "usuarios.ativar",
        "usuarios.desativar",
        "usuarios.alterar_papel",
        "alertas.gerenciar",
        "telegram.administrar",
        "*",
    ):
        assert tem_permissao(user, permissao) is False
    assert papeis_atribuiveis_por(user) == frozenset()
    assert pode_alterar_papel(user, _usuario(USER), ADMIN) is False


def test_user_nao_consulta_alertas_gerenciaveis():
    user = _usuario(USER)
    assert tem_permissao(user, "alertas.consultar") is True
    assert tem_permissao(user, "alertas.gerenciar") is False


# ==========================================
# VISITOR
# ==========================================


PERMISSOES_VISITOR = {
    "publico.consultar",
    "ativos.publicos.consultar",
    "indicadores.publicos.consultar",
}


def test_visitor_possui_somente_permissoes_publicas():
    visitante = _usuario(VISITOR)
    for permissao in PERMISSOES_VISITOR:
        assert tem_permissao(visitante, permissao), permissao
    assert eh_visitor(visitante) is True
    for permissao in (
        "dados.consultar",
        "documentos.consultar",
        "relatorios.consultar",
        "historico.consultar",
        "alertas.consultar",
        "notificacoes.consultar",
        "conta.propria",
        "ativos.proprios",
        "usuarios.ler",
        "alertas.gerenciar",
        "*",
    ):
        assert tem_permissao(visitante, permissao) is False


def test_visitor_nao_possui_privilegios_administrativos():
    visitante = _usuario(VISITOR)
    assert papeis_atribuiveis_por(visitante) == frozenset()
    assert pode_alterar_papel(visitante, _usuario(USER), USER) is False


# ==========================================
# usuario=None COMO VISITOR
# ==========================================


def test_usuario_none_funciona_como_visitor():
    for permissao in PERMISSOES_VISITOR:
        assert tem_permissao(None, permissao) is True
    assert tem_permissao(None, "dados.consultar") is False
    assert tem_permissao(None, "usuarios.ler") is False
    assert eh_visitor(None) is True
    assert eh_admin(None) is False
    assert eh_user(None) is False
    assert eh_superadmin(None) is False
    assert papel_de(None) == VISITOR
    assert requer_permissao(None, "publico.consultar") is True
    with pytest.raises(PermissaoNegadaError):
        requer_permissao(None, "dados.consultar")


# ==========================================
# PERMISSÃO DESCONHECIDA
# ==========================================


def test_permissao_desconhecida_e_negada():
    for papel in (ADMIN, USER, VISITOR):
        assert tem_permissao(_usuario(papel), "modulo.inexistente") is False
    assert tem_permissao(_usuario(USER), "permissao.fantasma") is False


def test_superadmin_tem_permissao_desconhecida_pelo_wildcard():
    assert tem_permissao(_usuario(SUPERADMIN), "modulo.inexistente") is True


# ==========================================
# ESCALONAMENTO DE PRIVILÉGIO
# ==========================================


def test_tentativa_de_escalonamento_e_negada():
    admin = _usuario(ADMIN)
    user = _usuario(USER)
    visitante = _usuario(VISITOR)
    assert pode_alterar_papel(admin, user, SUPERADMIN) is False
    assert pode_alterar_papel(admin, visitante, SUPERADMIN) is False
    assert pode_alterar_papel(user, user, ADMIN) is False
    assert pode_alterar_papel(user, user, SUPERADMIN) is False
    assert pode_alterar_papel(visitante, user, USER) is False


def test_admin_nao_promove_user_para_superadmin():
    admin = _usuario(ADMIN)
    user = _usuario(USER)
    assert pode_alterar_papel(admin, user, SUPERADMIN) is False
    assert pode_criar_usuario_com_papel(admin, SUPERADMIN) is False
    assert SUPERADMIN not in papeis_atribuiveis_por(admin)


def test_admin_gerencia_papeis_dentro_da_politica():
    admin = _usuario(ADMIN)
    user = _usuario(USER)
    visitante = _usuario(VISITOR)
    assert pode_alterar_papel(admin, user, VISITOR) is True
    assert pode_alterar_papel(admin, user, USER) is True
    assert pode_alterar_papel(admin, visitante, USER) is True


# ==========================================
# PROTEÇÃO DO SUPERADMIN
# ==========================================


def test_superadmin_inicial_protegido_de_admin():
    admin = _usuario(ADMIN)
    superadmin = _usuario(SUPERADMIN)
    assert usuario_protegido(superadmin) is True
    assert usuario_protegido(_usuario(USER)) is False
    assert pode_alterar_papel(admin, superadmin, USER) is False
    assert pode_alterar_papel(admin, superadmin, VISITOR) is False


def test_superadmin_pode_alterar_outro_superadmin():
    su = _usuario(SUPERADMIN)
    outro = _usuario(SUPERADMIN)
    assert pode_alterar_papel(su, outro, USER) is True
    assert pode_alterar_papel(su, outro, VISITOR) is True


# ==========================================
# USUÁRIO DESATIVADO
# ==========================================


def test_usuario_desativado_nao_recebe_autorizacao():
    su_desativado = _usuario(SUPERADMIN, ativo=False)
    user_desativado = _usuario(USER, ativo=False)
    admin_desativado = _usuario(ADMIN, ativo=False)
    for u in (su_desativado, user_desativado, admin_desativado):
        assert tem_permissao(u, "*") is False
        assert tem_permissao(u, "dados.consultar") is False
        assert tem_permissao(u, "publico.consultar") is False
        assert papel_de(u) is None
    assert eh_superadmin(su_desativado) is False
    assert eh_user(user_desativado) is False
    assert eh_admin(admin_desativado) is False
    assert papeis_atribuiveis_por(su_desativado) == frozenset()
    with pytest.raises(PermissaoNegadaError):
        requer_permissao(user_desativado, "dados.consultar")


# ==========================================
# REQUER PERMISSÃO (MECANISMO DE NEGAÇÃO)
# ==========================================


def test_requer_permissao_sucesso_retorna_true():
    admin = _usuario(ADMIN)
    assert requer_permissao(admin, "usuarios.ativar") is True
    assert requer_permissao(_usuario(USER), "relatorios.consultar") is True


def test_requer_permissao_negada_levanta_excecao():
    user = _usuario(USER)
    with pytest.raises(PermissaoNegadaError) as exc:
        requer_permissao(user, "telegram.administrar")
    assert exc.value.permissao == "telegram.administrar"
    assert exc.value.papel == USER
    assert exc.value.usuario_id is None


# ==========================================
# ISOLAMENTO ENTRE USUÁRIOS (preparo)
# ==========================================


def test_isolamento_entre_usuarios_preparado():
    assert eh_permissao_escopo_proprio("conta.propria") is True
    assert eh_permissao_escopo_proprio("ativos.proprios") is True
    assert eh_permissao_escopo_proprio("preferencias.proprias") is True
    assert eh_permissao_escopo_proprio("notificacoes.consultar") is True
    assert eh_permissao_escopo_proprio("dados.consultar") is False
    assert eh_permissao_escopo_proprio("usuarios.ler") is False
    assert "conta.propria" in PAPEL_PERMISSOES[USER]
    assert "conta.propria" in PAPEL_PERMISSOES[ADMIN]


# ==========================================
# SEM SEGREDOS EM LOGS / ERROS
# ==========================================


def test_erros_e_logs_nao_expoem_segredos(caplog):
    usuario = _usuario(USER)
    senha_secreta = "senhaSupersecreta42"
    usuario.senha_hash = generate_password_hash(senha_secreta)

    with caplog.at_level(logging.WARNING, logger="services.autorizacao"):
        try:
            requer_permissao(usuario, "usuarios.ler")
        except PermissaoNegadaError as exc:
            mensagem = str(exc)
            assert senha_secreta not in mensagem
            assert "senha" not in mensagem.lower()
            assert "token" not in mensagem.lower()
            assert "api" not in mensagem.lower()
            logger = logging.getLogger("services.autorizacao")
            logger.warning("Acesso negado: %s", exc)

    assert senha_secreta not in caplog.text
    assert "senhaSupersecreta42" not in caplog.text


def test_papel_de_nunca_le_senha():
    usuario = _usuario(USER)
    usuario.senha_hash = generate_password_hash("segredoExemplo7")
    assert papel_de(usuario) == USER
    assert eh_user(usuario) is True


# ==========================================
# INSTÂNCIAS INVÁLIDAS
# ==========================================


def test_objeto_invalido_e_tratado_como_sem_permissao():
    class ObjetoInvalido:
        pass

    assert papel_de(ObjetoInvalido()) is None
    assert tem_permissao(ObjetoInvalido(), "publico.consultar") is False
    assert eh_visitor(ObjetoInvalido()) is False
    with pytest.raises(PermissaoNegadaError):
        requer_permissao(ObjetoInvalido(), "publico.consultar")


def test_papel_invalido_e_negado():
    usuario = _usuario("ROOT")
    assert papel_de(usuario) is None
    assert tem_permissao(usuario, "*") is False
    assert tem_permissao(usuario, "publico.consultar") is False
