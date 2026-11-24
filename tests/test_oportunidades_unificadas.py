import unittest

from services.oportunidades_unificadas import montar_digest_oportunidades_instrumentos
from modules.utils import montar_markup_painel


class TestOportunidadesUnificadas(unittest.TestCase):
    def test_consolida_etf_e_bdr_no_mesmo_alerta(self):
        def listar(tipo, limite):
            dados = {
                "ETF": [{"ticker": "BOVA11", "distancia_maxima_1a": -11.2,
                         "liquidez_media_30d_brl": 500_000}],
                "BDR": [{"ticker": "A1MD34", "distancia_maxima_1a": -15.5,
                         "liquidez_media_30d_brl": 80_000}],
            }
            return dados.get(tipo, [])

        pacote = montar_digest_oportunidades_instrumentos(listar=listar)

        self.assertIn("BOVA11", pacote["texto"])
        self.assertIn("A1MD34", pacote["texto"])
        self.assertEqual(pacote["tipo"], "instrumento")
        self.assertEqual(pacote["tickers"], ["BOVA11", "A1MD34"])

    def test_nao_cria_alerta_sem_candidatos(self):
        pacote = montar_digest_oportunidades_instrumentos(
            listar=lambda tipo, limite: []
        )
        self.assertEqual(pacote["texto"], "")
        self.assertEqual(pacote["itens"], [])

    def test_botoes_de_instrumentos_abrem_o_painel_especifico(self):
        markup = montar_markup_painel(["BOVA11", "A1MD34"], "instrumento")
        callbacks = [botao.callback_data for linha in markup.keyboard for botao in linha]
        self.assertEqual(callbacks, ["painel_int_BOVA11", "painel_int_A1MD34"])
