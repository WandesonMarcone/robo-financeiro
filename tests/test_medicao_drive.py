"""Uma medição parcial do Drive retoma sem contar páginas duas vezes."""
import unittest
from unittest.mock import patch

from modules.GoogleDriveManager import GoogleDriveManager


class Resposta:
    def __init__(self, dados):
        self.dados = dados

    def execute(self):
        return self.dados


class DriveFalso:
    def __init__(self):
        self.paginas = []

    def about(self):
        return self

    def get(self, **_kwargs):
        return Resposta({"storageQuota": {"usage": "1000", "limit": "2000"}})

    def files(self):
        return self

    def list(self, **kwargs):
        pasta = kwargs["q"].split("'")[1]
        pagina = kwargs["pageToken"]
        self.paginas.append((pasta, pagina))
        if pasta == "raiz" and pagina is None:
            return Resposta({
                "nextPageToken": "segunda",
                "files": [
                    {"id": "subpasta", "mimeType": "application/vnd.google-apps.folder"},
                    {"id": "pdf1", "mimeType": "application/pdf", "size": "10"},
                ],
            })
        if pasta == "raiz" and pagina == "segunda":
            return Resposta({"files": [
                {"id": "pdf2", "mimeType": "application/pdf", "size": "20"}
            ]})
        if pasta == "subpasta" and pagina is None:
            return Resposta({"files": [
                {"id": "outro", "mimeType": "text/plain", "size": "5"}
            ]})
        raise AssertionError((pasta, pagina))


class TesteMedicaoDrive(unittest.TestCase):
    def test_retomada_apos_prazo_nao_duplica_arquivos(self):
        gerente = GoogleDriveManager.__new__(GoogleDriveManager)
        gerente.root_folder_id = "raiz"
        gerente.service = DriveFalso()
        estado = {}
        with patch("time.monotonic", side_effect=[0, 0, 5]):
            parcial = gerente.medir_armazenamento_robo(5, estado)
        self.assertFalse(parcial["medicao_concluida"])
        self.assertEqual(parcial["arquivos"], 1)

        with patch("time.monotonic", return_value=0):
            final = gerente.medir_armazenamento_robo(5, estado)
        self.assertTrue(final["medicao_concluida"])
        self.assertEqual(final["robo_bytes"], 35)
        self.assertEqual(final["arquivos"], 3)
        self.assertEqual(final["pdfs"], 2)
        self.assertEqual(final["pastas"], 1)
        self.assertEqual(gerente.service.paginas, [
            ("raiz", None), ("subpasta", None), ("raiz", "segunda")
        ])


if __name__ == "__main__":
    unittest.main()
