import unittest

from modules.lotes_atualizacao import distribuir_limite, proximo_lote


class LotesAtualizacaoTests(unittest.TestCase):
    def test_rotacao_nao_repete_nem_sai_do_teto(self):
        ativos = ["AAA3", "BBB3", "CCC3", "DDD3"]
        primeiro, cursor = proximo_lote(ativos, 0, 2)
        segundo, cursor2 = proximo_lote(ativos, cursor, 2)
        self.assertEqual(primeiro, ["AAA3", "BBB3"])
        self.assertEqual(segundo, ["CCC3", "DDD3"])
        self.assertEqual(cursor2, 0)

    def test_cursor_invalido_recomeca_em_zero(self):
        lote, cursor = proximo_lote(["PETR4", "VALE3"], "erro", 1)
        self.assertEqual((lote, cursor), (["PETR4"], 1))

    def test_distribuicao_respeita_teto_total(self):
        acoes, fiis = distribuir_limite(20, 77, 34)
        self.assertEqual((acoes, fiis), (14, 6))
        self.assertEqual(acoes + fiis, 20)

    def test_lista_vazia_nao_avanca(self):
        self.assertEqual(proximo_lote([], 4, 20), ([], 0))


if __name__ == "__main__":
    unittest.main()
