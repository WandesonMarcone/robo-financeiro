import unittest
from datetime import datetime, timedelta, timezone, date
from services.fila_fundamentos_acoes import selecionar_pendentes
from services.fundamentos_valuation import avaliar_cobertura, _escala

class TestFilaFundamentos(unittest.TestCase):
    def test_prioriza_novos_e_respeita_retry(self):
        agora = datetime(2026, 11, 25, tzinfo=timezone.utc)
        estados = {
            "BBAS3": {"ultima_tentativa": agora - timedelta(days=1), "proxima_tentativa": agora},
            "ITSA4": {"ultima_tentativa": agora, "proxima_tentativa": agora + timedelta(days=1)}
        }
        self.assertEqual(selecionar_pendentes(["BBAS3", "PETR4", "ITSA4"], estados, agora, 2), ["PETR4", "BBAS3"])

    def test_nao_confunde_campos_espalhados_com_historico(self):
        fatos = [{"periodo_fim": date(ano, 12, 31), "periodicidade": "ANUAL", "metrica": "lpa" if ano < 2025 else "vpa"} for ano in range(2021, 2026)]
        metodos = {x["metodo"]: x for x in avaliar_cobertura("TEST3", "ACAO", fatos, [])}
        self.assertEqual(metodos["GRAHAM"]["status"], "PARCIAL")

    def test_escala_milhoes(self):
        self.assertEqual(_escala({"ESCALA_MOEDA": "MILHÃO"}, "receita_liquida"), 1000000)

if __name__ == "__main__":
    unittest.main()
