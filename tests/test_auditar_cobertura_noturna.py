import unittest
from datetime import date

from scripts.auditar_cobertura_noturna import avaliar_linhas, ler_carimbo


class AuditoriaCoberturaNoturnaTests(unittest.TestCase):
    def test_ler_carimbo_valido(self):
        self.assertEqual(ler_carimbo("OK 12/11 00:10", 2026).isoformat(), "2026-11-12T00:10:00")

    def test_separa_atualizados_ausentes_e_atrasados(self):
        linhas = [
            ["Ticker"],
            ["PETR4", "", "OK 12/11 00:10"],
            ["VALE3", "", ""],
            ["ITUB4", "", "OK 09/11 08:30"],
        ]
        resultado = avaliar_linhas(linhas, coluna_carimbo=2, referencia=date(2026, 11, 12), atraso_maximo_dias=1)
        self.assertEqual(resultado["total"], 3)
        self.assertEqual(resultado["atualizados"], 1)
        self.assertEqual(resultado["ausentes"], ["VALE3"])
        self.assertEqual(resultado["atrasados"], ["ITUB4"])

    def test_aceita_coleta_da_vespera_quando_houver_tolerancia(self):
        linhas = [["Ticker"], ["PETR4", "", "OK 11/11 23:50"]]
        resultado = avaliar_linhas(linhas, coluna_carimbo=2, referencia=date(2026, 11, 12), atraso_maximo_dias=1)
        self.assertTrue(resultado["atualizados"] == 1)

