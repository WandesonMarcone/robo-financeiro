"""Testes do catálogo de regras por indicador — Fase 4 (aditivo).

Cobre: regras por tipo de ativo; negativo legítimo vs impossível vs suspeito;
zero; faixas de plausibilidade (WARNING/CRITICO); valor ausente/ilegível;
indicador sem regra; classificação puramente diagnóstica (não altera o valor).
"""
from pipeline_dados.regras_indicadores import (
    CRITICO,
    ERRO,
    OK,
    WARNING,
    classificar_indicador,
    obter_regra,
)


def test_obter_regra_por_tipo():
    regra = obter_regra("FII", "preco")
    assert regra is not None
    assert regra.classificacao_negativo == ERRO
    assert obter_regra("ACAO", "preco").limite_variacao_pct == 0.10
    assert obter_regra("ACAO", "dy").limite_variacao_critica_pct == 0.50
    assert obter_regra("FII", "indicador_inexistente") is None
    assert obter_regra("OUTRO_TIPO", "preco") is None


def test_preco_negativo_e_erro_para_fii_e_acao():
    for tipo in ("FII", "ACAO"):
        resultado = classificar_indicador(tipo, "preco", -1.0)
        assert resultado["severidade"] == ERRO, tipo
        assert resultado["regra"] == "VALOR_NEGATIVO_IMPOSSIVEL"


def test_qtd_imoveis_negativo_e_erro():
    resultado = classificar_indicador("FII", "qtd_imoveis", -3)
    assert resultado["severidade"] == ERRO
    assert resultado["regra"] == "VALOR_NEGATIVO_IMPOSSIVEL"


def test_negativo_legitimo_e_ok():
    for indicador in (
        "roe", "roa", "roic", "marg_bruta", "marg_ebit", "marg_liquida",
        "div_liq_patrimonio", "cagr_rec_5a", "lpa",
    ):
        resultado = classificar_indicador("ACAO", indicador, -0.10)
        assert resultado["severidade"] == OK, indicador
        assert resultado["regra"] == "VALOR_NEGATIVO_LEGITIMO"
        assert resultado["motivo"]


def test_negativo_suspeito_e_warning():
    for indicador in ("dy", "pvp", "pl", "vpa", "valor_mercado"):
        resultado = classificar_indicador("ACAO", indicador, -0.5)
        assert resultado["severidade"] == WARNING, indicador
        assert resultado["regra"] == "VALOR_NEGATIVO_SUSPEITO"


def test_negativo_suspeito_e_warning_para_fii():
    for indicador in ("pvp", "dy", "liquidez", "vpa", "lucro_12m", "dividendo_mensal"):
        resultado = classificar_indicador("FII", indicador, -0.5)
        assert resultado["severidade"] == WARNING, indicador
        assert resultado["regra"] == "VALOR_NEGATIVO_SUSPEITO"


def test_valor_zero_suspeito_quando_nao_aceito():
    resultado = classificar_indicador("FII", "preco", 0)
    assert resultado["severidade"] == WARNING
    assert resultado["regra"] == "VALOR_ZERO_SUSPEITO"


def test_valor_zero_ok_quando_aceito():
    assert classificar_indicador("FII", "liquidez", 0)["severidade"] == OK


def test_valor_fora_da_faixa_gera_warning():
    resultado = classificar_indicador("FII", "dy", 0.30)
    assert resultado["severidade"] == WARNING
    assert resultado["regra"] == "FORA_FAIXA"


def test_valor_fora_da_faixa_critica_gera_critico():
    resultado = classificar_indicador("FII", "dy", 0.80)
    assert resultado["severidade"] == CRITICO
    assert resultado["regra"] == "FORA_FAIXA_CRITICA"


def test_valor_ausente_ou_ilegivel_ignorado():
    for valor in (None, "abc", "", "N/A"):
        resultado = classificar_indicador("FII", "preco", valor)
        assert resultado["severidade"] == "IGNORADO", valor
        assert resultado["regra"] == "VALOR_AUSENTE"


def test_indicador_sem_regra_e_ok():
    resultado = classificar_indicador("FII", "nao_monitorado", 5.0)
    assert resultado["severidade"] == OK
    assert resultado["regra"] == "SEM_REGRA"


def test_valores_dentro_da_faixa_e_ok():
    for tipo, indicador, valor in (
        ("FII", "preco", 9.87),
        ("FII", "pvp", 0.95),
        ("FII", "dy", 0.12),
        ("FII", "vpa", 10.39),
        ("ACAO", "pl", 8.0),
        ("ACAO", "roe", 0.20),
        ("ACAO", "liq_corrente", 1.5),
    ):
        assert classificar_indicador(tipo, indicador, valor)["severidade"] == OK


def test_classificacao_nao_altera_valor_original():
    valor = -1.0
    classificar_indicador("FII", "preco", valor)
    assert valor == -1.0


def test_motivo_e_nome_exibicao_presentes():
    resultado = classificar_indicador("FII", "pvp", 0.95)
    assert resultado["nome_exibicao"] == "P/VP"
    assert resultado["motivo"]
