import unittest
import pandas as pd
from services.cadastro_cnpj_oficial import cnpj_valido, extrair_cadastro, combinar_mapas_oficiais

class TestCadastroCNPJ(unittest.TestCase):
    def test_digitos(self):
        self.assertEqual(cnpj_valido("33.000.167/0001-01"),"33000167000101")
        self.assertEqual(cnpj_valido("05.878.397/0001-32"),"05878397000132")
        self.assertIsNone(cnpj_valido("31.628.739/0001-04"))
        self.assertIsNone(cnpj_valido("00000000000000"))

    def test_multiplas_classes_e_ambiguos(self):
        geral=pd.DataFrame([{"CNPJ_Companhia":c,"Nome_Empresarial":n} for c,n in [("33.000.167/0001-01","Petrobras"),("05.878.397/0001-32","Allos")]])
        valores=pd.DataFrame([{"CNPJ_Companhia":c,"Codigo_Negociacao":t,"Valor_Mobiliario":"Ações Ordinárias","Mercado":"Bolsa","Data_Fim_Negociacao":fim} for c,t,fim in [
            ("33.000.167/0001-01","PETR3",""),("33.000.167/0001-01","PETR4",""),
            ("05.878.397/0001-32","ALOS3",""),("05.878.397/0001-32","ANTG3","2020-01-01"),
            ("33.000.167/0001-01","AMBG3",""),("05.878.397/0001-32","AMBG3","")]])
        mapa, ambiguos=extrair_cadastro(geral,valores)
        self.assertEqual(mapa["PETR3"]["cnpj"],mapa["PETR4"]["cnpj"])
        self.assertNotIn("ANTG3",mapa)
        self.assertEqual(ambiguos,["AMBG3"])

    def test_layout_real_prioriza_valor_mobiliario(self):
        geral=pd.DataFrame([{"CNPJ_Companhia":"33.000.167/0001-01","Nome_Empresarial":"Petrobras"}])
        valores=pd.DataFrame([{"CNPJ_Companhia":"33.000.167/0001-01","Codigo_Negociacao":"PETR4","Valor_Mobiliario":"Ações Preferenciais","Tipo":"Outro","Mercado":"Bolsa","Data_Fim_Negociacao":float("nan")}])
        mapa,_=extrair_cadastro(geral,valores)
        self.assertEqual(mapa["PETR4"]["cnpj"],"33000167000101")

    def test_historico_oficial_preenche_ausencia_sem_substituir_atual(self):
        atual = {"PETR4": {"cnpj": "33000167000101"}}
        anterior = {
            "PETR4": {"cnpj": "00000000000000"},
            "AZZA3": {"cnpj": "12345678000199"},
        }
        mapa, referencias, ambiguos = combinar_mapas_oficiais([
            (2026, atual, set(), "fca-2026"),
            (2025, anterior, set(), "fca-2025"),
        ])
        self.assertEqual(mapa["PETR4"]["cnpj"], "33000167000101")
        self.assertEqual(mapa["AZZA3"]["cnpj"], "12345678000199")
        self.assertEqual(referencias["AZZA3"]["ano"], 2025)
        self.assertFalse(ambiguos)

    def test_ambiguidade_nunca_usa_historico_como_chute(self):
        mapa, referencias, _ = combinar_mapas_oficiais([
            (2026, {}, {"TEST3"}, "fca-2026"),
            (2025, {"TEST3": {"cnpj": "12345678000199"}}, set(), "fca-2025"),
        ])
        self.assertNotIn("TEST3", mapa)
        self.assertNotIn("TEST3", referencias)
