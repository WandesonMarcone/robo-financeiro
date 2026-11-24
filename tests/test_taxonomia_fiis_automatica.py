import unittest

from services.taxonomia_fiis_automatica import SEGMENTOS_FII_VERIFICADOS, resolver_classificacao


class TaxonomiaFiisAutomaticaTests(unittest.TestCase):
    def test_catalogo_cobre_fiis_monitorados_sem_taxonomia(self):
        esperados = {
            "GGRC11", "BTLG11", "CLIN11", "RBRY11", "VGIR11", "CVBI11",
            "KNUQ11", "KNHF11", "MCCI11", "KNSC11", "HSRE11", "KNIP11",
            "KNHY11", "HGRU11", "HGLG11", "KNRI11", "SNEL11", "CPTS11",
            "ALZR11", "BTRU11", "KNCR11",
        }
        self.assertEqual(esperados, set(SEGMENTOS_FII_VERIFICADOS))
        for ticker, segmento in SEGMENTOS_FII_VERIFICADOS.items():
            self.assertIsNotNone(resolver_classificacao(ticker, "N/D", "N/D", segmento))

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

    def test_nan_da_fonte_nao_e_segmento(self):
        self.assertIsNone(resolver_classificacao("TEST11", "N/D", "N/D", "nan"))
