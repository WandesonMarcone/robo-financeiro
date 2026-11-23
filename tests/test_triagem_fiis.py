import unittest

from modules.relatorio_mercado import eh_oportunidade_fii


class TriagemFiisTest(unittest.TestCase):
    def test_ausencia_nao_aprova_indicador_obrigatorio(self):
        for indice in range(3):
            for valor in (None, float("nan"), float("inf"), -1):
                args = [0.9, 0.1, 10_000_000]
                args[indice] = valor
                self.assertFalse(eh_oportunidade_fii(*args))

    def test_limites_e_vacancia_zero(self):
        self.assertTrue(eh_oportunidade_fii(0.9, 0.1, 10_000_000, 0))
        self.assertFalse(eh_oportunidade_fii(0.9, 0.1, 1_000_000, 0))
        self.assertFalse(eh_oportunidade_fii(0.9, 0.1, 10_000_000, 0.2))


if __name__ == "__main__":
    unittest.main()
