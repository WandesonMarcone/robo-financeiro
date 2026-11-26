import unittest

from modules.resiliencia_planilha import executar_com_retentativa
from services.planilha_eventos_mercado import ABAS_EVENTOS, gravar_eventos_planilha


class ApiError429(Exception):
    def __init__(self):
        self.response = type("Response", (), {"status_code": 429})()


class AbaEventos:
    def __init__(self, tipo, linhas):
        self.nome, self.cabecalho = ABAS_EVENTOS[tipo]
        self.linhas = linhas
        self.row_count = 1000
        self.added = 0
        self.atualizacoes = []

    def get_all_values(self):
        return self.linhas

    def add_rows(self, quantidade):
        self.added += quantidade
        self.row_count += quantidade

    def batch_update(self, dados, **_kwargs):
        self.atualizacoes.extend(dados)


class PlanilhaFake:
    def __init__(self, aba):
        self.aba = aba

    def worksheet(self, nome):
        assert nome == self.aba.nome
        return self.aba


class PlanilhaEspelhosResilientesTests(unittest.TestCase):
    def test_api_429_repete_operacao_com_backoff(self):
        chamadas = []
        pausas = []

        def operacao():
            chamadas.append(1)
            if len(chamadas) == 1:
                raise ApiError429()
            return "gravado"

        resultado = executar_com_retentativa(
            operacao, "teste", sleep=pausas.append,
        )
        self.assertEqual(resultado, "gravado")
        self.assertEqual(len(chamadas), 2)
        self.assertEqual(pausas, [2])

    def test_aba_de_proventos_expande_antes_da_linha_1001(self):
        _, cabecalho = ABAS_EVENTOS["provento"]
        linhas = [list(cabecalho)] + [[f"antigo-{i}"] for i in range(999)]
        aba = AbaEventos("provento", linhas)
        resultado = gravar_eventos_planilha([{
            "identificador": "novo-evento",
            "ticker": "BBAS3",
            "classe": "ACAO",
            "data_ex": "2026-11-25",
            "data_pagamento": None,
            "tipo": "DISTRIBUICAO",
            "valor_unitario": 0.25,
            "fonte": "CVM",
            "qualidade_fonte": "OFICIAL",
        }], [], planilha=PlanilhaFake(aba))
        self.assertEqual(resultado["proventos"], 1)
        self.assertEqual(aba.added, 1000)
        self.assertEqual(aba.atualizacoes[0]["range"], "A1001:K1001")


if __name__ == "__main__":
    unittest.main()
