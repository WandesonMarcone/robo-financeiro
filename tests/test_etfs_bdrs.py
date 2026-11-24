import unittest

from services.coletor_etfs_bdrs import BASE_INICIAL_INSTRUMENTOS, avaliar_oportunidade_instrumento


class TestEtfsBdrs(unittest.TestCase):
    def test_base_inicial_contem_cinco_etfs_e_hmrn31(self):
        self.assertEqual(len([x for x in BASE_INICIAL_INSTRUMENTOS if x["tipo"] == "ETF"]), 5)
        self.assertIn("HMRN31", {x["ticker"] for x in BASE_INICIAL_INSTRUMENTOS})

    def test_etf_liquido_com_desconto_e_candidato(self):
        item = {"tipo": "ETF", "liquidez_media_30d_brl": 250_000,
                "distancia_maxima_1a": -12, "volatilidade_30d": 20}
        self.assertIsNotNone(avaliar_oportunidade_instrumento(item))

    def test_bdr_novo_ou_sem_liquidez_nao_vira_oportunidade(self):
        item = {"tipo": "BDR", "liquidez_media_30d_brl": 2_000,
                "distancia_maxima_1a": -30, "volatilidade_30d": 25}
        self.assertIsNone(avaliar_oportunidade_instrumento(item))

    def test_base_inicial_inclui_cripto_e_dolar_sem_backfill(self):
        tipos = {x["ticker"]: x["tipo"] for x in BASE_INICIAL_INSTRUMENTOS}
        self.assertEqual(tipos["BTCBRL"], "CRIPTO")
        self.assertEqual(tipos["ETHBRL"], "CRIPTO")
        self.assertEqual(tipos["USDBRL"], "MOEDA")

    def test_cripto_usa_regra_propria_sem_exigir_liquidez_b3(self):
        item = {"tipo": "CRIPTO", "distancia_maxima_1a": -18,
                "variacao_percentual": -4.5}
        self.assertIsNotNone(avaliar_oportunidade_instrumento(item))
