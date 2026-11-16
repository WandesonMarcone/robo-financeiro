"""Coleta Tesouro: registro durável e erro observável no histórico."""
import unittest
from unittest.mock import Mock, patch

from scripts import coletar_tesouro_direto as rotina


class TesteAuditoriaTesouro(unittest.TestCase):
    @patch.object(rotina, "concluir_evento")
    @patch.object(rotina, "registrar_resultado")
    @patch.object(rotina, "iniciar_evento", return_value=42)
    def test_gravacao_valida_registra_conclusao(self, iniciar, registrar, concluir):
        dados = {"gravadas": 3, "referencia": "2026-11-16"}
        self.assertEqual(rotina.executar(coletor=Mock(return_value=dados)), dados)
        registrar.assert_called_once_with(42, dados)
        self.assertTrue(concluir.call_args.kwargs["sucesso"])

    @patch.object(rotina, "concluir_evento")
    @patch.object(rotina, "iniciar_evento", return_value=42)
    def test_sem_titulos_nao_e_sucesso(self, iniciar, concluir):
        with self.assertRaises(ValueError):
            rotina.executar(coletor=Mock(return_value={"gravadas": 0}))
        self.assertFalse(concluir.call_args.kwargs["sucesso"])

    @patch.object(rotina, "concluir_evento")
    @patch.object(rotina, "iniciar_evento", return_value=42)
    def test_falha_da_fonte_fica_no_historico(self, iniciar, concluir):
        with self.assertRaises(TimeoutError):
            rotina.executar(coletor=Mock(side_effect=TimeoutError()))
        self.assertEqual(concluir.call_args.kwargs["erro"], "TimeoutError")


if __name__ == "__main__":
    unittest.main()
