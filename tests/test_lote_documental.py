"""Limites e relato da fila documental sem acessar serviços externos."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from atualizador_documentos import (
    ResultadoProcessamento,
    _nome_revisao,
    _selecionar_lote_documental,
    enviar_alerta_revisao_telegram,
)


class TesteLoteDocumental(unittest.TestCase):
    def test_lote_limita_consulta_e_preserva_total(self):
        consulta = Mock()
        consulta.count.return_value = 225
        consulta.order_by.return_value.limit.return_value.all.return_value = [
            SimpleNamespace(id=11), SimpleNamespace(id=12)
        ]
        total, ids = _selecionar_lote_documental(consulta, 500)
        self.assertEqual((total, ids), (225, [11, 12]))
        consulta.order_by.return_value.limit.assert_called_once_with(20)

    def test_relato_distingue_total_de_lote(self):
        resultado = ResultadoProcessamento("PENDENTE")
        resultado.fila = 225
        resultado.lote = 20
        resultado.processados = 18
        texto = resultado.mensagem_telegram()
        self.assertIn("Na fila: 225", texto)
        self.assertIn("Selecionados neste lote: 20", texto)
        self.assertIn("Processados: 18", texto)

    def test_nome_revisao_distingue_documentos_da_mesma_data(self):
        primeiro = _nome_revisao(
            "BTCI11", "Assembleia Geral", "04-11-2026 10:00", "1339000"
        )
        segundo = _nome_revisao(
            "BTCI11", "Assembleia Geral", "04-11-2026 10:00", "1339001"
        )
        self.assertNotEqual(primeiro, segundo)
        self.assertTrue(primeiro.endswith("_1339000.pdf"))

    @patch("services.historico_operacional.registrar_notificacao")
    @patch("atualizador_documentos._enviar_mensagem_telegram")
    @patch("atualizador_documentos._chat_administrador", return_value="123")
    def test_alerta_revisao_aceita_checagens_em_dicionarios(
        self, _chat, enviar_mensagem, _registrar
    ):
        enviar_mensagem.return_value = True

        entregue = enviar_alerta_revisao_telegram(
            "KNRI11",
            "Relatorio Gerencial",
            "https://drive.google.com/file/d/arquivo/view",
            "arquivo",
            6318,
            checagens=(
                {"tipo": "Relatorio Gerencial", "confianca": 80},
                {"tipo": "Outros", "confianca": 65},
            ),
        )

        self.assertTrue(entregue)
        mensagem = enviar_mensagem.call_args.args[1]
        self.assertIn("`Relatorio Gerencial` (80%)", mensagem)
        self.assertIn("`Outros` (65%)", mensagem)


if __name__ == "__main__":
    unittest.main()
