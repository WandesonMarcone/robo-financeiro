import unittest
from datetime import date
from decimal import Decimal
from services.fundamentos_consolidados import agrupar, filtrar_historico, json_itens

def fato(metrica, ano, periodicidade, ticker="ABEV3", classe="ACAO"):
    data=date(ano,12 if periodicidade=="ANUAL" else 3,31)
    return {"identificador":f"{ticker}-{ano}-{periodicidade}-{metrica}","ticker":ticker,"classe":classe,
            "periodo_fim":data,"exercicio":ano,"periodicidade":periodicidade,
            "documento":"DFP" if periodicidade=="ANUAL" else "ITR","metrica":metrica,
            "valor":Decimal("123.45678901"),"fonte":"CVM","conta_codigo":"3.01"}

class TestConsolidacao(unittest.TestCase):
    def test_grupos_preservam_precisao_e_fonte(self):
        f=[fato(m,2025,"ANUAL") for m in ("receita_liquida","lucro_liquido","patrimonio_liquido")]
        g=agrupar(f,"fundamentos")
        self.assertEqual(len(g),1)
        self.assertEqual(len(g[0]["itens"]),3)
        self.assertIn("123.45678901",json_itens(g[0]["itens"]))
        self.assertIn('"fonte":"CVM"',json_itens(g[0]["itens"]))
    def test_retencao_apenas_anual_com_minimo(self):
        f=[fato(m,2025,"ANUAL") for m in ("receita_liquida","lucro_liquido","patrimonio_liquido")]
        f += [fato("lucro_liquido",2025,"TRIMESTRAL"),fato("lucro_liquido",2026,"TRIMESTRAL"),
              fato("lucro_liquido",2024,"TRIMESTRAL"),fato("lucro_liquido",2025,"TRIMESTRAL","FII11","FII")]
        ret,_=filtrar_historico(f,[],2026)
        self.assertEqual(len(ret),6)
        self.assertNotIn(f[3],ret)
        self.assertIn(f[4],ret)
        self.assertIn(f[5],ret)
        self.assertIn(f[6],ret)
