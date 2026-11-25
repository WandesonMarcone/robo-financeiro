import unittest
import pandas as pd
from services.identidade_fundamentos_acoes import mapa_fca
from scripts.notificar_fundamentos import mensagem

class TestIdentidade(unittest.TestCase):
    def test_mapa_oficial_e_ambiguidade(self):
        geral = pd.DataFrame([{"CNPJ_Companhia": c, "Setor_Atividade": "Financeiro"} for c in ("28.195.667/0001-06", "05.878.397/0001-32")])
        valores = pd.DataFrame([{"CNPJ_Companhia": c, "Codigo_Negociacao": t, "Tipo": "Ações", "Mercado": "Bolsa"} for c,t in [("28.195.667/0001-06","ABCB4"),("05.878.397/0001-32","ALOS3"),("28.195.667/0001-06","AMB3"),("05.878.397/0001-32","AMB3")]])
        mapa = mapa_fca(geral, valores)
        self.assertEqual(mapa["ABCB4"]["cnpj"], "28195667000106")
        self.assertEqual(mapa["ALOS3"]["cnpj"], "05878397000132")
        self.assertNotIn("AMB3", mapa)

    def test_resumo_nao_oculta_falha(self):
        s = mensagem({"universo":135,"processados":[{"ticker":"ABCB4","estado":"FALHA","detalhe":{"motivo":"CNPJ ausente"}}],"falhas":["ABCB4"]})
        self.assertIn("ABCB4", s)
        self.assertIn("Falhas de coleta: 1", s)
