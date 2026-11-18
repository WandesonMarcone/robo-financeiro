"""Limites e relato da fila documental sem acessar serviços externos."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from atualizador_documentos import ResultadoProcessamento, _selecionar_lote_documental


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


if __name__ == "__main__":
    unittest.main()
