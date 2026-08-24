"""Testes da integração de produção do Bloco 5C.

Cobre a integração mínima e segura: flag ``ESPELHAMENTO_PG_ATIVO`` em config.py
(``config.bool_ambiente``), o orquestrador ``espelhar_mercado_se_ativo``
(espelhamento_mercado_5c.py) e o ponto de integração em ``app.py``
(executar_auditoria_carteira). Garantias testadas:

- flag false -> comportamento legado (somente Sheets, nenhum espelhamento);
- flag true  -> Sheets é gravado primeiro e o espelhamento roda depois;
- falha do PostgreSQL não desfaz/bloqueia o Sheets;
- execução repetida não duplica (idempotência);
- FIIs, Ações e inquilinos continuam funcionando pelo fluxo do Bloco 5C;
- Data Quality continua bloqueando INVALID e persistindo WARNING;
- a matriz do Sheets não é modificada pelo espelhamento.
"""
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

import app as app_module
import config
from pipeline_dados import espelhamento_mercado_5c as modulo_5c
from pipeline_dados.banco_dados import (
    Ativo,
    AtivoInquilino,
    Base,
    SnapshotAcao,
    SnapshotFii,
)
from pipeline_dados.espelhamento_mercado_5c import espelhar_mercado_se_ativo


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessao = sessionmaker(bind=engine)()
    yield sessao
    sessao.close()


def matriz_fiis():
    cabecalho = ["Ticker", "Tipo", "Setor", "Preço", "Cotas", "P/VP", "DY", "Vacância",
                 "Imóveis", "Inquilinos", "WALT", "Alavancagem", "Liquidez",
                 "Valor Mercado", "VPA", "Lucro 12M", "Div Mensal", "Carimbo"]
    linhas = [
        ["GARE11", "Tijolo", "Logística", 12.30, 200000000.0, 0.90, 0.10, 0.05, 3,
         "Inquilino A (50%), Inquilino B (50%)", "Pendente de IA", "Pendente de IA",
         800000.0, 2400000000.0, 13.67, 240000000.0, 0.1025, "19/08 10:00"],
        ["XPML11", "Tijolo", "Shoppings", 110.00, 100000000.0, 1.1, 0.08, 0.03, 5,
         "Magazine Luiza (12,3%), Via Varejo (8,5%)", "Pendente de IA", "Pendente de IA",
         5000000.0, 11000000000.0, 100.0, 880000000.0, 0.73, "19/08 10:00"],
        ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""],
    ]
    return [cabecalho] + linhas


def matriz_acoes():
    cabecalho = ["Ticker", "Setor", "Preço", "DY", "Qtd Ações", "P/L", "P/VP", "P/Ativo",
                 "Marg. Bruta", "Marg. EBIT", "Marg. Líq", "P/EBIT", "EV/EBIT",
                 "Dív/EBIT", "Dív/Patrim", "PSR", "P/Cap.Giro", "P/At.Circ.Liq",
                 "Liq. Corr", "ROE", "ROA", "ROIC", "Reservado", "Reservado",
                 "Reservado", "CAGR 5a", "Reservado", "Liq. Média", "VPA", "LPA",
                 "PEG", "Valor Mercado", "Carimbo"]
    linhas = [
        ["PETR4", "Petróleo, Gás & Biocombustíveis", 37.52, 0.14, 12300000000.0,
         4.5, 1.2, 0.8, 0.55, 0.30, 0.12, 8.0, 5.0, 0.5, 0.8, 0.9, 1.2, 1.1, 1.5,
         0.18, 0.12, 0.16, 0, 0, 0, 0.10, 0, 85000000.0, 31.0, 8.3, 1.1,
         400000000000.0, "19/08 10:00"],
        ["VALE3", "Materiais Básicos", 65.10, 0.11, 5100000000.0,
         6.0, 1.5, 1.0, 0.60, 0.40, 0.25, 9.0, 6.0, 0.7, 1.0, 1.1, 1.3, 1.2, 1.8,
         0.22, 0.15, 0.19, 0, 0, 0, 0.12, 0, 120000000.0, 44.0, 10.8, 1.4,
         600000000000.0, "19/08 10:00"],
        ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "",
         "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""],
    ]
    return [cabecalho] + linhas


# ==========================================
# FLAG E ORQUESTRADOR
# ==========================================

def test_bool_ambiente_interpreta_valores(monkeypatch):
    monkeypatch.setenv("FLAG_X", "TRUE")
    assert config.bool_ambiente("FLAG_X") is True
    monkeypatch.setenv("FLAG_X", "1")
    assert config.bool_ambiente("FLAG_X") is True
    monkeypatch.setenv("FLAG_X", "sim")
    assert config.bool_ambiente("FLAG_X") is True
    monkeypatch.setenv("FLAG_X", "0")
    assert config.bool_ambiente("FLAG_X") is False
    monkeypatch.delenv("FLAG_X", raising=False)
    assert config.bool_ambiente("FLAG_X") is False
    assert config.bool_ambiente("FLAG_X", padrao=True) is True


def test_flag_false_preserva_comportamento_legado(monkeypatch):
    monkeypatch.setattr(config, "ESPELHAMENTO_PG_ATIVO", False)
    chamadas = []
    monkeypatch.setattr(modulo_5c, "espelhar_mercado_fiis", lambda *a, **k: chamadas.append("fiis"))
    monkeypatch.setattr(modulo_5c, "espelhar_mercado_acoes", lambda *a, **k: chamadas.append("acoes"))
    assert espelhar_mercado_se_ativo(matriz_fiis=[["h"]], matriz_acoes=[["h"]]) is None
    assert chamadas == []


def test_flag_true_executa_espelhamento(monkeypatch):
    monkeypatch.setattr(config, "ESPELHAMENTO_PG_ATIVO", True)
    recebidas = {}

    def _fii(**kwargs):
        recebidas["fiis"] = kwargs
        return {"aba": "BD_FIIs", "linhas": 2, "criados": 2, "atualizados": 0,
                "invalidos": 0, "warnings": 0, "perfis_criados": 2, "perfis_atualizados": 0,
                "inquilinos_criados": 4, "inquilinos_atualizados": 0, "tickers": []}

    def _acao(**kwargs):
        recebidas["acoes"] = kwargs
        return {"aba": "BD_Acoes", "linhas": 2, "criados": 2, "atualizados": 0,
                "invalidos": 0, "warnings": 0, "perfis_criados": 2, "perfis_atualizados": 0,
                "inquilinos_criados": 0, "inquilinos_atualizados": 0, "tickers": []}

    monkeypatch.setattr(modulo_5c, "espelhar_mercado_fiis", _fii)
    monkeypatch.setattr(modulo_5c, "espelhar_mercado_acoes", _acao)
    resumo = espelhar_mercado_se_ativo(matriz_fiis=[["h"]], matriz_acoes=[["h"]])
    assert resumo is not None
    assert resumo["origem"] == "Google Sheets"
    assert resumo["fiis"]["criados"] == 2
    assert resumo["acoes"]["criados"] == 2
    assert recebidas["fiis"]["matriz"] == [["h"]]
    assert recebidas["acoes"]["matriz"] == [["h"]]


# ==========================================
# INTEGRAÇÃO NO APP.PY (SHEETS PRIMEIRO, PG DEPOIS)
# ==========================================

class _AbaFake:
    def __init__(self, eventos, nome):
        self.eventos = eventos
        self.nome = nome
        self._valores = [["h"]]

    def batch_update(self, updates):
        self.eventos.append(f"update_{self.nome}")

    def get_all_values(self):
        return self._valores


class _PlanilhaFake:
    def __init__(self, eventos):
        self.eventos = eventos
        self.abas = {
            "BD_FIIs": _AbaFake(eventos, "fiis"),
            "BD_Acoes": _AbaFake(eventos, "acoes"),
        }

    def worksheet(self, nome):
        return self.abas[nome]


class _GcFake:
    def __init__(self, planilha):
        self.planilha = planilha

    def open_by_url(self, url):
        return self.planilha


def _preparar_app(monkeypatch, planilha):
    monkeypatch.setattr(app_module, "conectar_gspread", lambda: _GcFake(planilha))
    monkeypatch.setattr(
        app_module,
        "rodar_garimpo_fiis",
        lambda *a, **k: ([["A1"]], "msg_fiis", planilha.abas["BD_FIIs"]),
    )
    monkeypatch.setattr(
        app_module,
        "rodar_garimpo_acoes",
        lambda *a, **k: ([["A1"]], "msg_acoes", planilha.abas["BD_Acoes"]),
    )
    monkeypatch.setattr(app_module, "disparar_alertas", lambda msg: None)


def test_sheets_atualizado_antes_do_pg(monkeypatch):
    eventos = []
    planilha = _PlanilhaFake(eventos)
    _preparar_app(monkeypatch, planilha)
    monkeypatch.setattr(app_module, "espelhar_mercado_se_ativo", lambda **k: eventos.append("mirror"))
    monkeypatch.setattr(config, "ESPELHAMENTO_PG_ATIVO", True)

    app_module.executar_auditoria_carteira()
    assert eventos == ["update_fiis", "update_acoes", "mirror"]


def test_falha_pg_nao_desfaz_sheets(monkeypatch):
    eventos = []
    planilha = _PlanilhaFake(eventos)
    _preparar_app(monkeypatch, planilha)

    def _mirror_falha(**kwargs):
        raise OperationalError("fail", None, "banco indisponível")

    monkeypatch.setattr(app_module, "espelhar_mercado_se_ativo", _mirror_falha)
    monkeypatch.setattr(config, "ESPELHAMENTO_PG_ATIVO", True)

    app_module.executar_auditoria_carteira()
    assert eventos == ["update_fiis", "update_acoes"]


def test_flag_false_no_app_nao_chama_espelhamento(monkeypatch):
    eventos = []
    planilha = _PlanilhaFake(eventos)
    _preparar_app(monkeypatch, planilha)
    monkeypatch.setattr(app_module, "espelhar_mercado_se_ativo", lambda **k: eventos.append("mirror"))
    monkeypatch.setattr(config, "ESPELHAMENTO_PG_ATIVO", False)

    app_module.executar_auditoria_carteira()
    assert eventos == ["update_fiis", "update_acoes"]


# ==========================================
# FLUXO REAL PELO ORQUESTRADOR
# ==========================================

def test_execucao_repetida_nao_duplica(db_session, monkeypatch):
    monkeypatch.setattr(config, "ESPELHAMENTO_PG_ATIVO", True)
    espelhar_mercado_se_ativo(matriz_fiis=matriz_fiis(), matriz_acoes=matriz_acoes(), session=db_session)
    espelhar_mercado_se_ativo(matriz_fiis=matriz_fiis(), matriz_acoes=matriz_acoes(), session=db_session)
    assert db_session.query(SnapshotFii).count() == 2
    assert db_session.query(SnapshotAcao).count() == 2
    assert db_session.query(AtivoInquilino).count() == 4


def test_fiis_acoes_inquilinos_persistidos(db_session, monkeypatch):
    monkeypatch.setattr(config, "ESPELHAMENTO_PG_ATIVO", True)
    espelhar_mercado_se_ativo(matriz_fiis=matriz_fiis(), matriz_acoes=matriz_acoes(), session=db_session)

    snap_fii = db_session.query(SnapshotFii).join(Ativo).filter(Ativo.ticker == "GARE11").one()
    assert snap_fii.preco == Decimal("12.30")
    assert snap_fii.dy == Decimal("0.10")

    snap_acao = db_session.query(SnapshotAcao).join(Ativo).filter(Ativo.ticker == "PETR4").one()
    assert snap_acao.preco == Decimal("37.52")

    inquilinos = db_session.query(AtivoInquilino).join(Ativo).filter(Ativo.ticker == "XPML11").all()
    assert {i.nome for i in inquilinos} == {"Magazine Luiza", "Via Varejo"}


def test_data_quality_bloqueia_invalid(db_session, monkeypatch):
    monkeypatch.setattr(config, "ESPELHAMENTO_PG_ATIVO", True)
    matriz = matriz_fiis()
    matriz.append(["HGCR11", "Papel", "CRI", -1.00, 0, 1.5, 0.12, 0.0, 0,
                   "Não informado", "Pendente de IA", "Pendente de IA", 1000.0,
                   1000000000.0, 1.0, 120000000.0, 0.01, "19/08 10:00"])
    resumo = espelhar_mercado_se_ativo(matriz_fiis=matriz, matriz_acoes=matriz_acoes(), session=db_session)
    assert resumo["fiis"]["invalidos"] == 1
    hgcr = db_session.query(Ativo).filter_by(ticker="HGCR11").first()
    assert hgcr is not None
    assert db_session.query(SnapshotFii).filter_by(ativo_id=hgcr.id).count() == 0


def test_data_quality_warning_persiste(db_session, monkeypatch):
    monkeypatch.setattr(config, "ESPELHAMENTO_PG_ATIVO", True)
    matriz = matriz_fiis()
    matriz.append(["BTLG11", "Tijolo", "Logística", 40.0, 0, 0.8, 0.09, 0.02, 2.5,
                   "Não informado", "Pendente de IA", "Pendente de IA", 500000.0,
                   2000000000.0, 50.0, 180000000.0, 0.30, "19/08 10:00"])
    resumo = espelhar_mercado_se_ativo(matriz_fiis=matriz, matriz_acoes=matriz_acoes(), session=db_session)
    assert resumo["fiis"]["warnings"] == 1
    assert db_session.query(SnapshotFii).join(Ativo).filter(Ativo.ticker == "BTLG11").count() == 1


def test_matriz_nao_e_modificada_pelo_espelhamento(db_session, monkeypatch):
    monkeypatch.setattr(config, "ESPELHAMENTO_PG_ATIVO", True)
    m_fiis = matriz_fiis()
    m_acoes = matriz_acoes()
    copia_fiis = [list(l) for l in m_fiis]
    copia_acoes = [list(l) for l in m_acoes]
    espelhar_mercado_se_ativo(matriz_fiis=m_fiis, matriz_acoes=m_acoes, session=db_session)
    assert m_fiis == copia_fiis
    assert m_acoes == copia_acoes
