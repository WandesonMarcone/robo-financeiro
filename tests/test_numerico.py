"""Testes da camada de coerção numérica centralizada (Fase 7, Etapa 7.5).

Cobrem ``pipeline_dados.numerico`` — a abstração única de conversão numérica
que substitui ``modules.utils.formatar`` e ``services.dashboard_menus.converter_numero``
(auditoria 7.1, item 4.1). Garantia central: ERRO de parsing/coleta NUNCA vira
``0.0``; valor ausente, inválido, zero legítimo e erro de coleta são distinguíveis.
"""
from pipeline_dados import numerico
from pipeline_dados.numerico import (
    NAO_FINITO,
    NAO_NUMERO,
    campo_numerico,
    coerir_numero,
    derivar_divisao,
    derivar_produto,
    parsear_numero,
    parsear_percentual,
    primeiro_numero,
)

# ==========================================
# NÚMEROS INTEIROS E DECIMAIS
# ==========================================

def test_inteiro_preservado():
    assert parsear_numero(5) == 5.0
    assert parsear_numero("5") == 5.0


def test_decimal_preservado():
    assert parsear_numero(5.5) == 5.5
    assert parsear_numero("5.5") == 5.5


def test_negativos_aceitos():
    assert parsear_numero("-3") == -3.0
    assert parsear_numero(-2.75) == -2.75


def test_cientifico_aceito():
    assert parsear_numero("1e3") == 1000.0


# ==========================================
# SEPARADORES BRASILEIROS E INTERNACIONAIS
# ==========================================

def test_separador_brasileiro_milhar_e_decimal():
    assert parsear_numero("1.234,56") == 1234.56


def test_separador_internacional():
    assert parsear_numero("1234.56") == 1234.56


def test_virgula_decimal_sem_milhar():
    assert parsear_numero("12,5") == 12.5


def test_separador_brasileiro_so_milhar():
    # Ponto único é tratado como decimal (formato internacional): "1.000" = 1.0.
    # Milhar brasileiro só é interpretado no formato misto ("1.234,56").
    assert parsear_numero("1.000") == 1.0


# ==========================================
# VALORES NULOS / AUSENTES
# ==========================================

def test_none_e_ausente():
    assert parsear_numero(None) is None


def test_string_vazia_e_ausente():
    assert parsear_numero("") is None
    assert parsear_numero("   ") is None


def test_ausente_retorna_motivo_none():
    assert coerir_numero(None) == (None, None)
    assert coerir_numero("") == (None, None)


# ==========================================
# VALORES INVÁLIDOS
# ==========================================

def test_texto_nao_numerico_invalido():
    assert parsear_numero("abc") is None
    assert coerir_numero("abc") == (None, NAO_NUMERO)


def test_bool_nao_e_numero():
    assert parsear_numero(True) is None
    assert coerir_numero(True) == (None, NAO_NUMERO)


def test_nan_e_inf_sao_invalidos_nao_ausentes():
    assert parsear_numero(float("nan")) is None
    assert parsear_numero(float("inf")) is None
    assert coerir_numero(float("nan")) == (None, NAO_FINITO)
    assert coerir_numero(float("inf")) == (None, NAO_FINITO)


# ==========================================
# ZERO LEGÍTIMO
# ==========================================

def test_zero_legitimo_e_preservado():
    assert parsear_numero(0) == 0.0
    assert parsear_numero("0") == 0.0
    assert parsear_numero(0.0) == 0.0


def test_zero_legitimo_motivo_none():
    assert coerir_numero(0) == (0.0, None)
    assert coerir_numero("0") == (0.0, None)


# ==========================================
# ERRO DE COLETA NUNCA VIRA 0.0
# ==========================================

def test_erro_de_parsing_nao_vira_zero():
    # Padrões que o legado (formatar/converter_numero) transformava em 0.0.
    for valor in ["abc", "R$ 1,50", "--", "12x", "%%%", "1.2.3", {"a": 1}, [1, 2]]:
        assert parsear_numero(valor) is None, f"{valor!r} deveria ser None, nunca 0.0"
        assert parsear_numero(valor) != 0.0


def test_coerir_numero_distinguir_toda_semantica():
    # zero legítimo / ausente / inválido / não finito são distinguíveis.
    assert coerir_numero("0") == (0.0, None)
    assert coerir_numero(None) == (None, None)
    assert coerir_numero("nao-numero") == (None, NAO_NUMERO)
    assert coerir_numero(float("inf")) == (None, NAO_FINITO)


def test_numerico_nao_exporta_formatar_legado():
    # A nova camada não expõe o mascaramento do legado (erro -> 0.0).
    assert not hasattr(numerico, "formatar")
    assert not hasattr(numerico, "converter_numero")


def test_qualidade_dados_reexporta_o_mesmo_parsear_numero():
    # A camada de validação delega para a abstração única (mesma função).
    from pipeline_dados.qualidade_dados import parsear_numero as qd_parsear

    assert qd_parsear is parsear_numero


# ==========================================
# HELPERS 8.2: PERCENTUAL / CAMPO / DERIVAÇÃO
# ==========================================

def test_parsear_percentual_zero_real_e_ausencia():
    assert parsear_percentual("0%") == 0.0
    assert parsear_percentual(0) == 0.0
    assert parsear_percentual("12,5%") == 0.125
    assert parsear_percentual("") is None
    assert parsear_percentual(None) is None
    assert parsear_percentual("   ") is None
    assert parsear_percentual("abc%") is None


def test_campo_numerico_nao_usa_default_zero():
    assert campo_numerico(None, "preco") is None
    assert campo_numerico({}, "preco") is None
    assert campo_numerico({"preco": 0}, "preco") == 0.0
    assert campo_numerico({"dy": "0%"}, "dy", percentual=True) == 0.0
    assert campo_numerico({"dy": "abc"}, "dy") is None


def test_primeiro_numero_nao_pula_zero():
    assert primeiro_numero(0, 5) == 0.0
    assert primeiro_numero(None, "", "abc", 0.0) == 0.0
    assert primeiro_numero(None, float("nan"), 2.5) == 2.5
    assert primeiro_numero(None, "", "x") is None


def test_derivar_divisao_e_produto_respeitam_ausencia():
    assert derivar_divisao(10, 2) == 5.0
    assert derivar_divisao(0, 2) == 0.0
    assert derivar_divisao(10, 0) is None
    assert derivar_divisao(10, None) is None
    assert derivar_divisao(None, 2) is None
    assert derivar_produto(10, 0) == 0.0
    assert derivar_produto(10, None) is None
    assert derivar_produto(2, 3, 4) == 24.0
