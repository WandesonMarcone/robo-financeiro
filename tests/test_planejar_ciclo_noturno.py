import unittest

from scripts.planejar_ciclo_noturno import planejar


class Aba:
    def __init__(self, valores):
        self.valores = valores

    def get_all_values(self):
        return self.valores


class Planilha:
    def __init__(self, acoes, fiis):
        self.abas = {"BD_Acoes": Aba(acoes), "BD_FIIs": Aba(fiis)}

    def worksheet(self, nome):
        return self.abas[nome]


class PlanejamentoNoturnoTests(unittest.TestCase):
    def test_calcula_lotes_para_cobertura_completa(self):
        acoes = [["Ticker"]] + [[f"AC{i:03}3"] for i in range(101)]
        fiis = [["Ticker"]] + [[f"FI{i:03}11"] for i in range(48)]
        resultado = planejar(30, Planilha(acoes, fiis))
        self.assertEqual(resultado["por_lote_acoes"] + resultado["por_lote_fiis"], 30)
        self.assertEqual(resultado["ciclos"], 6)
        self.assertGreaterEqual(resultado["ciclos"] * resultado["por_lote_acoes"], 101)
        self.assertGreaterEqual(resultado["ciclos"] * resultado["por_lote_fiis"], 48)


if __name__ == "__main__":
    unittest.main()
