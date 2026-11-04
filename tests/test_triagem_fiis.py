import unittest

from modules.relatorio_mercado import eh_oportunidade_fii
from modules.taxonomia_fiis import classificar_fii


class TriagemFiisTest(unittest.TestCase):
    def test_ausencia_nao_aprova_indicador_obrigatorio(self):
        for indice in range(3):
            for valor in (None, float('nan'), float('inf'), -1):
                args = [.9, .1, 10_000_000]
                args[indice] = valor
                self.assertFalse(eh_oportunidade_fii(*args))

    def test_limites_e_vacancia_zero(self):
        self.assertTrue(eh_oportunidade_fii(.9, .1, 10_000_000, 0))
        self.assertFalse(eh_oportunidade_fii(.9, .1, 1_000_000, 0))
        self.assertFalse(eh_oportunidade_fii(.9, .1, 10_000_000, .2))

    def test_classificacao_com_fonte_ausente(self):
        esperados = {'BTLG11':'Tijolo', 'XPML11':'Tijolo', 'HGLG11':'Tijolo',
                     'SNEL11':'Híbrido', 'KNIP11':'Papel', 'HGRU11':'Tijolo',
                     'KNRI11':'Tijolo', 'MCCI11':'Papel'}
        for ticker, tipo in esperados.items():
            self.assertEqual(classificar_fii('', ticker)[0], tipo)
        self.assertEqual(classificar_fii('', 'TEST11')[0], 'N/D')


if __name__ == '__main__':
    unittest.main()
