import json
import unittest
from datetime import date
from unittest.mock import Mock, patch

import pandas as pd
import requests

from services.proventos_eventos import (
    coletar_proventos_eventos, conciliar_pagamentos_b3, extrair_eventos_yahoo,
    extrair_proventos_oficiais_b3,
    selecionar_lote,
)


class WorksheetNotFound(Exception):
    pass


class Aba:
    def __init__(self, linhas, eventos):
        self.linhas = linhas
        self.eventos = eventos
        self.row_count = 1000

    def add_rows(self, quantidade):
        self.row_count += quantidade

    def get_all_values(self):
        return self.linhas

    def update(self, valores, intervalo, value_input_option=None):
        self.eventos.append(("cabecalho", intervalo))
        self.linhas = valores

    def batch_update(self, atualizacoes, value_input_option=None):
        self.eventos.append(("planilha", atualizacoes))

    def freeze(self, **_kwargs):
        return None


class Planilha:
    def __init__(self, eventos):
        self.eventos = eventos
        self.abas = {
            "BD_Acoes": Aba([["TICKER"], ["BBAS3"]], eventos),
            "BD_FIIs": Aba([["TICKER"]], eventos),
            "BD_ETFs": Aba([["TICKER"]], eventos),
            "BD_BDRs": Aba([["TICKER"]], eventos),
        }

    def worksheet(self, nome):
        if nome not in self.abas:
            raise WorksheetNotFound(nome)
        return self.abas[nome]

    def add_worksheet(self, title, rows, cols):
        aba = Aba([], self.eventos)
        self.abas[title] = aba
        return aba


class Papel:
    def history(self, **_kwargs):
        indice = pd.to_datetime(["2026-11-10", "2026-11-11"])
        return pd.DataFrame({
            "Dividends": [0.50, 0], "Capital Gains": [0, 0],
            "Stock Splits": [0, 2.0], "Close": [20, 10],
        }, index=indice)


class Sessao:
    def __init__(self, eventos):
        self.eventos = eventos

    def execute(self, _sql, parametros):
        self.eventos.append(("neon", parametros["identificador"]))
        retorno = Mock()
        retorno.mappings.return_value.one.return_value = {
            chave: parametros[chave]
            for chave in ("data_pagamento", "fonte", "qualidade_fonte")
            if chave in parametros
        }
        return retorno

    def commit(self):
        self.eventos.append(("commit",))

    def rollback(self):
        self.eventos.append(("rollback",))

    def close(self):
        return None


class ProventosEventosTests(unittest.TestCase):
    def test_b3_retem_pagamento_oficial_da_mesma_classe(self):
        class Resposta:
            def __init__(self, dados):
                self.dados = dados

            def raise_for_status(self):
                return None

            def json(self):
                return self.dados

        def get(url, **_kwargs):
            if "GetInitialCompanies" in url:
                return Resposta({"results": [{"issuingCompany": "PETR", "codeCVM": "9512"}]})
            if "GetDetail" in url:
                return Resposta(json.dumps({"otherCodes": [
                    {"code": "PETR3", "isin": "BRPETRACNOR9"},
                    {"code": "PETR4", "isin": "BRPETRACNPR6"},
                ]}))
            self.assertIn("GetListedSupplementCompany", url)
            return Resposta([{"code": "PETR", "cashDividends": [
                {"assetIssued": "BRPETRACNPR6", "isinCode": "BRPETRACNPR6", "paymentDate": "21/12/2026", "lastDatePrior": "21/08/2026", "rate": "0,47156696", "label": "DIVIDENDO"},
                {"assetIssued": "BRPETRACNOR9", "isinCode": "BRPETRACNOR9", "paymentDate": "23/11/2026", "lastDatePrior": "21/08/2026", "rate": "0,47156696"},
            ]}])

        itens = extrair_proventos_oficiais_b3("PETR4", http_get=get)
        self.assertEqual(1, len(itens))
        self.assertEqual("BRPETRACNPR6", itens[0]["isin"])
        self.assertEqual(date(2026, 12, 21), itens[0]["data_pagamento"])
        self.assertEqual(date(2026, 8, 21), itens[0]["data_com"])

    def test_b3_preserva_classe_bdr(self):
        class Resposta:
            def __init__(self, dados):
                self.dados = dados

            def raise_for_status(self):
                return None

            def json(self):
                return self.dados

        def get(url, **_kwargs):
            if "GetInitialCompanies" in url:
                return Resposta({"results": [{"issuingCompany": "AAPL", "codeCVM": "123"}]})
            if "GetDetail" in url:
                return Resposta({"otherCodes": [{"code": "AAPL34", "isin": "BRAAPLBDR001"}]})
            return Resposta([{"code": "AAPL", "cashDividends": [{
                "isinCode": "BRAAPLBDR001", "paymentDate": "21/12/2026",
                "lastDatePrior": "20/12/2026", "rate": "0,10",
            }]}])

        itens = extrair_proventos_oficiais_b3("AAPL34", http_get=get, classe="BDR")
        self.assertEqual("BDR", itens[0]["classe"])

    def test_data_oficial_divergente_fica_em_conflito(self):
        sessao = Mock()
        sessao.execute.return_value.mappings.return_value.all.return_value = [{
            "id": 10, "identificador": "evento", "data_pagamento": date(2026, 11, 23),
        }]
        resultado = conciliar_pagamentos_b3(sessao, "PETR4", oficiais=[{
            "ticker": "PETR4", "classe": "ACAO", "isin": "BRPETRACNPR6",
            "data_com": date(2026, 8, 21), "data_pagamento": date(2026, 12, 21),
            "valor_unitario": 0.47, "tipo_original": "DIVIDENDO",
            "fonte": "B3_LISTED_COMPANIES", "url_fonte": "https://www.b3.com.br/",
        }])

        self.assertEqual(1, resultado["conflitos"])
        self.assertEqual(0, resultado["confirmados"])
        self.assertEqual(2, sessao.execute.call_count)
        self.assertEqual("CONFLITO", sessao.execute.call_args.args[1]["status"])

    def test_lote_rotativo_nao_repete_sempre_o_inicio(self):
        tickers = ["A", "B", "C", "D", "E"]
        primeiro = selecionar_lote(tickers, 2, hoje=date(2026, 11, 24))
        segundo = selecionar_lote(tickers, 2, hoje=date(2026, 11, 25))
        self.assertNotEqual(primeiro, segundo)

    def test_reconsulta_falha_transitoria_do_yahoo(self):
        class PapelInstavel:
            chamadas = 0

            def history(self, **_kwargs):
                self.chamadas += 1
                if self.chamadas == 1:
                    raise RuntimeError("falha transitória")
                return Papel().history()

        with patch("services.proventos_eventos.time.sleep") as espera:
            proventos, eventos = extrair_eventos_yahoo(
                "BBAS3", "ACAO", PapelInstavel(), date(2026, 10, 1), date(2026, 11, 1)
            )
        self.assertEqual(1, len(proventos))
        self.assertEqual(1, len(eventos))
        espera.assert_called_once_with(3.0)

    def test_neon_e_confirmado_antes_do_espelho_planilha(self):
        eventos = []
        resultado = coletar_proventos_eventos(
            limite_por_classe=1, janela_dias=30, pausa_segundos=0,
            planilha=Planilha(eventos), session_factory=lambda: Sessao(eventos),
            ticker_factory=lambda _simbolo: Papel(), hoje=date(2026, 11, 24),
            b3_fetcher=lambda _ticker: [],
        )
        tipos = [item[0] for item in eventos]
        self.assertEqual(1, resultado["proventos"])
        self.assertEqual(1, resultado["eventos"])
        self.assertLess(tipos.index("neon"), tipos.index("planilha"))
        self.assertEqual("NEON_ANTES_PLANILHA", resultado["ordem_persistencia"])


    def test_indisponibilidade_b3_preserva_lote_complementar(self):
        operacoes = []

        def b3_indisponivel(_ticker):
            raise requests.ConnectionError("B3 indisponível")

        resultado = coletar_proventos_eventos(
            limite_por_classe=1, janela_dias=30, pausa_segundos=0,
            planilha=Planilha(operacoes), session_factory=lambda: Sessao(operacoes),
            ticker_factory=lambda _simbolo: Papel(), hoje=date(2026, 11, 24),
            b3_fetcher=b3_indisponivel,
        )

        self.assertEqual(1, resultado["processados"])
        self.assertEqual(1, resultado["proventos"])
        self.assertEqual(1, resultado["eventos"])
        self.assertEqual("CONSULTA_B3_PENDENTE", resultado["falhas"][0]["erro"])
        self.assertIn(("commit",), operacoes)
        self.assertNotIn(("rollback",), operacoes)


if __name__ == "__main__":
    unittest.main()
