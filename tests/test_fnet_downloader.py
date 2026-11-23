import unittest
from unittest.mock import Mock

from fnet_scraper import FnetDownloader


class TesteFnetDownloader(unittest.TestCase):
    def _downloader(self, conteudo, content_type="application/octet-stream"):
        resposta = Mock()
        resposta.headers = {"Content-Type": content_type}
        resposta.content = conteudo
        resposta.raise_for_status.return_value = None
        downloader = FnetDownloader()
        downloader.session.cookies.set("sessao", "ativa")
        downloader.session.get = Mock(return_value=resposta)
        return downloader

    def test_identifica_formato_estruturado_sem_pdf(self):
        downloader = self._downloader(b"PK\\x03\\x04arquivo-estruturado")

        self.assertIsNone(downloader.baixar_pdf("123"))
        self.assertEqual(downloader.ultimo_erro, "FORMATO_NAO_PDF")

    def test_pdf_valido_limpa_erro_anterior(self):
        downloader = self._downloader(b"%PDF-1.7\\nconteudo")
        downloader.ultimo_erro = "ERRO_ANTERIOR"

        self.assertTrue(downloader.baixar_pdf("124").startswith(b"%PDF"))
        self.assertIsNone(downloader.ultimo_erro)

    def test_html_continua_sendo_falha_da_fonte(self):
        downloader = self._downloader(b"<html></html>", "text/html")

        self.assertIsNone(downloader.baixar_pdf("125"))
        self.assertEqual(downloader.ultimo_erro, "RESPOSTA_INVALIDA")


if __name__ == "__main__":
    unittest.main()
