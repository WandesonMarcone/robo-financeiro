"""Testes do serviço de logos (sem rede real).

Cobrem Drive (Ícones B3) → Logo.dev → texto, identidade PETR3/PETR4,
validação de imagem, duplicatas, cache e file_id do Telegram.
"""

import io
import logging
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if "googleapiclient" not in sys.modules:
    _google_http = mock.MagicMock()
    sys.modules.setdefault("google", mock.MagicMock())
    sys.modules.setdefault("google.oauth2", mock.MagicMock())
    sys.modules.setdefault("google.oauth2.credentials", mock.MagicMock())
    sys.modules.setdefault("googleapiclient", mock.MagicMock())
    sys.modules.setdefault("googleapiclient.discovery", mock.MagicMock())
    sys.modules.setdefault("googleapiclient.http", _google_http)

import requests  # noqa: E402

from services import logo_service  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
JPEG = b"\xff\xd8\xff" + b"\x00" * 24
HTML = b"<html>cloudflare</html>"


def _resposta(status=200, content=PNG, content_type="image/png"):
    return SimpleNamespace(
        status_code=status,
        headers={"Content-Type": content_type} if content_type else {},
        content=content,
        close=lambda: None,
    )


class FakeDrive:
    def __init__(self, arquivos=None, falha_busca=False, falha_salvar=False, falha_baixar=False):
        self.arquivos = dict(arquivos or {})
        self.buscas = []
        self.saves = []
        self.downloads = []
        self.falha_busca = falha_busca
        self.falha_salvar = falha_salvar
        self.falha_baixar = falha_baixar

    def buscar_logo_catalogo(self, ticker, tipo=""):
        self.buscas.append((ticker, tipo))
        if self.falha_busca:
            raise PermissionError("sem permissao no Drive")
        achado = self.arquivos.get((ticker, tipo)) or self.arquivos.get(ticker)
        return achado

    def salvar_logo_catalogo(self, ticker, conteudo_bytes, tipo="", mime_type="image/png"):
        self.saves.append((ticker, tipo, mime_type, len(conteudo_bytes or b"")))
        if self.falha_salvar:
            raise PermissionError("sem permissao de escrita")
        chave = (ticker, tipo)
        if chave in self.arquivos:
            return self.arquivos[chave]
        novo = {"id": f"id-{ticker}", "name": f"{ticker}.png", "mimeType": mime_type}
        self.arquivos[chave] = novo
        return novo

    def baixar_logo_catalogo(self, file_id):
        self.downloads.append(file_id)
        if self.falha_baixar:
            raise RuntimeError("download falhou")
        return PNG


class _RepoFake:
    def chave_canonica(self, ticker):
        return ticker

    def obter_file_id(self, ticker, agora=None):
        return None

    def registrar_file_id(self, ticker, file_id, url_origem=None):
        return file_id

    def registrar_falha(self, ticker, erro=None, url_origem=None, ttl_segundos=None):
        return None


class TestLogoService(unittest.TestCase):
    def setUp(self):
        logo_service.limpar_cache_logos()
        logo_service.definir_repositorio_logos(_RepoFake())
        self._token = mock.patch.dict(
            os.environ, {"LOGO_DEV_TOKEN": "token-secreto-xyz"}, clear=False
        )
        self._token.start()

    def tearDown(self):
        self._token.stop()
        logo_service.definir_repositorio_logos(None)
        logo_service.limpar_cache_logos()

    def test_drive_tem_logo_e_nao_consulta_logo_dev(self):
        drive = FakeDrive({"PETR4": {"id": "drv-petr", "name": "PETR4.png"}})
        with mock.patch.object(logo_service.requests, "get") as get:
            url = logo_service.obter_link_logo("PETR4", "acao", drive_manager=drive)
        self.assertEqual(url, "drive:drv-petr")
        get.assert_not_called()
        self.assertEqual(drive.buscas[0][0], "PETR4")
        self.assertEqual(drive.saves, [])

    def test_petr3_reutiliza_identidade_da_petr4_no_drive(self):
        drive = FakeDrive({"PETR4": {"id": "drv-petr", "name": "PETR4.png"}})
        url = logo_service.obter_link_logo("PETR3", "acao", drive_manager=drive)
        self.assertEqual(url, "drive:drv-petr")
        self.assertEqual(drive.buscas[0][0], "PETR4")

    def test_ausente_no_drive_consulta_logo_dev_e_grava(self):
        drive = FakeDrive()
        with mock.patch.object(
            logo_service.requests, "get", return_value=_resposta(200, PNG)
        ) as get:
            url = logo_service.obter_link_logo("VALE3", "acao", drive_manager=drive)
        self.assertEqual(url, "drive:id-VALE3")
        self.assertTrue(get.called)
        self.assertEqual(len(drive.saves), 1)
        self.assertEqual(drive.saves[0][0], "VALE3")

    def test_nao_grava_duplicata_quando_drive_ja_tem(self):
        drive = FakeDrive({"MXRF11": {"id": "drv-mxrf", "name": "MXRF11.png"}})
        with mock.patch.object(logo_service.requests, "get") as get:
            logo_service.obter_link_logo("MXRF11", "fii", drive_manager=drive)
        get.assert_not_called()
        self.assertEqual(drive.saves, [])

    def test_imagem_invalida_do_logo_dev_nao_e_salva(self):
        drive = FakeDrive()
        with mock.patch.object(
            logo_service.requests,
            "get",
            return_value=_resposta(200, HTML, "text/html"),
        ):
            url = logo_service.obter_link_logo("ITUB4", "acao", drive_manager=drive)
        self.assertEqual(url, "")
        self.assertEqual(drive.saves, [])

    def test_http_erro_timeout_e_rede_nao_interrompem(self):
        drive = FakeDrive()
        with mock.patch.object(
            logo_service.requests, "get", return_value=_resposta(500, b"err")
        ):
            self.assertEqual(
                logo_service.obter_link_logo("WEGE3", "acao", drive_manager=drive), ""
            )
        logo_service.limpar_cache_logos()
        with mock.patch.object(
            logo_service.requests,
            "get",
            side_effect=requests.Timeout("estourou"),
        ):
            self.assertEqual(
                logo_service.obter_link_logo("BBAS3", "acao", drive_manager=drive), ""
            )
        logo_service.limpar_cache_logos()
        with mock.patch.object(
            logo_service.requests,
            "get",
            side_effect=requests.ConnectionError("fora"),
        ):
            self.assertEqual(
                logo_service.obter_link_logo("ABEV3", "acao", drive_manager=drive), ""
            )

    def test_falha_de_permissao_no_drive_cai_para_logo_dev(self):
        drive = FakeDrive(falha_busca=True, falha_salvar=True)
        with mock.patch.object(
            logo_service.requests, "get", return_value=_resposta(200, PNG)
        ):
            url = logo_service.obter_link_logo("VALE3", "acao", drive_manager=drive)
        self.assertIn("img.logo.dev", url)
        self.assertIn("VALE3.SA", url)

    def test_escrita_drive_falha_ainda_usa_logo_dev(self):
        drive = FakeDrive(falha_salvar=True)
        with mock.patch.object(
            logo_service.requests, "get", return_value=_resposta(200, PNG)
        ):
            url = logo_service.obter_link_logo("VALE3", "acao", drive_manager=drive)
        self.assertIn("img.logo.dev", url)

    def test_sem_token_e_sem_drive_retorna_vazio(self):
        drive = FakeDrive()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LOGO_DEV_TOKEN", None)
            url = logo_service.obter_link_logo("XXXX99", "acao", drive_manager=drive)
        self.assertEqual(url, "")

    def test_file_id_do_telegram_tem_prioridade(self):
        drive = FakeDrive({"PETR4": {"id": "drv-petr"}})
        logo_service.registrar_file_id_logo("PETR3", "FILE-ID-PETR")
        with mock.patch.object(logo_service.requests, "get") as get:
            self.assertEqual(
                logo_service.obter_media_logo("PETR3", drive_manager=drive),
                "FILE-ID-PETR",
            )
            self.assertEqual(
                logo_service.obter_media_logo("PETR4", drive_manager=drive),
                "FILE-ID-PETR",
            )
        get.assert_not_called()
        self.assertEqual(drive.buscas, [])

    def test_cache_positivo_evita_novas_consultas(self):
        drive = FakeDrive({"VALE3": {"id": "drv-vale"}})
        primeira = logo_service.obter_link_logo("VALE3", "acao", drive_manager=drive)
        segunda = logo_service.obter_link_logo("VALE3", "acao", drive_manager=drive)
        self.assertEqual(primeira, segunda)
        self.assertEqual(len(drive.buscas), 1)

    def test_bytes_drive_para_telegram(self):
        drive = FakeDrive()
        dados = logo_service.obter_bytes_logo_drive("drive:abc", drive_manager=drive)
        self.assertEqual(dados, PNG)
        self.assertEqual(drive.downloads, ["abc"])
        self.assertIsNone(logo_service.obter_bytes_logo_drive("https://x"))

    def test_token_nao_aparece_em_logs(self):
        drive = FakeDrive()
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger = logging.getLogger("robo.logos")
        logger.addHandler(handler)
        antigo = logger.level
        logger.setLevel(logging.DEBUG)
        try:
            with mock.patch.object(
                logo_service.requests, "get", return_value=_resposta(404, b"x")
            ):
                logo_service.obter_link_logo("VALE3", "acao", drive_manager=drive)
        finally:
            logger.removeHandler(handler)
            logger.setLevel(antigo)
        self.assertNotIn("token-secreto-xyz", stream.getvalue())

    def test_falha_de_logo_nao_propaga(self):
        drive = FakeDrive(falha_busca=True)
        with mock.patch.object(
            logo_service.requests,
            "get",
            side_effect=RuntimeError("boom"),
        ):
            self.assertEqual(
                logo_service.obter_link_logo("ITUB4", "acao", drive_manager=drive),
                "",
            )

    def test_media_rapida_usa_drive_sem_logo_dev(self):
        drive = FakeDrive({"VALE3": {"id": "drv-vale"}})
        with mock.patch.object(
            logo_service, "_resolver_drive_manager", return_value=drive
        ), mock.patch.object(logo_service.requests, "get") as get:
            url = logo_service.obter_media_logo_rapida("VALE3", "acao")
        self.assertEqual(url, "drive:drv-vale")
        get.assert_not_called()

    def test_normaliza_ticker_com_sufixo_de_callback(self):
        drive = FakeDrive({"MXRF11": {"id": "drv-mxrf"}})
        url = logo_service.obter_link_logo("MXRF11_fii", "fii", drive_manager=drive)
        self.assertEqual(url, "drive:drv-mxrf")

    def test_mime_png_jpeg_rejeita_html(self):
        self.assertEqual(logo_service._mime_imagem(PNG), "image/png")
        self.assertEqual(logo_service._mime_imagem(JPEG), "image/jpeg")
        self.assertIsNone(logo_service._mime_imagem(HTML, "text/html"))
        self.assertIsNone(logo_service._mime_imagem(b"x"))


class TestCatalogoDriveLogos(unittest.TestCase):
    def _gerente(self, listagens, get_meta=None, creates=None):
        from modules import GoogleDriveManager as gdm

        gerente = gdm.GoogleDriveManager.__new__(gdm.GoogleDriveManager)
        gerente.root_folder_id = "PASTA-DADOS-FINANCEIROS"
        lista = list(listagens)

        class _Files:
            def list(self, **kwargs):
                return SimpleNamespace(execute=lambda: {"files": lista.pop(0) if lista else []})

            def get(self, **kwargs):
                return SimpleNamespace(execute=lambda: get_meta)

            def create(self, **kwargs):
                creates.append(kwargs) if creates is not None else None
                return SimpleNamespace(
                    execute=lambda: {"id": "novo-id", "name": kwargs["body"]["name"]}
                )

        gerente.service = SimpleNamespace(files=lambda: _Files())
        return gerente

    def test_atalho_resolve_pasta_destino(self):
        from modules import GoogleDriveManager as gdm

        gerente = gdm.GoogleDriveManager.__new__(gdm.GoogleDriveManager)
        gerente.root_folder_id = "PASTA-DADOS"

        metas = [
            {
                "id": "atalho",
                "name": "Ícones B3",
                "mimeType": "application/vnd.google-apps.shortcut",
                "shortcutDetails": {"targetId": "destino-real"},
            },
            {
                "id": "destino-real",
                "name": "Ícones B3",
                "mimeType": "application/vnd.google-apps.folder",
            },
        ]

        class _Files:
            def get(self, **kwargs):
                meta = metas.pop(0)
                return SimpleNamespace(execute=lambda m=meta: m)

        gerente.service = SimpleNamespace(files=lambda: _Files())
        resolvido = gerente.resolver_pasta_logos("atalho")
        self.assertEqual(resolvido["id"], "destino-real")
        self.assertEqual(resolvido["name"], "Ícones B3")

    def test_recusa_misturar_com_dados_financeiros(self):
        from modules import GoogleDriveManager as gdm

        gerente = gdm.GoogleDriveManager.__new__(gdm.GoogleDriveManager)
        gerente.root_folder_id = "MESMO-ID"

        class _Files:
            def get(self, **kwargs):
                return SimpleNamespace(
                    execute=lambda: {
                        "id": "MESMO-ID",
                        "name": "Dados Financeiros",
                        "mimeType": "application/vnd.google-apps.folder",
                    }
                )

        gerente.service = SimpleNamespace(files=lambda: _Files())
        self.assertIsNone(gerente._subpasta_logos("acao", criar=False))

    def test_busca_por_subpasta_acoes_e_fiis(self):
        from modules import GoogleDriveManager as gdm

        gerente = gdm.GoogleDriveManager.__new__(gdm.GoogleDriveManager)
        gerente.root_folder_id = "DADOS"
        chamadas = []

        class _Files:
            def get(self, **kwargs):
                return SimpleNamespace(
                    execute=lambda: {
                        "id": "ICONES",
                        "name": "Ícones B3",
                        "mimeType": "application/vnd.google-apps.folder",
                    }
                )

            def list(self, **kwargs):
                chamadas.append(kwargs["q"])
                if "Ações" in kwargs["q"] or "FIIs" in kwargs["q"]:
                    return SimpleNamespace(
                        execute=lambda: {"files": [{"id": "sub", "name": "x"}]}
                    )
                if "PETR4.png" in kwargs["q"]:
                    return SimpleNamespace(
                        execute=lambda: {"files": [{"id": "arq", "name": "PETR4.png"}]}
                    )
                return SimpleNamespace(execute=lambda: {"files": []})

        gerente.service = SimpleNamespace(files=lambda: _Files())
        achado = gerente.buscar_logo_catalogo("PETR4", "acao")
        self.assertEqual(achado["id"], "arq")
        self.assertTrue(any("Ações" in q for q in chamadas))

    def test_salvar_nao_sobrescreve_nem_torna_publico(self):
        from modules import GoogleDriveManager as gdm

        gerente = gdm.GoogleDriveManager.__new__(gdm.GoogleDriveManager)
        gerente.root_folder_id = "DADOS"
        cria = []
        perms = []

        class _Files:
            def get(self, **kwargs):
                return SimpleNamespace(
                    execute=lambda: {
                        "id": "ICONES",
                        "name": "Ícones B3",
                        "mimeType": "application/vnd.google-apps.folder",
                    }
                )

            def list(self, **kwargs):
                if "VALE3.png" in kwargs["q"]:
                    return SimpleNamespace(
                        execute=lambda: {"files": [{"id": "ja-existe", "name": "VALE3.png"}]}
                    )
                return SimpleNamespace(
                    execute=lambda: {"files": [{"id": "sub-acoes", "name": "Ações"}]}
                )

            def create(self, **kwargs):
                cria.append(kwargs)
                return SimpleNamespace(execute=lambda: {"id": "novo"})

        class _Perms:
            def create(self, **kwargs):
                perms.append(kwargs)
                return SimpleNamespace(execute=lambda: {})

        gerente.service = SimpleNamespace(files=lambda: _Files(), permissions=lambda: _Perms())
        existente = gerente.salvar_logo_catalogo("VALE3", PNG, tipo="acao")
        self.assertEqual(existente["id"], "ja-existe")
        self.assertEqual(cria, [])
        self.assertEqual(perms, [])


if __name__ == "__main__":
    unittest.main()
