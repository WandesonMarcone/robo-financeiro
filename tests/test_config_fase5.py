"""Testes das configurações aditivas da Fase 5 (Etapa 1).

Valida que as novas configurações de autenticação possuem padrões seguros e
são lidas do ambiente, sem remover nenhuma variável existente da V1.0.1.
"""
import importlib
import os

import pytest

import config

_VARIAVEIS_FASE5 = (
    "SESSAO_TTL_HORAS",
    "PRIMEIRO_ADMIN_TELEGRAM_ID",
    "AUDITORIA_ATIVA",
    "API_ENABLED",
    "TELEGRAM_WEBHOOK_SECRET",
    "API_CORS_ORIGINS",
)


@pytest.fixture(autouse=True)
def ambiente_isolado():
    salvas = {var: os.environ.get(var) for var in _VARIAVEIS_FASE5}
    yield
    for var, valor in salvas.items():
        if valor is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = valor
    importlib.reload(config)


def test_padroes_seguros():
    assert config.SESSAO_TTL_HORAS == 168
    assert config.PRIMEIRO_ADMIN_TELEGRAM_ID == ""
    assert config.AUDITORIA_ATIVA is True
    assert config.API_ENABLED is False
    assert config.RATE_LIMIT_API_POR_MINUTO == 120
    assert config.RATE_LIMIT_AUTH_POR_MINUTO == 10
    assert config.API_CORS_ORIGINS == ()


def test_sessao_ttl_lida_do_ambiente(monkeypatch):
    monkeypatch.setenv("SESSAO_TTL_HORAS", "24")
    importlib.reload(config)
    assert config.SESSAO_TTL_HORAS == 24


def test_sessao_ttl_invalida_usa_padrao(monkeypatch):
    monkeypatch.setenv("SESSAO_TTL_HORAS", "abc")
    importlib.reload(config)
    assert config.SESSAO_TTL_HORAS == 168


def test_primeiro_admin_telegram_id_lido_do_ambiente(monkeypatch):
    monkeypatch.setenv("PRIMEIRO_ADMIN_TELEGRAM_ID", "123456")
    importlib.reload(config)
    assert config.PRIMEIRO_ADMIN_TELEGRAM_ID == "123456"


def test_flags_booleanas_lidas_do_ambiente(monkeypatch):
    monkeypatch.setenv("AUDITORIA_ATIVA", "0")
    monkeypatch.setenv("API_ENABLED", "true")
    importlib.reload(config)
    assert config.AUDITORIA_ATIVA is False
    assert config.API_ENABLED is True


def test_telegram_webhook_secret_lido_do_ambiente(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "segredo-teste-ambiente")
    importlib.reload(config)
    assert config.TELEGRAM_WEBHOOK_SECRET == "segredo-teste-ambiente"


def test_telegram_webhook_secret_padrao_vazio():
    assert config.TELEGRAM_WEBHOOK_SECRET == ""


def test_cors_origens_lidas_do_ambiente(monkeypatch):
    monkeypatch.setenv(
        "API_CORS_ORIGINS",
        "https://app.exemplo.com, http://localhost:5173/, *",
    )
    importlib.reload(config)
    assert config.API_CORS_ORIGINS == (
        "https://app.exemplo.com",
        "http://localhost:5173",
    )


def test_cors_origens_wildcard_isolado_e_ignorado(monkeypatch):
    monkeypatch.setenv("API_CORS_ORIGINS", "*")
    importlib.reload(config)
    assert config.API_CORS_ORIGINS == ()


def test_variaveis_existentes_nao_removidas():
    for var in (
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "SPREADSHEET_URL",
        "GROQ_API_KEY",
        "JSON_KEY",
        "DATABASE_URL",
        "ESPELHAMENTO_PG_ATIVO",
        "WEBHOOK_URL_BASE",
        "TELEGRAM_WEBHOOK_SECRET",
        "MAPA_ISCAS_MASTER",
        "FILTROS_FIXOS",
    ):
        assert hasattr(config, var), var
