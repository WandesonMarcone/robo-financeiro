import unittest
from datetime import date
from unittest.mock import patch

import pandas as pd

from services.proventos_eventos import coletar_proventos_eventos, selecionar_lote


class WorksheetNotFound(Exception):
    pass


class Aba:
    def __init__(self, linhas, eventos):
        self.linhas = linhas
        self.eventos = eventos

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

    def commit(self):
        self.eventos.append(("commit",))

    def rollback(self):
        self.eventos.append(("rollback",))

    def close(self):
        return None


class ProventosEventosTests(unittest.TestCase):
    def test_lote_rotativo_nao_repete_sempre_o_inicio(self):
        tickers = ["A", "B", "C", "D", "E"]
        primeiro = selecionar_lote(tickers, 2, hoje=date(2026, 11, 24))
        segundo = selecionar_lote(tickers, 2, hoje=date(2026, 11, 25))
        self.assertNotEqual(primeiro, segundo)

    def test_planilha_e_confirmada_antes_do_neon(self):
        eventos = []
        resultado = coletar_proventos_eventos(
            limite_por_classe=1, janela_dias=30, pausa_segundos=0,
            planilha=Planilha(eventos), session_factory=lambda: Sessao(eventos),
            ticker_factory=lambda _simbolo: Papel(), hoje=date(2026, 11, 24),
        )
        tipos = [item[0] for item in eventos]
        self.assertEqual(1, resultado["proventos"])
        self.assertEqual(1, resultado["eventos"])
        self.assertLess(tipos.index("planilha"), tipos.index("neon"))
        self.assertEqual("PLANILHA_ANTES_NEON", resultado["ordem_persistencia"])


if __name__ == "__main__":
    unittest.main()
