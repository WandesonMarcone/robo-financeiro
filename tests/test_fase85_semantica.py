"""Fase 8.5: ZERO / AUSENTE / N/A / INVALIDO / PRESENTE; FII vs acao."""
from pipeline_dados.banco_dados import TipoAtivo
from pipeline_dados.regras_indicadores import classificar_indicador, obter_regra
from pipeline_dados.semantica_indicadores import (
    AUSENTE,
    FRACAO,
    INVALIDO,
    NAO_APLICAVEL,
    PRESENTE,
    UNIDADE_PCT,
    UNIDADE_X,
    ZERO,
    classificar_semantica,
    eh_nao_aplicavel,
    escala_do_indicador,
    indicador_aplicavel,
    indicadores_pendentes,
    interpretar_valor,
    tipo_canonico,
    unidade_do_indicador,
)
from services.mercado import interpretar_indicador, obter_snapshots, obter_universo


def test_zero_real_nao_e_ausencia():
    assert classificar_semantica(0) == ZERO
    assert classificar_semantica(0.0) == ZERO
    assert classificar_semantica("0") == ZERO
    interpretacao = interpretar_valor("FII", "dy", 0.0)
    assert interpretacao["semantica"] == ZERO
    assert interpretacao["valor_numerico"] == 0.0


def test_ausente_e_null_nao_vira_zero():
    for valor in (None, "", "   ", "-"):
        assert classificar_semantica(valor) == AUSENTE, valor
        interpretacao = interpretar_valor("ACAO", "roe", valor)
        assert interpretacao["semantica"] == AUSENTE, valor
        assert interpretacao["valor_numerico"] is None, valor


def test_na_explicito_nao_e_vazio_nem_zero():
    assert eh_nao_aplicavel("N/A") is True
    assert eh_nao_aplicavel("n/a") is True
    assert eh_nao_aplicavel("nao aplicavel") is True
    assert eh_nao_aplicavel("-") is False
    assert eh_nao_aplicavel("") is False
    assert eh_nao_aplicavel(None) is False
    interpretacao = interpretar_valor("ACAO", "roe", "N/A")
    assert interpretacao["semantica"] == NAO_APLICAVEL
    assert interpretacao["valor_numerico"] is None


def test_invalido_nao_vira_zero():
    for valor in ("abc", "erro_de_coleta", float("nan"), float("inf")):
        assert classificar_semantica(valor) == INVALIDO, valor
        interpretacao = interpretar_valor("ACAO", "pl", valor)
        assert interpretacao["semantica"] == INVALIDO, valor
        assert interpretacao["valor_numerico"] is None, valor


def test_presente_preserva_numero():
    interpretacao = interpretar_valor("ACAO", "roe", 0.20)
    assert interpretacao["semantica"] == PRESENTE
    assert interpretacao["valor_numerico"] == 0.20
    assert interpretacao["escala"] == FRACAO
    assert interpretacao["unidade"] == UNIDADE_PCT


def test_indicador_de_acao_em_fii_e_na():
    assert indicador_aplicavel("FII", "roe") is False
    assert indicador_aplicavel("FII", "pl") is False
    assert indicador_aplicavel("FII", "roa") is False
    interpretacao = interpretar_valor("FII", "roe", 0.20)
    assert interpretacao["semantica"] == NAO_APLICAVEL
    assert interpretacao["valor_numerico"] is None
    assert interpretacao["aplicavel"] is False
    resultado = classificar_indicador("FII", "roe", 0.20)
    assert resultado["severidade"] == "IGNORADO"
    assert resultado["regra"] == "NAO_APLICAVEL"
    assert resultado["semantica"] == NAO_APLICAVEL


def test_indicador_de_fii_em_acao_e_na():
    assert indicador_aplicavel("ACAO", "qtd_imoveis") is False
    assert indicador_aplicavel("ACAO", "liquidez") is False
    interpretacao = interpretar_valor("ACAO", "qtd_imoveis", 12)
    assert interpretacao["semantica"] == NAO_APLICAVEL
    assert interpretacao["valor_numerico"] is None


def test_indicadores_compartilhados_aplicam_aos_dois():
    for indicador in ("preco", "dy", "pvp", "vpa"):
        assert indicador_aplicavel("FII", indicador)
        assert indicador_aplicavel("ACAO", indicador)


def test_classificar_indicador_distingue_ausente_invalido_na():
    ausente = classificar_indicador("ACAO", "roe", None)
    assert ausente["regra"] == "VALOR_AUSENTE"
    assert ausente["semantica"] == AUSENTE
    invalido = classificar_indicador("ACAO", "roe", "abc")
    assert invalido["regra"] == "VALOR_INVALIDO"
    assert invalido["semantica"] == INVALIDO
    na = classificar_indicador("ACAO", "roe", "N/A")
    assert na["regra"] == "NAO_APLICAVEL"
    assert na["semantica"] == NAO_APLICAVEL
    zero = classificar_indicador("FII", "liquidez", 0)
    assert zero["semantica"] == ZERO
    assert zero["severidade"] != "IGNORADO"


def test_servico_mercado_expoe_semantica_sem_inventar():
    dados = interpretar_indicador("ACAO", "roa", 0.08)
    assert dados["semantica"] == PRESENTE
    assert dados["valor_numerico"] == 0.08
    assert dados["unidade"] == UNIDADE_PCT
    vazio = interpretar_indicador("ACAO", "roa", None)
    assert vazio["semantica"] == AUSENTE
    assert vazio["valor_numerico"] is None


def test_div_liq_ebit_permanece_pendente():
    assert "div_liq_ebit" in indicadores_pendentes()
    definicao_ok = unidade_do_indicador("div_liq_ebit", "ACAO")
    assert definicao_ok == UNIDADE_X
    assert escala_do_indicador("div_liq_ebit") == "multiplo"


def test_percentual_explicito_e_zero_percentual():
    assert classificar_semantica("12,5%") == PRESENTE
    interpretacao = interpretar_valor("ACAO", "roe", "20%")
    assert interpretacao["semantica"] == PRESENTE
    assert interpretacao["valor_numerico"] == 0.20
    zero_pct = interpretar_valor("ACAO", "dy", "0%")
    assert zero_pct["semantica"] == ZERO
    assert zero_pct["valor_numerico"] == 0.0


def test_tipo_ativo_enum_nao_inventa_na_nem_zero():
    assert tipo_canonico(TipoAtivo.ACAO) == "ACAO"
    assert tipo_canonico(TipoAtivo.FII) == "FII"
    assert indicador_aplicavel(TipoAtivo.ACAO, "roe") is True
    assert indicador_aplicavel(TipoAtivo.FII, "roe") is False
    assert obter_regra(TipoAtivo.ACAO, "roe") is not None
    interpretacao = interpretar_valor(TipoAtivo.FII, "pl", 8.0)
    assert interpretacao["semantica"] == NAO_APLICAVEL
    assert interpretacao["valor_numerico"] is None
    assert interpretacao["tipo"] == "FII"


def test_servico_mercado_contrato_publico_inalterado():
    assert callable(obter_snapshots)
    assert callable(obter_universo)
    vazio = interpretar_indicador(TipoAtivo.ACAO, "peg_ratio", None)
    assert vazio["semantica"] == AUSENTE
    assert vazio["valor_numerico"] is None
