"""Regressão de cabeçalhos acentuados e CSV vazio do Tesouro."""
import unittest
from unittest.mock import patch

from services.coletor_tesouro_direto import coletar_tesouro_direto


class SessaoFalsa:
    def __init__(self):
        self.parametros = []

    def execute(self, _sql, parametros):
        self.parametros.append(parametros)

    def commit(self):
        pass

    def close(self):
        pass


class Resposta:
    def __init__(self, csv):
        self.content = csv.encode("utf-8")

    def raise_for_status(self):
        pass


class TesteTesouro(unittest.TestCase):
    def test_acentos_preservam_taxa_e_preco(self):
        csv = (
            "Data Base;Tipo Titulo;Data Vencimento;"
            "Taxa Compra Manhã;Taxa Venda Manhã;PU Compra Manhã;PU Venda Manhã\n"
            "15/11/2026;Tesouro Selic;01/01/2030;12,20;12,30;99,00;100,00\n"
            "16/11/2026;Tesouro Selic;01/01/2030;12,34;12,35;101,50;102,00\n"
        )
        sessao = SessaoFalsa()
        with patch("services.coletor_tesouro_direto.requests.get",
                   return_value=Resposta(csv)):
            resumo = coletar_tesouro_direto(session_factory=lambda: sessao)
        self.assertEqual(resumo["gravadas"], 1)
        self.assertEqual(resumo["referencia"], "2026-11-16")
        self.assertEqual(sessao.parametros[0]["taxa_compra"], 12.34)
        self.assertEqual(sessao.parametros[0]["preco_venda"], 102.0)

    def test_csv_somente_cabecalho_e_erro_visivel(self):
        with patch("services.coletor_tesouro_direto.requests.get",
                   return_value=Resposta("Data Base;Tipo Titulo\n")):
            with self.assertRaisesRegex(ValueError, "TESOURO_CSV_VAZIO"):
                coletar_tesouro_direto(session_factory=SessaoFalsa)


if __name__ == "__main__":
    unittest.main()
