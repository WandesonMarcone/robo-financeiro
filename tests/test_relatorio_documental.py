import unittest
from types import SimpleNamespace

from services.relatorio_documental import mensagens_telegram_documentais


class TestRelatorioDocumental(unittest.TestCase):
    def test_lista_ticker_tipo_e_data_no_relatorio(self):
        resultado = SimpleNamespace(
            mensagem_telegram=lambda: "Resumo da coleta",
            detalhes_painel=lambda: {
                "novos": 2,
                "documentos": [
                    {"ticker": "MXRF11", "tipo": "Relatório Gerencial", "data": "2026-11-18"},
                    {"ticker": "BBAS3", "tipo": "Demonstrações Financeiras", "data": "2026-09-30"},
                ],
            },
        )

        mensagens = mensagens_telegram_documentais(resultado)

        texto = "\n".join(mensagens)
        self.assertIn("Resumo da coleta", texto)
        self.assertIn("MXRF11 — Relatório Gerencial — 2026-11-18", texto)
        self.assertIn("BBAS3 — Demonstrações Financeiras — 2026-09-30", texto)

    def test_quebra_sem_estourar_limite_telegram(self):
        documentos = [
            {"ticker": "MXRF11", "tipo": "Relatório Gerencial muito detalhado", "data": "2026-11-18"}
            for _ in range(180)
        ]
        resultado = SimpleNamespace(
            mensagem_telegram=lambda: "Resumo",
            detalhes_painel=lambda: {"novos": len(documentos), "documentos": documentos},
        )

        mensagens = mensagens_telegram_documentais(resultado)

        self.assertGreater(len(mensagens), 2)
        self.assertTrue(all(len(mensagem) <= 3500 for mensagem in mensagens))


if __name__ == "__main__":
    unittest.main()
