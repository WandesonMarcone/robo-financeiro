"""Regressão da contingência FNET e seu registro de falhas no histórico."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts import varredura_fnet_diaria as rotina


class TesteContingenciaFnet(unittest.TestCase):
    def _coletor(self, status="gravado", falhas=0, erro=None):
        resultado = SimpleNamespace(
            status=status, falhas_persistencia=falhas, erro=erro,
            detalhes_painel=lambda: {"status": status, "falhas_persistencia": falhas},
            mensagem_telegram=lambda: "Resumo FNET",
        )
        return SimpleNamespace(coletar=Mock(return_value=resultado))

    @patch.object(rotina, "concluir_evento")
    @patch.object(rotina, "registrar_resultado")
    @patch.object(rotina, "iniciar_evento", return_value=123)
    def test_sucesso_registra_resultado(self, iniciar, registrar, concluir):
        resultado = rotina.executar(self._coletor())
        self.assertEqual(resultado["status"], "gravado")
        self.assertEqual(registrar.call_count, 1)
        self.assertTrue(concluir.call_args.kwargs["sucesso"])

    @patch.object(rotina, "concluir_evento")
    @patch.object(rotina, "registrar_resultado")
    @patch.object(rotina, "iniciar_evento", return_value=123)
    def test_falha_parcial_nao_aparece_como_concluida(self, iniciar, registrar, concluir):
        with self.assertRaises(RuntimeError):
            rotina.executar(self._coletor(falhas=1))
        self.assertEqual(concluir.call_count, 1)
        self.assertFalse(concluir.call_args.kwargs["sucesso"])

    @patch.object(rotina, "concluir_evento")
    @patch.object(rotina, "iniciar_evento", return_value=123)
    def test_excecao_na_coleta_encerra_evento(self, iniciar, concluir):
        coletor = SimpleNamespace(coletar=Mock(side_effect=TimeoutError()))
        with self.assertRaises(TimeoutError):
            rotina.executar(coletor)
        self.assertFalse(concluir.call_args.kwargs["sucesso"])


if __name__ == "__main__":
    unittest.main()
