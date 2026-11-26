import unittest

from atualizador_documentos import auditar_documentos_drive


class _Campo:
    def asc(self):
        return self


class _Documento:
    id = _Campo()

    def __init__(self, identificador, url):
        self.id = identificador
        self.url_pdf = url
        self.ativo_id = identificador
        self.tipo_documento = "RELATORIO"
        self.assunto = "2026-11-01"
        self.data_publicacao = None
        self.texto_extraido = "texto"
        self.status_processamento = "SALVO_DRIVE"


class _Consulta:
    def __init__(self, documentos):
        self.documentos = documentos

    def order_by(self, *_args):
        return self

    def all(self):
        return list(self.documentos)


class _Sessao:
    def __init__(self, documentos):
        self.documentos = documentos
        self.apagados = []

    def query(self, _modelo):
        return _Consulta(self.documentos)

    def delete(self, documento):
        self.apagados.append(documento.id)

    def commit(self):
        return None

    def rollback(self):
        return None


class _DriveIndisponivel:
    def arquivo_existe(self, _file_id):
        return None


class AuditoriaDriveSeguraTests(unittest.TestCase):
    def test_erro_de_consulta_no_drive_nao_apaga_documento(self):
        sessao = _Sessao([_Documento(1, "https://drive.google.com/file/d/abc/view")])
        resumo = auditar_documentos_drive(session=sessao, drive_manager=_DriveIndisponivel())
        self.assertEqual([], sessao.apagados)
        self.assertEqual(1, resumo["falhas"])


if __name__ == "__main__":
    unittest.main()
