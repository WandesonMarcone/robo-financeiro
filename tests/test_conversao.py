"""Conversao de valores de fonte: zero legitimo vs ausencia.

Nenhuma rede e usada. Cobre ``modules.utils.converter_numero`` /
``eh_valido`` e o reexport em ``modules.scraper_fiis``.
"""

import math
import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.utils import converter_numero, eh_valido, formatar  # noqa: E402
import modules.scraper_fiis as sf  # noqa: E402


def _e_nan(valor):
    return isinstance(valor, float) and math.isnan(valor)


class TestConverterNumero(unittest.TestCase):
    def test_zero_valido(self):
        self.assertEqual(converter_numero(0), 0.0)
        self.assertEqual(converter_numero(0.0), 0.0)
        self.assertEqual(converter_numero("0"), 0.0)
        self.assertEqual(converter_numero("0,00"), 0.0)
        self.assertEqual(converter_numero("0,00%"), 0.0)
        self.assertTrue(eh_valido(converter_numero(0)))

    def test_none_e_ausencia(self):
        self.assertTrue(_e_nan(converter_numero(None)))
        self.assertFalse(eh_valido(None))
        self.assertFalse(eh_valido(converter_numero(None)))

    def test_string_vazia(self):
        self.assertTrue(_e_nan(converter_numero("")))
        self.assertTrue(_e_nan(converter_numero("   ")))

    def test_nan(self):
        self.assertTrue(_e_nan(converter_numero(float("nan"))))
        self.assertTrue(_e_nan(converter_numero(pd.NA)))
        self.assertFalse(eh_valido(float("nan")))

    def test_infinito(self):
        self.assertTrue(_e_nan(converter_numero(float("inf"))))
        self.assertTrue(_e_nan(converter_numero(float("-inf"))))
        self.assertFalse(eh_valido(float("inf")))

    def test_texto_invalido(self):
        self.assertTrue(_e_nan(converter_numero("-")))
        self.assertTrue(_e_nan(converter_numero("--")))
        self.assertTrue(_e_nan(converter_numero("N/D")))
        self.assertTrue(_e_nan(converter_numero("n/a")))
        self.assertTrue(_e_nan(converter_numero("abc")))
        self.assertTrue(_e_nan(converter_numero(True)))
        self.assertTrue(_e_nan(converter_numero(False)))

    def test_numero_valido(self):
        self.assertEqual(converter_numero(12), 12.0)
        self.assertAlmostEqual(converter_numero("11,34%"), 0.1134)
        self.assertAlmostEqual(converter_numero("R$ 1.234,56"), 1234.56)
        self.assertAlmostEqual(converter_numero(-3.5), -3.5)
        self.assertTrue(eh_valido(converter_numero("15.0")))

    def test_formatar_nao_vira_zero(self):
        self.assertTrue(_e_nan(formatar(None)))
        self.assertTrue(_e_nan(formatar("")))
        self.assertEqual(formatar(0), 0.0)

    def test_scraper_fiis_reexporta_a_mesma_funcao(self):
        self.assertIs(sf.converter_numero, converter_numero)
        self.assertIs(sf.eh_valido, eh_valido)


if __name__ == "__main__":
    unittest.main()
