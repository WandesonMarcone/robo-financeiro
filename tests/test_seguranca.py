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
