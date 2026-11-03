import pathlib
import unittest


class SemStatusInvestTests(unittest.TestCase):
    def test_coletor_de_fiis_nao_contem_requisicao_ao_statusinvest(self):
        arquivo = pathlib.Path(__file__).resolve().parents[1] / "modules" / "scraper_fiis.py"
        self.assertNotIn("statusinvest.com.br", arquivo.read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()
