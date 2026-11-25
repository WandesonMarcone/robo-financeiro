import unittest
from services.capital_emissor import reconciliar, escala_suspeita
from services.universo_acoes import normalizar_ticker_acao

class TestCapital(unittest.TestCase):
    def test_bradesco(self):
        c=reconciliar(5606747177,5590117604,11196864781,21300000)
        self.assertEqual(c["emitidas"]-c["tesouraria"],11175564781)
    def test_inconsistencia(self):
        self.assertIsNone(reconciliar(100,80,200,0))
        self.assertIsNone(reconciliar(100,80,180,181))
    def test_escala_nao_chuta(self):
        self.assertTrue(escala_suspeita(15616526,15616526000,1))
        self.assertFalse(escala_suspeita(15616526000,15616526000,1))
    def test_ticker_b3(self):
        self.assertEqual(normalizar_ticker_acao("B3SA3"),"B3SA3")
        self.assertIsNone(normalizar_ticker_acao("TICKER"))
