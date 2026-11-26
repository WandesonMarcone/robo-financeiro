import unittest

from services.catalogo_central import espelhar_acoes_oficiais


class Resultado:
    rowcount = 97


class Sessao:
    def __init__(self):
        self.sql = []

    def execute(self, consulta):
        self.sql.append(str(consulta))
        return Resultado()


class CatalogoCentralTests(unittest.TestCase):
    def test_espelho_separa_ticker_de_cnpj_e_preserva_historico(self):
        sessao = Sessao()
        resultado = espelhar_acoes_oficiais(sessao)
        texto = "\n".join(sessao.sql)
        self.assertEqual(resultado["catalogo_afetado"], 97)
        self.assertIn("ON CONFLICT (ticker)", texto)
        self.assertIn("JOIN empresas e ON e.cnpj=co.cnpj", texto)
        self.assertNotIn("DELETE FROM", texto)


if __name__ == "__main__":
    unittest.main()
