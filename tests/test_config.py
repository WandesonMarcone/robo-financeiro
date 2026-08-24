import os

import pytest


@pytest.fixture(autouse=True)
def limpar_variaveis_ambiente():
    """Isola as variáveis de ambiente entre os testes de config."""
    vars_salvas = {}
    for var in (
        "DATABASE_URL",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "SPREADSHEET_URL",
        "GROQ_API_KEY",
        "ADMIN_CHAT_IDS",
        "SUPERADMIN_CHAT_IDS",
    ):
        vars_salvas[var] = os.environ.get(var)
        os.environ.pop(var, None)
    yield
    for var, valor in vars_salvas.items():
        if valor is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = valor


def test_url_sqlite_padrao():
    import config

    url = config.obter_database_url()
    assert url == "sqlite:///pipeline_dados/banco_institucional.db"


def test_normaliza_postgres_para_postgresql():
    import config

    os.environ["DATABASE_URL"] = "postgres://user:pass@host:5432/db"
    assert config.obter_database_url().startswith("postgresql://")
    assert config.obter_database_url() == "postgresql://user:pass@host:5432/db"


def test_mantem_postgresql_intacto():
    import config

    os.environ["DATABASE_URL"] = "postgresql://user:pass@host:5432/db"
    assert config.obter_database_url() == "postgresql://user:pass@host:5432/db"


def test_verificacao_configuracao_sem_token():
    import config

    problemas, avisos = config.verificar_configuracao()
    assert any("TELEGRAM_BOT_TOKEN" in p for p in problemas)


def test_verificacao_configuracao_aponta_faltas_como_avisos():
    import config

    problemas, avisos = config.verificar_configuracao()
    todos = " ".join(problemas + avisos)
    assert "SPREADSHEET_URL" in todos
    assert "GROQ_API_KEY" in todos
