import logging
from datetime import date

import pytest

from pipeline_dados.qualidade_dados import (
    INVALID,
    VALID,
    WARNING,
    ResultadoQualidade,
    cnpj_verificar_digitos,
    parsear_numero,
    registrar_diagnostico,
    validar_registro,
)


def registro_fii_valido():
    return {
        "cnpj_fundo": "00.000.000/0001-91",
        "patrimonio_liquido": 1_000_000.0,
        "ativo_total": 1_500_000.0,
        "disponibilidades_caixa": 200_000.0,
        "cotistas": 1200,
    }


def registro_acao_valido():
    return {
        "data_referencia": date(2024, 12, 31),
        "ativo_total": 1_000.0,
        "passivo_total": 1_000.0,
        "caixa": 100.0,
        "patrimonio_liquido": 400.0,
        "divida_bruta": 150.0,
        "divida_curto_prazo": 50.0,
        "divida_longo_prazo": 100.0,
        "divida_liquida": 50.0,
        "receita": 800.0,
        "lucro_bruto": 300.0,
        "ebitda": 200.0,
        "resultado_financeiro": -20.0,
        "lucro_liquido": 100.0,
        "fco": 90.0,
    }


def achados_por_regra(resultado, regra):
    return [a for a in resultado.achados if a.regra == regra]


# ==========================================
# DADO VÁLIDO E NÃO-BLOQUEIO DE DADOS LEGÍTIMOS
# ==========================================

def test_fii_valido_e_aceito():
    resultado = validar_registro(
        registro_fii_valido(), "fii_informe_cvm", origem="CVM/INF_MENSAL_FII", ativo="TEST11"
    )
    assert resultado.status == VALID
    assert resultado.aceita is True
    assert resultado.achados == []


def test_acao_valida_e_aceita_com_negativos_legitimos():
    resultado = validar_registro(registro_acao_valido(), "acao_itr_cvm", origem="CVM/ITR", ativo="PETR4")
    assert resultado.status == VALID
    assert resultado.aceita is True


def test_documento_fnet_valido_e_aceito():
    resultado = validar_registro(
        {
            "data_publicacao": date(2024, 5, 10),
            "tipo_documento": "Fato Relevante",
            "url_pdf": "https://fnet.bmfbovespa.com.br/arquivos/123.pdf",
            "id_b3": "B3-123",
        },
        "documento_fnet",
        origem="FNET/B3",
        ativo="MXRF11",
        documento="B3-123",
    )
    assert resultado.status == VALID
    assert resultado.aceita is True


def test_campo_nao_mapeado_e_ignorado():
    registro = registro_fii_valido()
    registro["campo_desconhecido"] = "qualquer coisa"
    resultado = validar_registro(registro, "fii_informe_cvm")
    assert resultado.status == VALID


# ==========================================
# CAMPO OBRIGATÓRIO AUSENTE (DADO AUSENTE)
# ==========================================

def test_campo_obrigatorio_ausente_bloqueia():
    resultado = validar_registro(
        {"data_publicacao": None, "tipo_documento": "Fato Relevante"},
        "documento_fnet",
        origem="FNET/B3",
    )
    assert resultado.status == INVALID
    assert resultado.aceita is False
    assert achados_por_regra(resultado, "CAMPO_OBRIGATORIO")


def test_dado_ausente_e_diferente_de_invalido():
    ausente = validar_registro(
        {"data_publicacao": None, "tipo_documento": "Fato Relevante"}, "documento_fnet"
    )
    invalido = validar_registro(
        {"data_publicacao": "31/02/2024", "tipo_documento": "Fato Relevante"}, "documento_fnet"
    )
    assert ausente.status == INVALID
    assert invalido.status == INVALID
    assert {a.regra for a in ausente.achados} == {"CAMPO_OBRIGATORIO"}
    assert {a.regra for a in invalido.achados} == {"DATA_INVALIDA"}
    mensagem_ausente = next(a for a in ausente.achados).mensagem
    assert "AUSENTE" in mensagem_ausente


def test_campo_opcional_ausente_nao_bloqueia():
    registro = registro_fii_valido()
    registro["disponibilidades_caixa"] = None
    resultado = validar_registro(registro, "fii_informe_cvm")
    assert resultado.status == VALID
    assert resultado.aceita is True


def test_texto_obrigatorio_ausente_bloqueia():
    resultado = validar_registro(
        {"data_publicacao": date(2024, 5, 10), "tipo_documento": ""}, "documento_fnet"
    )
    assert resultado.status == INVALID
    assert achados_por_regra(resultado, "CAMPO_OBRIGATORIO")


# ==========================================
# CNPJ
# ==========================================

def test_cnpj_valido_aceito():
    assert cnpj_verificar_digitos("00.000.000/0001-91") is True
    assert cnpj_verificar_digitos("60.872.504/0001-23") is True


def test_cnpj_invalido_rejeitado():
    assert cnpj_verificar_digitos("00.000.000/0000-00") is False
    assert cnpj_verificar_digitos("00.000.000/0001-00") is False
    assert cnpj_verificar_digitos("12.ABC.345/0001-00") is False
    assert cnpj_verificar_digitos("123") is False


def test_cnpj_invalido_bloqueia_registro_fii():
    registro = registro_fii_valido()
    registro["cnpj_fundo"] = "00.000.000/0000-00"
    resultado = validar_registro(registro, "fii_informe_cvm")
    assert resultado.status == INVALID
    assert achados_por_regra(resultado, "CNPJ_INVALIDO")


def test_cnpj_ausente_e_opcional():
    registro = registro_fii_valido()
    registro["cnpj_fundo"] = None
    resultado = validar_registro(registro, "fii_informe_cvm")
    assert resultado.status == VALID


# ==========================================
# DATAS
# ==========================================

def test_data_invalida_rejeitada():
    resultado = validar_registro(
        {"data_publicacao": "31/02/2024", "tipo_documento": "Fato Relevante"}, "documento_fnet"
    )
    assert resultado.status == INVALID
    assert achados_por_regra(resultado, "DATA_INVALIDA")


def test_data_futura_gera_warning_e_nao_bloqueia():
    resultado = validar_registro(
        {"data_publicacao": "2099-01-01", "tipo_documento": "Fato Relevante"}, "documento_fnet"
    )
    assert resultado.status == WARNING
    assert resultado.aceita is True
    assert achados_por_regra(resultado, "DATA_FUTURA")


def test_data_antiga_gera_warning_e_nao_bloqueia():
    resultado = validar_registro(
        {"data_publicacao": "1980-05-10", "tipo_documento": "Fato Relevante"}, "documento_fnet"
    )
    assert resultado.status == WARNING
    assert resultado.aceita is True
    assert achados_por_regra(resultado, "DATA_ANTIGA")


def test_data_referencia_invalida_em_acao_rejeita():
    registro = registro_acao_valido()
    registro["data_referencia"] = "não é uma data"
    resultado = validar_registro(registro, "acao_itr_cvm")
    assert resultado.status == INVALID
    assert achados_por_regra(resultado, "DATA_INVALIDA")


# ==========================================
# NaN / NONE / VALORES IMPOSSÍVEIS
# ==========================================

def test_nan_em_campo_numerico_rejeitado():
    registro = registro_fii_valido()
    registro["patrimonio_liquido"] = float("nan")
    resultado = validar_registro(registro, "fii_informe_cvm")
    assert resultado.status == INVALID
    assert achados_por_regra(resultado, "NAO_FINITO")


def test_infinito_rejeitado():
    registro = registro_acao_valido()
    registro["receita"] = float("inf")
    resultado = validar_registro(registro, "acao_itr_cvm")
    assert resultado.status == INVALID
    assert achados_por_regra(resultado, "NAO_FINITO")


def test_valor_negativo_impossivel_rejeitado():
    registro = registro_fii_valido()
    registro["ativo_total"] = -5.0
    resultado = validar_registro(registro, "fii_informe_cvm")
    assert resultado.status == INVALID
    assert achados_por_regra(resultado, "VALOR_NEGATIVO")


def test_valor_negativo_em_acao_nao_bloqueia():
    registro = registro_acao_valido()
    registro["patrimonio_liquido"] = -10.0
    resultado = validar_registro(registro, "acao_itr_cvm")
    assert resultado.status == WARNING
    assert resultado.aceita is True
    assert achados_por_regra(resultado, "VALOR_NEGATIVO_SUSPEITO")


def test_valor_nao_numerico_rejeitado():
    registro = registro_fii_valido()
    registro["cotistas"] = "muitos"
    resultado = validar_registro(registro, "fii_informe_cvm")
    assert resultado.status == INVALID
    assert achados_por_regra(resultado, "NAO_NUMERO")


def test_cotistas_decimais_geram_warning():
    registro = registro_fii_valido()
    registro["cotistas"] = 1200.5
    resultado = validar_registro(registro, "fii_informe_cvm")
    assert resultado.status == WARNING
    assert resultado.aceita is True
    assert achados_por_regra(resultado, "NAO_INTEIRO")


def test_vacancia_acima_de_1_gera_warning_e_nao_bloqueia():
    resultado = validar_registro(
        {"vacancia_fisica": 1.5, "patrimonio_liquido": 100.0}, "fii_informe_cvm"
    )
    assert resultado.status == WARNING
    assert resultado.aceita is True
    assert achados_por_regra(resultado, "VACANCIA_ESCALA")


def test_vacancia_negativa_rejeitada():
    resultado = validar_registro(
        {"vacancia_fisica": -0.1, "patrimonio_liquido": 100.0}, "fii_informe_cvm"
    )
    assert resultado.status == INVALID
    assert achados_por_regra(resultado, "VALOR_NEGATIVO")


def test_despesas_taxas_negativas_geram_warning():
    resultado = validar_registro({"despesas_taxas": -5.0}, "fii_informe_cvm")
    assert resultado.status == WARNING
    assert resultado.aceita is True


def test_url_invalida_rejeitada():
    resultado = validar_registro(
        {
            "data_publicacao": date(2024, 5, 10),
            "tipo_documento": "Fato Relevante",
            "url_pdf": "ftp://arquivo.pdf",
        },
        "documento_ipe",
    )
    assert resultado.status == INVALID
    assert achados_por_regra(resultado, "URL_INVALIDA")


# ==========================================
# CONSISTÊNCIA ENTRE CAMPOS
# ==========================================

def test_consistencia_balanco_ok():
    resultado = validar_registro(registro_acao_valido(), "acao_itr_cvm")
    assert not achados_por_regra(resultado, "INCONSISTENCIA_BALANCO")


def test_consistencia_balanco_quebrada_gera_warning():
    registro = registro_acao_valido()
    registro["ativo_total"] = 1_000.0
    registro["passivo_total"] = 300.0
    resultado = validar_registro(registro, "acao_itr_cvm")
    assert resultado.status == WARNING
    assert resultado.aceita is True
    assert achados_por_regra(resultado, "INCONSISTENCIA_BALANCO")


def test_pl_maior_que_passivo_gera_warning():
    registro = registro_acao_valido()
    registro["patrimonio_liquido"] = 1_500.0
    resultado = validar_registro(registro, "acao_itr_cvm")
    assert achados_por_regra(resultado, "INCONSISTENCIA_BALANCO")


def test_dados_incompletos_nao_sao_inconsistencia():
    resultado = validar_registro({"ativo_total": 100.0}, "acao_itr_cvm")
    assert not achados_por_regra(resultado, "INCONSISTENCIA_BALANCO")


# ==========================================
# ERRO DE COLETA NUNCA VIRA ZERO
# ==========================================

def test_parsear_numero_nao_vira_zero_em_erro():
    assert parsear_numero("abc") is None
    assert parsear_numero("") is None
    assert parsear_numero("R$ 1,50") is None
    assert parsear_numero(float("nan")) is None
    assert parsear_numero(float("inf")) is None
    assert parsear_numero(None) is None


def test_parsear_numero_preserva_zero_legitimo_e_formato_br():
    assert parsear_numero("0") == 0.0
    assert parsear_numero(0) == 0.0
    assert parsear_numero("1.234,56") == 1234.56
    assert parsear_numero("1234,56") == 1234.56


def test_ausencia_em_campo_obrigatorio_rejeita_em_vez_de_zero():
    registro = registro_fii_valido()
    registro["patrimonio_liquido"] = None
    registro["ativo_total"] = None
    resultado = validar_registro(registro, "fii_informe_cvm")
    assert resultado.status == VALID  # campos opcionais: ausência é aceita


def test_erro_de_coleta_rejeitado_e_nao_persistido():
    registro = registro_fii_valido()
    registro["patrimonio_liquido"] = "erro_de_coleta"
    resultado = validar_registro(registro, "fii_informe_cvm")
    assert resultado.status == INVALID
    assert resultado.aceita is False
    assert parsear_numero("erro_de_coleta") is None


# ==========================================
# INVALID vs WARNING
# ==========================================

def test_invalid_prevalece_sobre_warning():
    registro = registro_fii_valido()
    registro["patrimonio_liquido"] = -1.0  # INVALID
    registro["cotistas"] = 10.5  # WARNING
    resultado = validar_registro(registro, "fii_informe_cvm")
    assert resultado.status == INVALID
    assert resultado.aceita is False


def test_warning_aceita_mas_registra_achado():
    resultado = validar_registro(
        {"vacancia_financeira": 1.2, "patrimonio_liquido": 100.0}, "fii_informe_cvm"
    )
    assert resultado.status == WARNING
    assert resultado.aceita is True
    assert resultado.achados


# ==========================================
# ORIGEM REGISTRADA
# ==========================================

def test_origem_e_contexto_registrados():
    resultado = validar_registro(
        registro_acao_valido(), "acao_itr_cvm", origem="CVM/ITR", ativo="PETR4", documento="2024-12-31"
    )
    assert resultado.origem == "CVM/ITR"
    assert resultado.ativo == "PETR4"
    assert resultado.documento == "2024-12-31"
    assert isinstance(resultado, ResultadoQualidade)


def test_origem_preservada_nos_achados():
    resultado = validar_registro(
        registro_fii_valido(), "fii_informe_cvm", origem="CVM/INF_MENSAL_FII", ativo="TEST11"
    )
    assert resultado.origem == "CVM/INF_MENSAL_FII"
    assert resultado.ativo == "TEST11"


def test_registrar_diagnostico_loga_achados(caplog):
    registro = registro_fii_valido()
    registro["cnpj_fundo"] = "00.000.000/0000-00"
    resultado = validar_registro(
        registro, "fii_informe_cvm", origem="CVM/INF_MENSAL_FII", ativo="TEST11"
    )
    with caplog.at_level(logging.ERROR, logger="test.qualidade"):
        registrar_diagnostico(resultado, logger=logging.getLogger("test.qualidade"))
    assert "CNPJ_INVALIDO" in caplog.text
    assert "CVM/INF_MENSAL_FII" in caplog.text
    assert "TEST11" in caplog.text


def test_registrar_diagnostico_silencioso_sem_achados(caplog):
    resultado = validar_registro(registro_fii_valido(), "fii_informe_cvm")
    with caplog.at_level(logging.ERROR):
        registrar_diagnostico(resultado, logger=logging.getLogger("test.qualidade"))
    assert not caplog.records


# ==========================================
# API E REGRAS DE CONTORNO
# ==========================================

def test_contexto_desconhecido_levanta_erro():
    with pytest.raises(ValueError):
        validar_registro({}, "contexto_que_nao_existe")


def test_validacao_nunca_muta_o_registro():
    registro = registro_fii_valido()
    copia = dict(registro)
    validar_registro(registro, "fii_informe_cvm")
    assert registro == copia
