import importlib.util
import pathlib
import unittest
import urllib.error

path = pathlib.Path(__file__).resolve().parents[1] / "scripts/diagnostico_fontes.py"
spec = importlib.util.spec_from_file_location("diagnostico_fontes", path)
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)


HTML = """
<table>
  <tr><th>Papel</th><th>Cotação</th><th>P/L</th></tr>
  <tr><td>PETR4</td><td>31,00</td><td>5,1</td></tr>
  <tr><td>VALE3</td><td>60,00</td><td>6,0</td></tr>
</table>
"""


class DiagnosticoFontesTests(unittest.TestCase):
    def test_extrai_tabela_fundamentus(self):
        headers, rows = d._fundamentus_rows(HTML)
        self.assertEqual(headers[:2], ["Papel", "Cotação"])
        self.assertEqual(rows["PETR4"]["P/L"], "5,1")

    def test_http_error_preserva_codigo_sem_corpo(self):
        def request(_):
            raise urllib.error.HTTPError("https://fundamentus.com.br/resultado.php", 429, "rate", None, None)
        result = d.coletar_fundamentus(request_text=request)
        self.assertEqual(result["status"], "falha")
        self.assertEqual(result["http_status"], 429)
        self.assertNotIn("texto", result)

    def test_compara_cobertura_por_ativo(self):
        def fund():
            return {
                "status": "valido", "segundos": 0.1, "http_status": 200,
                "colunas": ["Papel"], "linhas": 2,
                "dados": {"PETR4": {}, "VALE3": {}},
            }

        def yahoo(ticker):
            if ticker == "VALE3":
                return {"status": "falha", "segundos": 0.2, "http_status": 404, "tipo": "HTTPError"}
            return {"status": "valido", "segundos": 0.1, "http_status": 200, "preco": 30, "horario_fonte": 1}

        result = d.diagnosticar(
            ["PETR4", "VALE3", "ITUB4"], 3, 0,
            coletar_fund=fund, coletar_yf=yahoo, sleep=lambda _: None,
        )
        self.assertEqual([item["cobertura"] for item in result["resultados"]], ["ambas", "somente_fundamentus", "somente_yahoo"])
        self.assertEqual(result["parametro_recomendado"]["fundamentus_por_execucao"], 1)

    def test_rejeita_ticker_invalido(self):
        with self.assertRaises(ValueError):
            d.diagnosticar(["PETR4", "URL"], 2, 0, coletar_fund=lambda: {}, coletar_yf=lambda _: {})
