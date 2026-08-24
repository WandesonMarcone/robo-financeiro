import os

import pytest


@pytest.fixture(autouse=True)
def limpar_url():
    salva = os.environ.get("DATABASE_URL")
    os.environ.pop("DATABASE_URL", None)
    yield
    if salva is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = salva


def test_obter_database_url_sqlite_padrao():
    import config

    assert config.obter_database_url() == "sqlite:///pipeline_dados/banco_institucional.db"


def test_obter_database_url_normaliza_postgres():
    import config

    os.environ["DATABASE_URL"] = "postgres://user:pass@host/db"
    assert config.obter_database_url() == "postgresql://user:pass@host/db"
