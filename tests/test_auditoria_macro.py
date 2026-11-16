"""Falha parcial no BCB não pode aparecer como coleta concluída."""
import unittest
from unittest.mock import Mock, patch

from scripts import coletar_series_macro as rotina


class TesteAuditoriaMacro(unittest.TestCase):
    @patch.object(rotina, "concluir_evento")
    @patch.object(rotina, "registrar_resultado")
    @patch.object(rotina, "iniciar_evento", return_value=77)
    def test_parcial_invalida_execucao(self, iniciar, registrar, concluir):
        dados = {"series": {"SELIC_META": {"gravadas": 2}},
                 "falhas": [{"serie": "CDI", "erro": "HTTPError"}]}
        with self.assertRaisesRegex(RuntimeError, "CDI"):
            rotina.executar(coletor=Mock(return_value=dados))
        registrar.assert_called_once_with(77, dados)
        self.assertEqual(concluir.call_count, 1)
        self.assertFalse(concluir.call_args.kwargs["sucesso"])

    @patch.object(rotina, "concluir_evento")
    @patch.object(rotina, "iniciar_evento", return_value=77)
    def test_serie_vazia_falha(self, iniciar, concluir):
        with self.assertRaisesRegex(RuntimeError, "Nenhuma"):
            rotina.executar(coletor=Mock(return_value={"series": {}, "falhas": []}))
        self.assertFalse(concluir.call_args.kwargs["sucesso"])

    @patch.object(rotina, "concluir_evento")
    @patch.object(rotina, "registrar_resultado")
    @patch.object(rotina, "iniciar_evento", return_value=77)
    def test_todas_series_validas(self, iniciar, registrar, concluir):
        dados = {"series": {"IPCA": {"gravadas": 1}, "CDI": {"gravadas": 4}}, "falhas": []}
        self.assertEqual(rotina.executar(coletor=Mock(return_value=dados)), dados)
        self.assertTrue(concluir.call_args.kwargs["sucesso"])


if __name__ == "__main__":
    unittest.main()
