"""Regressões para indisponibilidades temporárias da CVM."""

import unittest
from unittest.mock import Mock, patch

import requests

from atualizador_documentos import _baixar_pdf_cvm


class TesteDownloadCvmResiliente(unittest.TestCase):
    @patch("atualizador_documentos.time.sleep")
    @patch("atualizador_documentos.requests.get")
    def test_repete_timeout_e_recupera(self, get, _sleep):
        sucesso = Mock(status_code=200, content=b"%PDF-ok")
        get.side_effect = [requests.Timeout("CVM lenta"), sucesso]

        conteudo, erro, temporario = _baixar_pdf_cvm("https://cvm/doc.pdf")

        self.assertEqual(conteudo, b"%PDF-ok")
        self.assertIsNone(erro)
        self.assertFalse(temporario)
        self.assertEqual(get.call_count, 2)

    @patch("atualizador_documentos.time.sleep")
    @patch("atualizador_documentos.requests.get")
    def test_timeout_persistente_fica_para_proxima_rodada(self, get, _sleep):
        get.side_effect = requests.Timeout("CVM lenta")

        conteudo, erro, temporario = _baixar_pdf_cvm(
            "https://cvm/doc.pdf", tentativas=3
        )

        self.assertIsNone(conteudo)
        self.assertIn("Timeout", erro)
        self.assertTrue(temporario)
        self.assertEqual(get.call_count, 3)

    @patch("atualizador_documentos.requests.get")
    def test_erro_definitivo_nao_e_repetido(self, get):
        get.return_value = Mock(status_code=404, content=b"")

        conteudo, erro, temporario = _baixar_pdf_cvm("https://cvm/doc.pdf")

        self.assertIsNone(conteudo)
        self.assertEqual(erro, "HTTP 404")
        self.assertFalse(temporario)
        get.assert_called_once()


if __name__ == "__main__":
    unittest.main()
