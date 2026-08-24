"""Testes do espelhamento de inquilinos de FIIs -> ativos_inquilinos (Bloco 5C).

Cobre: parser determinístico da coluna J do BD_FIIs (formato real produzido por
``buscar_dados_profundos_fii``: itens separados por ", ", cada um
"nome (percentual)"), participação convertida para fração Decimal, nome sem
participação, múltiplos inquilinos, espaços extras, formato inválido/sentinela
não gerando registro falso, idempotência por (ativo_id, nome, data_referencia),
nova linha em data diferente, dois inquilinos no mesmo ativo, ativo inexistente
sendo criado, Google Sheets intocado e ausência de PostgreSQL propagando erro.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from pipeline_dados import espelhamento_mercado_5c as modulo_5c
from pipeline_dados.banco_dados import (
    Ativo,
    AtivoInquilino,
    Base,
    TipoAtivo,
)
from pipeline_dados.espelhamento_mercado_5c import espelhar_mercado_fiis, parsear_inquilinos


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


def _inquilinos_por_ativo(session, ticker):
    return (
        session.query(AtivoInquilino)
        .join(Ativo)
        .filter(Ativo.ticker == ticker)
        .order_by(AtivoInquilino.nome)
        .all()
    )


# ==========================================
# PARSER DETERMINÍSTICO
# ==========================================

def test_parseia_formato_real_do_scraper():
    inquilinos = parsear_inquilinos("Magazine Luiza (12,3%), Via Varejo (8,5%)")
    assert [i["nome"] for i in inquilinos] == ["Magazine Luiza", "Via Varejo"]
    assert inquilinos[0]["participacao"] == Decimal("0.123")
    assert inquilinos[1]["participacao"] == Decimal("0.085")


def test_parseia_nome_com_participacao():
    assert parsear_inquilinos("Banco do Brasil (15,5%)") == [
        {"nome": "Banco do Brasil", "participacao": Decimal("0.155")}
    ]


def test_nome_sem_participacao_fica_null():
    assert parsear_inquilinos("Empresa X") == [
        {"nome": "Empresa X", "participacao": None}
    ]


def test_multiplos_inquilinos():
    inquilinos = parsear_inquilinos("Inquilino A (10%), Inquilino B (20%), Inquilino C (70%)")
    assert [i["nome"] for i in inquilinos] == ["Inquilino A", "Inquilino B", "Inquilino C"]
    assert [i["participacao"] for i in inquilinos] == [
        Decimal("0.1"),
        Decimal("0.2"),
        Decimal("0.7"),
    ]


def test_espacos_extras_sao_normalizados():
    inquilinos = parsear_inquilinos(
        "  Magazine   Luiza  ( 12,3% ) ,   Via Varejo  (8,5%)  "
    )
    assert [i["nome"] for i in inquilinos] == ["Magazine Luiza", "Via Varejo"]
    assert inquilinos[0]["participacao"] == Decimal("0.123")
    assert inquilinos[1]["participacao"] == Decimal("0.085")


def test_participacao_convertida_para_valor_numerico():
    assert parsear_inquilinos("A (12,3%)")[0]["participacao"] == Decimal("0.123")
    assert parsear_inquilinos("B (8.5%)")[0]["participacao"] == Decimal("0.085")
    assert parsear_inquilinos("C (0,5)")[0]["participacao"] == Decimal("0.5")


def test_formato_invalido_nao_gera_registro_falso():
    assert parsear_inquilinos("###") == []
    assert parsear_inquilinos("()") == []
    assert parsear_inquilinos("12,3%") == []
    assert parsear_inquilinos("-") == []


def test_sentinela_nao_gera_inquilino(db_session):
    matriz = matriz_fiis()
    matriz.append(["BTLG11", "Tijolo", "Logística", 40.0, 0, 0.8, 0.09, 0.02, 2,
                   "Não informado / Não aplicável", "Pendente de IA", "Pendente de IA",
                   500000.0, 2000000000.0, 50.0, 180000000.0, 0.30, "19/08 10:00"])
    rel = espelhar_mercado_fiis(db_session, matriz, data_referencia=date(2026, 8, 20))
    assert rel["inquilinos_criados"] == 4
    btlg = db_session.query(Ativo).filter_by(ticker="BTLG11").one()
    assert db_session.query(AtivoInquilino).filter_by(ativo_id=btlg.id).count() == 0


# ==========================================
# PERSISTÊNCIA / IDEMPOTÊNCIA
# ==========================================

def test_primeira_execucao_persiste_inquilinos(db_session):
    rel = espelhar_mercado_fiis(db_session, matriz_fiis(), data_referencia=date(2026, 8, 20))
    assert rel["inquilinos_criados"] == 4
    assert rel["inquilinos_atualizados"] == 0
    assert db_session.query(AtivoInquilino).count() == 4


def test_segunda_execucao_nao_duplica(db_session):
    espelhar_mercado_fiis(db_session, matriz_fiis(), data_referencia=date(2026, 8, 20))
    rel = espelhar_mercado_fiis(db_session, matriz_fiis(), data_referencia=date(2026, 8, 20))
    assert rel["inquilinos_criados"] == 0
    assert rel["inquilinos_atualizados"] == 4
    assert db_session.query(AtivoInquilino).count() == 4


def test_outra_data_cria_novo_snapshot(db_session):
    espelhar_mercado_fiis(db_session, matriz_fiis(), data_referencia=date(2026, 8, 19))
    rel = espelhar_mercado_fiis(db_session, matriz_fiis(), data_referencia=date(2026, 8, 20))
    assert rel["inquilinos_criados"] == 4
    assert db_session.query(AtivoInquilino).count() == 8


def test_dois_inquilinos_no_mesmo_ativo_nao_colidem(db_session):
    espelhar_mercado_fiis(db_session, matriz_fiis(), data_referencia=date(2026, 8, 20))
    registros = _inquilinos_por_ativo(db_session, "GARE11")
    assert [r.nome for r in registros] == ["Inquilino A", "Inquilino B"]
    assert {r.data_referencia for r in registros} == {date(2026, 8, 20)}


def test_nome_vazio_nao_persiste(db_session):
    matriz = matriz_fiis()
    matriz.append(["BTLG11", "Tijolo", "Logística", 40.0, 0, 0.8, 0.09, 0.02, 2,
                   "   ", "Pendente de IA", "Pendente de IA", 500000.0,
                   2000000000.0, 50.0, 180000000.0, 0.30, "19/08 10:00"])
    rel = espelhar_mercado_fiis(db_session, matriz, data_referencia=date(2026, 8, 20))
    assert rel["inquilinos_criados"] == 4
    btlg = db_session.query(Ativo).filter_by(ticker="BTLG11").one()
    assert db_session.query(AtivoInquilino).filter_by(ativo_id=btlg.id).count() == 0


def test_participacao_null_quando_ausente(db_session):
    matriz = matriz_fiis()
    matriz.append(["MALL11", "Tijolo", "Shoppings", 90.00, 0, 1.0, 0.09, 0.02, 4,
                   "Shopping Iguatemi", "Pendente de IA", "Pendente de IA",
                   3000000.0, 9000000000.0, 90.0, 810000000.0, 0.675, "19/08 10:00"])
    espelhar_mercado_fiis(db_session, matriz, data_referencia=date(2026, 8, 20))
    registro = db_session.query(AtivoInquilino).join(Ativo).filter(Ativo.ticker == "MALL11").one()
    assert registro.nome == "Shopping Iguatemi"
    assert registro.participacao is None
    assert registro.data_referencia == date(2026, 8, 20)
    assert registro.data_coleta is not None


def test_participacao_persistida_como_decimal(db_session):
    espelhar_mercado_fiis(db_session, matriz_fiis(), data_referencia=date(2026, 8, 20))
    registros = _inquilinos_por_ativo(db_session, "XPML11")
    assert [r.nome for r in registros] == ["Magazine Luiza", "Via Varejo"]
    assert registros[0].participacao == Decimal("0.123")
    assert registros[1].participacao == Decimal("0.085")


# ==========================================
# FLUXO GERAL / GARANTIAS
# ==========================================

def test_ativo_inexistente_e_criado_no_fluxo(db_session):
    matriz = matriz_fiis()
    matriz.append(["MALL11", "Tijolo", "Shoppings", 90.00, 0, 1.0, 0.09, 0.02, 4,
                   "Shopping Iguatemi (12,5%)", "Pendente de IA", "Pendente de IA",
                   3000000.0, 9000000000.0, 90.0, 810000000.0, 0.675, "19/08 10:00"])
    espelhar_mercado_fiis(db_session, matriz, data_referencia=date(2026, 8, 20))
    ativo = db_session.query(Ativo).filter_by(ticker="MALL11").one()
    assert ativo.tipo == TipoAtivo.FII
    assert db_session.query(AtivoInquilino).filter_by(ativo_id=ativo.id).count() == 1


def test_matriz_de_entrada_nao_e_alterada(db_session):
    matriz = matriz_fiis()
    copia = [list(linha) for linha in matriz]
    espelhar_mercado_fiis(db_session, matriz, data_referencia=date(2026, 8, 20))
    assert matriz == copia


def test_sem_postgres_erro_nao_e_mascarado(monkeypatch):
    def _falhar():
        raise OperationalError("fail", None, "banco indisponível")

    monkeypatch.setattr(modulo_5c, "_criar_sessao", _falhar)
    matriz = matriz_fiis()
    with pytest.raises(OperationalError):
        espelhar_mercado_fiis(matriz=matriz, data_referencia=date(2026, 8, 20))
    assert matriz[1][0] == "GARE11"
