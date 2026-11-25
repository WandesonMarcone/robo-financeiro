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


    def test_quantidades_nao_somam_classes(self):
        from services.capital_emissor import quantidades
        c={"emitidas":3000000,"classes":{"TEST3":{"emitidas":1000000},"TEST4":{"emitidas":2000000}}}
        self.assertEqual(quantidades(c,"TEST3")["ticker_shares"],1000000)
        self.assertEqual(quantidades(c,"TEST4")["company_shares"],3000000)
        self.assertIsNone(quantidades(c,"TEST11")["ticker_shares"])
        self.assertIsNone(quantidades(None,"TEST3")["company_shares"])
