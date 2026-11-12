import unittest

from services.taxonomia_fiis_automatica import resolver_classificacao


class TaxonomiaFiisAutomaticaTests(unittest.TestCase):
    def test_recupera_logistica_com_evidencia(self):
        self.assertEqual(
            resolver_classificacao("HGLG11", "N/A", "N/A", "Logística"),
            ("Tijolo", "Logística"),
        )

    def test_recupera_cri_sem_chamar_de_tijolo(self):
        self.assertEqual(
            resolver_classificacao("KNCR11", "", "", "Recebíveis Imobiliários / CRI"),
            ("Papel", "CRI"),
        )

    def test_preserva_classificacao_ja_confirmada(self):
        self.assertIsNone(
            resolver_classificacao("XPML11", "Tijolo", "Shoppings", "Logística"),
        )

    def test_sem_fonte_nao_inventa(self):
        self.assertIsNone(resolver_classificacao("TEST11", "N/A", "N/A", ""))
