"""Fase 8.5: escala/unidade canonica; % vira fracao; sem heuristica."""
import pandas as pd

from modules.scraper_acoes import LIMIAR_ROE_OPORTUNIDADE, limpar_porcentagem_df
from pipeline_dados.mapeamento_sheets import parsear_valor_market
from pipeline_dados.regras_indicadores import CRITICO, classificar_indicador
from pipeline_dados.semantica_indicadores import (
    CATALOGO,
    FRACAO,
    MONETARIO,
    MULTIPLO,
    QUANTIDADE,
    RAZAO,
    UNIDADE_BRL,
    UNIDADE_PCT,
    UNIDADE_UN,
    UNIDADE_X,
    escala_do_indicador,
    interpretar_valor,
    unidade_do_indicador,
)


def test_percentuais_persistidos_sao_fracao():
    for indicador in (
        "dy", "roe", "roa", "roic", "marg_bruta", "marg_ebit",
        "marg_liquida", "cagr_rec_5a", "cagr_lucro_5a",
    ):
        assert escala_do_indicador(indicador) == FRACAO, indicador
        assert unidade_do_indicador(indicador) == UNIDADE_PCT, indicador


def test_multiplos_sao_x():
    for indicador in ("pl", "pvp", "p_ebit", "ev_ebit", "psr", "peg_ratio"):
        assert escala_do_indicador(indicador) == MULTIPLO, indicador
        assert unidade_do_indicador(indicador) == UNIDADE_X, indicador


def test_monetarios_sao_reais():
    for indicador in ("preco", "vpa", "lpa", "valor_mercado", "liq_media"):
        assert escala_do_indicador(indicador) == MONETARIO, indicador
        assert unidade_do_indicador(indicador) == UNIDADE_BRL, indicador


def test_parsear_valor_market_percentual_vira_fracao():
    assert parsear_valor_market("11,5%") == 0.115
    assert parsear_valor_market("12,5%") == 0.125
    assert parsear_valor_market("0%") == 0.0
    assert parsear_valor_market("8,0%") == 0.08


def test_parsear_valor_market_sem_percentual_nao_converte_escala():
    assert parsear_valor_market(12.0) == 12.0
    assert parsear_valor_market("12.0") == 12.0
    assert parsear_valor_market("12,0") == 12.0
    assert parsear_valor_market("R$ 1.234,56") == 1234.56


def test_doze_sem_percentual_nao_vira_fracao_por_heuristica():
    interpretacao = interpretar_valor("ACAO", "roe", 12.0)
    assert interpretacao["valor_numerico"] == 12.0
    assert interpretacao["escala"] == FRACAO
    resultado = classificar_indicador("ACAO", "roe", 12.0)
    assert resultado["severidade"] == CRITICO
    assert resultado["regra"] == "FORA_FAIXA_CRITICA"


def test_roa_roe_margens_em_fracao_sao_ok():
    for indicador, valor in (
        ("roe", 0.20),
        ("roa", 0.08),
        ("roic", 0.16),
        ("marg_bruta", 0.55),
        ("marg_ebit", 0.30),
        ("marg_liquida", 0.12),
        ("dy", 0.06),
    ):
        resultado = classificar_indicador("ACAO", indicador, valor)
        assert resultado["severidade"] == "OK", indicador
        dados = interpretar_valor("ACAO", indicador, valor)
        assert dados["valor_numerico"] == valor
        assert dados["escala"] == FRACAO


def test_filtro_roe_oportunidade_usa_fracao():
    assert LIMIAR_ROE_OPORTUNIDADE == 0.08
    df = pd.DataFrame(
        {"P/L": [8.0, 8.0], "P/VP": [1.0, 1.0], "ROE": [0.09, 0.07]},
        index=["AAAA3", "BBBB3"],
    )
    aprovadas = df[df["ROE"] >= LIMIAR_ROE_OPORTUNIDADE].index.tolist()
    assert aprovadas == ["AAAA3"]
    com_limiar_errado = df[df["ROE"] >= 8.0].index.tolist()
    assert com_limiar_errado == []


def test_catalogo_cobre_indicadores_persistidos():
    for indicador in ("preco", "dy", "pvp", "pl", "roe", "roa", "lpa"):
        assert indicador in CATALOGO


def test_limpar_porcentagem_df_so_converte_com_simbolo():
    assert limpar_porcentagem_df("8,0%") == 0.08
    assert limpar_porcentagem_df("0%") == 0.0
    assert limpar_porcentagem_df(12.0) == 12.0
    assert limpar_porcentagem_df("12,0") == 12.0
    assert limpar_porcentagem_df(None) is None


def test_razoes_quantidades_e_divida():
    assert escala_do_indicador("liq_corrente") == RAZAO
    assert unidade_do_indicador("liq_corrente") == UNIDADE_X
    assert escala_do_indicador("div_liq_patrimonio") == RAZAO
    assert unidade_do_indicador("div_liq_patrimonio") == UNIDADE_X
    assert escala_do_indicador("qtd_imoveis") == QUANTIDADE
    assert unidade_do_indicador("qtd_imoveis") == UNIDADE_UN
    for indicador, valor in (
        ("peg_ratio", 1.1),
        ("ev_ebit", 5.0),
        ("p_ebit", 8.0),
        ("div_liq_patrimonio", 0.8),
        ("pl", 4.5),
        ("pvp", 1.2),
    ):
        dados = interpretar_valor("ACAO", indicador, valor)
        assert dados["valor_numerico"] == valor, indicador
        assert dados["escala"] == escala_do_indicador(indicador)
        assert classificar_indicador("ACAO", indicador, valor)["severidade"] == "OK"


def test_ev_ebitda_nao_existe_no_catalogo():
    assert "ev_ebitda" not in CATALOGO
    assert "ev_ebit" in CATALOGO
    assert "walt" not in CATALOGO
    assert "alavancagem" not in CATALOGO
