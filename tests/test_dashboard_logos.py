"""Testes da apresentação de logos nos painéis de ativos (sem rede/DB)."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.dashboard_menus as dashboard  # noqa: E402


INDICADORES_FII = {
    "setor": "Logística",
    "preco": "100,00",
    "dy": "9,5%",
    "pvp": "0,95",
    "vpa": "105,00",
}


class _MensagemEnviada:
    def __init__(self, file_id=None):
        self.photo = [SimpleNamespace(file_id=file_id)] if file_id else None


class _BotFake:
    def __init__(self, falhar_foto=False, falhar_edicao_media=False,
                 falhar_edicao_texto=False):
        self.falhar_foto = falhar_foto
        self.falhar_edicao_media = falhar_edicao_media
        self.falhar_edicao_texto = falhar_edicao_texto
        self.fotos = []
        self.mensagens = []
        self.editadas = []
        self.medias_editadas = []

    def send_photo(self, chat_id, foto, **kwargs):
        if self.falhar_foto:
            raise RuntimeError("Telegram recusou a foto")
        self.fotos.append((chat_id, foto, kwargs))
        return _MensagemEnviada("FILE-ID-NOVO")

    def send_message(self, chat_id, texto, **kwargs):
        self.mensagens.append((chat_id, texto, kwargs))

    def edit_message_media(self, media, chat_id=None, message_id=None, **kwargs):
        if self.falhar_edicao_media:
            raise RuntimeError("mensagem atual não é mídia")
        self.medias_editadas.append((chat_id, message_id, media, kwargs))
        return _MensagemEnviada()

    def edit_message_text(self, texto, chat_id=None, message_id=None, **kwargs):
        if self.falhar_edicao_texto:
            raise RuntimeError("não há texto para editar")
        self.editadas.append((chat_id, message_id, texto, kwargs))


class TestPainelComLogo(unittest.TestCase):
    def setUp(self):
        self._patch_indicadores = mock.patch.object(
            dashboard, "buscar_ativo_na_planilha", return_value=dict(INDICADORES_FII)
        )
        self._patch_indicadores.start()
        self._patch_db = mock.patch.object(
            dashboard, "SessionDB", side_effect=RuntimeError("db desligado")
        )
        self._patch_db.start()
        self._patch_registrar = mock.patch.object(
            dashboard, "registrar_file_id_logo"
        )
        self.registrar = self._patch_registrar.start()
        self._patch_falha = mock.patch.object(
            dashboard, "registrar_falha_logo"
        )
        self.registrar_falha = self._patch_falha.start()
        self._patch_invalidar = mock.patch.object(
            dashboard, "invalidar_file_id_logo"
        )
        self.invalidar_file_id = self._patch_invalidar.start()

    def tearDown(self):
        self._patch_invalidar.stop()
        self._patch_falha.stop()
        self._patch_registrar.stop()
        self._patch_db.stop()
        self._patch_indicadores.stop()

    def _executar(self, bot_fake, file_id=None, url="https://logos/MXRF11.png", message_id=None):
        with mock.patch.object(dashboard, "bot", bot_fake), \
                mock.patch.object(dashboard, "obter_file_id_logo", return_value=file_id), \
                mock.patch.object(dashboard, "obter_link_logo", return_value=url) as link:
            dashboard.gerar_painel_ativo("MXRF11", "fii", 123, message_id)
        return link

    def test_envia_painel_com_bytes_do_drive(self):
        bot_fake = _BotFake()
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
        with mock.patch.object(
            dashboard, "obter_bytes_logo_drive", return_value=png
        ) as baixar:
            self._executar(bot_fake, url="drive:id-mxrf")
        baixar.assert_called_once_with("drive:id-mxrf")
        self.assertEqual(bot_fake.fotos[0][1], png)
        self.registrar.assert_called_once_with("MXRF11", "FILE-ID-NOVO")

    def test_envia_painel_como_foto_e_caption(self):
        bot_fake = _BotFake()
        link = self._executar(bot_fake, url="https://logos/MXRF11.png")

        self.assertEqual(len(bot_fake.fotos), 1)
        chat_id, foto, kwargs = bot_fake.fotos[0]
        self.assertEqual(chat_id, 123)
        self.assertEqual(foto, "https://logos/MXRF11.png")
        self.assertIn("MXRF11", kwargs["caption"])
        self.assertNotIn("\u200e", kwargs["caption"])
        callbacks = [
            b.callback_data
            for linha in kwargs["reply_markup"].keyboard
            for b in linha
        ]
        self.assertIn("dados_MXRF11_fii", callbacks)
        self.assertIn("docs_MXRF11_fii", callbacks)
        self.assertIn("ia_MXRF11_fii", callbacks)
        self.assertIn("menu_fiis", callbacks)
        # Emojis continuam nos teclados (imagens personalizadas não são suportadas).
        self.assertTrue(
            any("📎" in b.text for linha in kwargs["reply_markup"].keyboard for b in linha)
        )
        self.registrar.assert_called_once_with("MXRF11", "FILE-ID-NOVO")
        link.assert_called_once()

    def test_file_id_em_cache_evita_nova_resolucao(self):
        bot_fake = _BotFake()
        with mock.patch.object(dashboard, "bot", bot_fake), \
                mock.patch.object(dashboard, "obter_file_id_logo", return_value="FILE-ID-CACHE"), \
                mock.patch.object(dashboard, "obter_link_logo") as link:
            dashboard.gerar_painel_ativo("MXRF11", "fii", 123)
        self.assertEqual(bot_fake.fotos[0][1], "FILE-ID-CACHE")
        link.assert_not_called()

    def test_falha_no_envio_da_foto_usa_texto_com_prevía(self):
        bot_fake = _BotFake(falhar_foto=True)
        self._executar(bot_fake, url="https://logos/MXRF11.png")

        self.assertEqual(bot_fake.fotos, [])
        self.assertEqual(len(bot_fake.mensagens), 1)
        texto = bot_fake.mensagens[0][1]
        self.assertIn("MXRF11", texto)
        self.assertIn("https://logos/MXRF11.png", texto)

    def test_falha_ao_baixar_bytes_do_drive_usa_texto(self):
        bot_fake = _BotFake()
        with mock.patch.object(
            dashboard, "obter_bytes_logo_drive", return_value=None
        ):
            self._executar(bot_fake, url="drive:id-mxrf")
        self.assertEqual(bot_fake.fotos, [])
        self.assertEqual(len(bot_fake.mensagens), 1)
        self.assertIn("MXRF11", bot_fake.mensagens[0][1])

    def test_ativo_sem_logo_usa_painel_textual(self):
        bot_fake = _BotFake()
        self._executar(bot_fake, file_id=None, url="")

        self.assertEqual(bot_fake.fotos, [])
        self.assertEqual(len(bot_fake.mensagens), 1)
        self.assertIn("MXRF11", bot_fake.mensagens[0][1])

    def test_edicao_preserva_logo_quando_mensagem_e_foto(self):
        bot_fake = _BotFake()
        self._executar(bot_fake, url="https://logos/MXRF11.png", message_id=99)

        self.assertEqual(bot_fake.editadas, [])
        self.assertEqual(len(bot_fake.medias_editadas), 1)
        chat_id, message_id, media, kwargs = bot_fake.medias_editadas[0]
        self.assertEqual((chat_id, message_id), (123, 99))
        self.assertEqual(media.media, "https://logos/MXRF11.png")
        self.assertIn("MXRF11", media.caption)
        self.assertIn("dados_MXRF11_fii", [
            b.callback_data for linha in kwargs["reply_markup"].keyboard for b in linha
        ])

    def test_edicao_de_mensagem_de_texto_cai_para_edit_message_text(self):
        bot_fake = _BotFake(falhar_edicao_media=True)
        self._executar(bot_fake, url="https://logos/MXRF11.png", message_id=99)

        self.assertEqual(bot_fake.medias_editadas, [])
        self.assertEqual(len(bot_fake.editadas), 1)
        self.assertIn("https://logos/MXRF11.png", bot_fake.editadas[0][2])

    def test_rejeicao_de_file_id_na_edicao_invalida_somente_o_cache_do_telegram(self):
        bot_fake = _BotFake(falhar_edicao_media=True)
        self._executar(
            bot_fake, file_id="FILE-ID-EXPIRADO", url="", message_id=99
        )

        self.invalidar_file_id.assert_called_once()
        self.assertEqual(self.invalidar_file_id.call_args.args[0], "MXRF11")
        self.registrar_falha.assert_not_called()

    def test_rejeicao_de_file_id_no_envio_invalida_somente_o_cache_do_telegram(self):
        bot_fake = _BotFake(falhar_foto=True)
        self._executar(bot_fake, file_id="FILE-ID-EXPIRADO", url="")

        self.invalidar_file_id.assert_called_once()
        self.assertEqual(self.invalidar_file_id.call_args.args[0], "MXRF11")
        self.registrar_falha.assert_not_called()
        self.assertEqual(len(bot_fake.mensagens), 1)

    def test_falha_ao_editar_texto_envia_novo_painel_sem_quebrar(self):
        bot_fake = _BotFake(
            falhar_edicao_media=True, falhar_edicao_texto=True
        )
        self._executar(
            bot_fake, url="https://logos/MXRF11.png", message_id=99
        )

        self.assertEqual(bot_fake.editadas, [])
        self.assertEqual(len(bot_fake.mensagens), 1)
        self.assertIn("MXRF11", bot_fake.mensagens[0][1])

    def test_indicadores_ausentes_nao_quebram_o_fluxo(self):
        self._patch_indicadores.stop()
        bot_fake = _BotFake()
        with mock.patch.object(dashboard, "buscar_ativo_na_planilha", return_value=None), \
                mock.patch.object(dashboard, "bot", bot_fake):
            dashboard.gerar_painel_ativo("XXXX99", "acao", 123)
        self._patch_indicadores.start()
        self.assertEqual(len(bot_fake.mensagens), 1)
        self.assertIn("XXXX99", bot_fake.mensagens[0][1])


if __name__ == "__main__":
    unittest.main()
