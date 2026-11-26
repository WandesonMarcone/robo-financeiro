import unittest

from modules.scraper_acoes import classificar_setor_por_mapa


class ClassificacaoSetorAcoesTest(unittest.TestCase):
    def test_tickers_atual_e_anterior_da_embraer_preservam_setor(self):
        self.assertEqual(
            classificar_setor_por_mapa("EMBJ3"),
            ("Bens Industriais", "Material de Transporte"),
        )
        self.assertEqual(
            classificar_setor_por_mapa("EMBR3"),
            ("Bens Industriais", "Material de Transporte"),
        )


if __name__ == "__main__":
    unittest.main()
