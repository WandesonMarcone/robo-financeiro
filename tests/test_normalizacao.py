from datetime import date, datetime

from pipeline_dados.normalizacao import (
    formatar_cnpj,
    normalizar_cnpj,
    normalizar_data,
    normalizar_texto,
)


def test_normalizar_cnpj_com_mascara():
    assert normalizar_cnpj("00.000.000/0001-91") == "00000000000191"


def test_normalizar_cnpj_apenas_digitos():
    assert normalizar_cnpj("00000000000191") == "00000000000191"


def test_normalizar_cnpj_invalido_retorna_none():
    assert normalizar_cnpj("123") is None
    assert normalizar_cnpj("") is None
    assert normalizar_cnpj(None) is None


def test_formatar_cnpj_aplica_mascara():
    assert formatar_cnpj("00000000000191") == "00.000.000/0001-91"


def test_formatar_cnpj_ja_mascarado_mantem_valor():
    assert formatar_cnpj("00.000.000/0001-91") == "00.000.000/0001-91"


def test_formatar_cnpj_invalido_mantem_entrada():
    assert formatar_cnpj("123") == "123"


def test_normalizar_data_iso():
    assert normalizar_data("2024-05-10") == date(2024, 5, 10)


def test_normalizar_data_brasileira():
    assert normalizar_data("10/05/2024") == date(2024, 5, 10)


def test_normalizar_data_fnet():
    assert normalizar_data("10-05-2024") == date(2024, 5, 10)


def test_normalizar_data_com_hora():
    assert normalizar_data("2024-05-10 14:30:00") == date(2024, 5, 10)
    assert normalizar_data("10/05/2024 14:30:00") == date(2024, 5, 10)


def test_normalizar_data_aceita_date_e_datetime():
    assert normalizar_data(date(2024, 5, 10)) == date(2024, 5, 10)
    assert normalizar_data(datetime(2024, 5, 10, 8, 0)) == date(2024, 5, 10)


def test_normalizar_data_invalida_retorna_none():
    assert normalizar_data(None) is None
    assert normalizar_data("") is None
    assert normalizar_data("data invalida") is None


def test_normalizar_texto_remove_acentos():
    assert normalizar_texto("ÁÉÍÓÚ ÃÕ Ç") == "AEIOU AO C"
    assert normalizar_texto("MXRF11") == "MXRF11"
    assert normalizar_texto(None) == ""
