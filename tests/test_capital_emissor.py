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

    def test_total_oficial_nao_inventa_quantidade_da_classe(self):
        from services.capital_emissor import _resumo
        capital={"emitidas":3000000,"qualidade":"CVM_OFICIAL_TOTAL","classes":{}}
        resumo=_resumo("TEST4","123",capital,[])
        self.assertEqual(3000000,resumo["company_shares"])
        self.assertIsNone(resumo["ticker_shares"])
        self.assertEqual("CVM_OFICIAL_TOTAL",resumo["status"])

    def test_yahoo_nao_soma_classes_nem_units(self):
        from datetime import datetime, timezone
        from services.capital_yahoo import observar, resumir
        now=datetime.now(timezone.utc)
        obs=[{"ticker":t,"cnpj":"123","shares_outstanding":q,"implied_shares_outstanding":i,"coletado_em":now}
             for t,q,i in [("TEST3",100,300),("TEST4",200,300),("TEST11",100,999)]]
        self.assertEqual(resumir("TEST3","123",obs)["company_shares"],300)
        self.assertIsNone(resumir("TEST11","123",obs)["ticker_shares"])
        obs[1]["implied_shares_outstanding"]=400
        self.assertIsNone(resumir("TEST3","123",obs)["company_shares"])
        self.assertIsNone(observar("TEST3",{"sharesOutstanding":0,"impliedSharesOutstanding":float("nan")}))
