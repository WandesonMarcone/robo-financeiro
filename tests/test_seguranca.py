import logging
import os

import pytest

from modules import seguranca


@pytest.fixture(autouse=True)
def limpar_ids():
    vars_salvas = {
        "ADMIN_CHAT_IDS": os.environ.get("ADMIN_CHAT_IDS"),
        "SUPERADMIN_CHAT_IDS": os.environ.get("SUPERADMIN_CHAT_IDS"),
        "TELEGRAM_CHAT_ID": os.environ.get("TELEGRAM_CHAT_ID"),
    }
    for var in vars_salvas:
        os.environ.pop(var, None)
    yield
    for var, valor in vars_salvas.items():
        if valor is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = valor


@pytest.fixture(autouse=True)
def banco_indisponivel(monkeypatch):
    """Simula banco indisponível: resolução cai no comportamento legado.

    Garante que os testes do mecanismo legado sejam determinísticos e não
    toquem o banco real do projeto. Os testes DB-first sobrescrevem a consulta
    (ou a sessão) conforme necessário.
    """

    def _falha(*args, **kwargs):
        raise RuntimeError("banco indisponível (simulado)")

    monkeypatch.setattr("atualizador_documentos.SessionDB", _falha)


def _papel_no_banco_fixo(monkeypatch, papel):
    """Simula um Telegram ID vinculado no banco com o papel informado."""
    monkeypatch.setattr(seguranca, "_papel_no_banco", lambda user_id: papel)


def test_usuario_sem_configuracao_e_user():
    os.environ.pop("ADMIN_CHAT_IDS", None)
    os.environ.pop("SUPERADMIN_CHAT_IDS", None)
    os.environ.pop("TELEGRAM_CHAT_ID", None)
    assert seguranca.papel_do_usuario(123) == seguranca.ROLE_USER
    assert seguranca.eh_admin(123) is False


def test_admin_configurado():
    os.environ["ADMIN_CHAT_IDS"] = "10, 20"
    assert seguranca.eh_admin(10) is True
    assert seguranca.eh_admin(20) is True
    assert seguranca.eh_admin(30) is False


def test_superadmin_configurado():
    os.environ["SUPERADMIN_CHAT_IDS"] = "99"
    assert seguranca.eh_superadmin(99) is True
    assert seguranca.eh_superadmin(10) is False


def test_fallback_admin_como_superadmin():
    os.environ["ADMIN_CHAT_IDS"] = "55"
    os.environ.pop("SUPERADMIN_CHAT_IDS", None)
    assert seguranca.eh_superadmin(55) is True


def test_dono_do_telegram_e_superadmin_legado():
    os.environ["TELEGRAM_CHAT_ID"] = "777"
    assert seguranca.papel_do_usuario(777) == seguranca.ROLE_SUPERADMIN


def test_hierarquia_niveis():
    assert seguranca.NIVEIS["USER"] < seguranca.NIVEIS["ADMIN"] < seguranca.NIVEIS["SUPERADMIN"]
    assert seguranca.NIVEIS[seguranca.ROLE_VISITOR] < seguranca.NIVEIS["USER"]


# ==========================================
# FASE 5, ETAPA 4 — RESOLUÇÃO DB-FIRST
# ==========================================


def test_usuario_vinculado_como_superadmin(monkeypatch):
    _papel_no_banco_fixo(monkeypatch, seguranca.ROLE_SUPERADMIN)
    assert seguranca.papel_do_usuario(500) == seguranca.ROLE_SUPERADMIN
    assert seguranca.eh_superadmin(500) is True
    assert seguranca.eh_admin(500) is True


def test_usuario_vinculado_como_admin(monkeypatch):
    _papel_no_banco_fixo(monkeypatch, seguranca.ROLE_ADMIN)
    assert seguranca.papel_do_usuario(501) == seguranca.ROLE_ADMIN
    assert seguranca.eh_admin(501) is True
    assert seguranca.eh_superadmin(501) is False


def test_usuario_vinculado_como_user(monkeypatch):
    _papel_no_banco_fixo(monkeypatch, seguranca.ROLE_USER)
    assert seguranca.papel_do_usuario(502) == seguranca.ROLE_USER
    assert seguranca.eh_admin(502) is False
    assert seguranca.eh_superadmin(502) is False


def test_usuario_vinculado_como_visitor(monkeypatch):
    _papel_no_banco_fixo(monkeypatch, seguranca.ROLE_VISITOR)
    assert seguranca.papel_do_usuario(503) == seguranca.ROLE_VISITOR
    assert seguranca.eh_admin(503) is False
    assert seguranca.eh_superadmin(503) is False


def test_telegram_nao_vinculado_usa_fallback_legado(monkeypatch):
    os.environ["SUPERADMIN_CHAT_IDS"] = "700"
    assert seguranca.papel_do_usuario(700) == seguranca.ROLE_SUPERADMIN
    assert seguranca.eh_superadmin(700) is True
    assert seguranca.eh_admin(700) is True


def test_banco_indisponivel_usa_fallback_legado():
    # O fixture autouse simula SessionDB indisponível; a resolução cai no legado.
    os.environ["SUPERADMIN_CHAT_IDS"] = "701"
    assert seguranca.papel_do_usuario(701) == seguranca.ROLE_SUPERADMIN
    assert seguranca.eh_superadmin(701) is True


def test_superadmin_legado_continua_funcionando():
    os.environ["SUPERADMIN_CHAT_IDS"] = "99"
    assert seguranca.eh_superadmin(99) is True


def test_admin_legado_continua_funcionando():
    os.environ["ADMIN_CHAT_IDS"] = "10, 20"
    assert seguranca.eh_admin(10) is True
    assert seguranca.eh_admin(30) is False


def test_usuario_comum_nao_recebe_privilegio(monkeypatch):
    # Vinculado como USER no banco mas listado em SUPERADMIN_CHAT_IDS:
    # o banco é a fonte de identidade e prevalece sobre o ambiente.
    _papel_no_banco_fixo(monkeypatch, seguranca.ROLE_USER)
    os.environ["SUPERADMIN_CHAT_IDS"] = "702"
    assert seguranca.papel_do_usuario(702) == seguranca.ROLE_USER
    assert seguranca.eh_admin(702) is False
    assert seguranca.eh_superadmin(702) is False


def test_usuario_comum_nao_recebe_privilegio_de_dono(monkeypatch):
    # Vinculado como USER no banco mesmo sendo o TELEGRAM_CHAT_ID legado.
    _papel_no_banco_fixo(monkeypatch, seguranca.ROLE_USER)
    os.environ["TELEGRAM_CHAT_ID"] = "777"
    assert seguranca.papel_do_usuario(777) == seguranca.ROLE_USER
    assert seguranca.eh_superadmin(777) is False


def test_telegram_chat_id_continua_como_mecanismo_legado():
    os.environ["TELEGRAM_CHAT_ID"] = "777"
    assert seguranca.papel_do_usuario(777) == seguranca.ROLE_SUPERADMIN
    assert seguranca.eh_superadmin(777) is True


def test_papel_do_usuario_none_cai_no_legado():
    assert seguranca.papel_do_usuario(None) == seguranca.ROLE_USER


# ==========================================
# FASE 5, ETAPA 4 — CONSULTA REAL NO BANCO
# ==========================================


def test_papel_no_banco_consulta_usuarios_reais(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from pipeline_dados.banco_dados import Base, Usuario

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessao = sessionmaker(bind=engine)()
    sessao.add_all(
        [
            Usuario(
                nome="Dono",
                email="dono@x.com",
                papel=seguranca.ROLE_SUPERADMIN,
                telegram_user_id=555,
            ),
            Usuario(
                nome="Visitante",
                email="v@x.com",
                papel=seguranca.ROLE_VISITOR,
                telegram_user_id=556,
            ),
        ]
    )
    sessao.commit()
    monkeypatch.setattr("atualizador_documentos.SessionDB", lambda: sessao)
    try:
        assert seguranca._papel_no_banco(555) == seguranca.ROLE_SUPERADMIN
        assert seguranca._papel_no_banco(556) == seguranca.ROLE_VISITOR
        assert seguranca._papel_no_banco(999) is None
    finally:
        sessao.close()
        engine.dispose()


def test_falha_no_banco_nao_expoe_segredos_nos_logs(monkeypatch, caplog):
    class _SessaoQueFalha:
        def query(self, *args, **kwargs):
            raise RuntimeError("falha interna senha=supersecreta")

        def close(self):
            pass

    monkeypatch.setattr("atualizador_documentos.SessionDB", lambda: _SessaoQueFalha())
    with caplog.at_level(logging.WARNING, logger="modules.seguranca"):
        resultado = seguranca._papel_no_banco(555)
    assert resultado is None
    assert "supersecreta" not in caplog.text
