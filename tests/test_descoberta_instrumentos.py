import unittest

from services.coletor_etfs_bdrs import registrar_instrumento
from services.descoberta_instrumentos import candidatos_b3, descobrir_e_cadastrar
from services.planilha_instrumentos import COLUNAS_PLANILHA_INSTRUMENTOS


class Resposta:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class Aba:
    def __init__(self, eventos, linhas=None):
        self.eventos = eventos
        self.linhas = linhas or [list(COLUNAS_PLANILHA_INSTRUMENTOS)]

    def get_all_values(self):
        return self.linhas

    def update(self, valores, intervalo, value_input_option=None):
        self.eventos.append(("planilha", intervalo, valores))

    def insert_row(self, valores, index=1, value_input_option=None):
        self.eventos.append(("cabecalho", index, valores))

    def freeze(self, **_kwargs):
        return None


class Planilha:
    def __init__(self, aba):
        self.aba = aba

    def worksheet(self, _nome):
        return self.aba


class ResultadoSQL:
    def mappings(self):
        return self

    def one(self):
        return {"id": 1, "ticker": "NOVO11", "tipo": "ETF"}


class Sessao:
    def __init__(self, eventos):
        self.eventos = eventos

    def execute(self, *_args, **_kwargs):
        self.eventos.append(("neon",))
        return ResultadoSQL()

    def commit(self):
        self.eventos.append(("commit",))

    def rollback(self):
        self.eventos.append(("rollback",))

    def close(self):
        pass


class DescobertaInstrumentosTests(unittest.TestCase):
    def test_lista_brapi_filtra_etf_com_cotacao_e_volume(self):
        payload = {"requestedAt": "2026-11-24T10:00:00Z", "stocks": [
            {"stock": "NOVO11", "name": "ETF Novo", "close": 10,
             "change": -1, "volume": 1000, "subType": "etf"},
            {"stock": "SEM11", "name": "Sem volume", "close": 10,
             "volume": 0, "subType": "etf"},
        ]}
        itens = candidatos_b3("ETF", get=lambda *_a, **_k: Resposta(payload))
        self.assertEqual(["NOVO11"], [x["ticker"] for x in itens])

    def test_cadastro_grava_planilha_antes_do_neon(self):
        eventos = []
        planilha = Planilha(Aba(eventos))
        registrar_instrumento(
            "NOVO11", "ETF", nome="ETF Novo", planilha=planilha,
            session_factory=lambda: Sessao(eventos),
        )
        self.assertEqual("planilha", eventos[0][0])
        self.assertEqual("neon", eventos[1][0])

    def test_descoberta_nao_recadastra_ticker_da_planilha(self):
        eventos = []
        linhas = [list(COLUNAS_PLANILHA_INSTRUMENTOS), ["NOVO11"]]
        planilha = Planilha(Aba(eventos, linhas=linhas))
        payload = {"stocks": [
            {"stock": "NOVO11", "name": "ETF Novo", "close": 10,
             "change": 1, "volume": 1000, "subType": "etf"},
        ]}
        chamados = []
        resultado = descobrir_e_cadastrar(
            "ETF", planilha=planilha,
            get=lambda *_a, **_k: Resposta(payload),
            registrar=lambda *a, **k: chamados.append((a, k)),
        )
        self.assertEqual([], chamados)
        self.assertEqual([], resultado["adicionados"])

    def test_aba_legada_sem_cabecalho_preserva_primeiro_ativo(self):
        eventos = []
        linha_legada = [
            "BOVA11", "ETF Ibovespa", "167", "0,5", "Ibovespa",
            "1", "1", "-18", "50", "8", "—", "10", "—",
            "YAHOO_FINANCE", "2026-11-17", "17/11/2026 23:08",
        ]
        aba = Aba(eventos, linhas=[linha_legada])
        planilha = Planilha(aba)
        from services.planilha_instrumentos import listar_tickers_planilha

        self.assertEqual({"BOVA11"}, listar_tickers_planilha("ETF", planilha))
        self.assertEqual("cabecalho", eventos[0][0])
        self.assertEqual("TICKER", eventos[0][2][0])
        self.assertEqual("BOVA11", aba.linhas[0][0])


if __name__ == "__main__":
    unittest.main()
