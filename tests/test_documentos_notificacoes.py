"""Testes da distribuição individual de documentos.

Nenhuma rede é usada: o envio ao Telegram é substituído por um fake e a lista
de destinatários é injetada. O objetivo é garantir que documentos só sejam
enviados a usuários com vínculo persistente com o ativo (nunca em broadcast).
"""

import os
import sys
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import atualizador_documentos as ad  # noqa: E402


class TestNotificacaoDocumentos(unittest.TestCase):
    def test_envia_apenas_para_seguidores_com_chat(self):
        destinatarios = [
            SimpleNamespace(telegram_chat_id=111, telegram_user_id=111),
            SimpleNamespace(telegram_chat_id=None, telegram_user_id=222),
            SimpleNamespace(telegram_chat_id=None, telegram_user_id=None),
        ]
        enviados = []

        def _fake_enviar(chat_id, mensagem, teclado=None, parse_mode=None):
            enviados.append((chat_id, mensagem, teclado))
            return True

        with mock.patch.object(
            ad, "_destinatarios_do_ativo", return_value=destinatarios
        ), mock.patch.object(ad, "_enviar_mensagem_telegram", _fake_enviar):
            total = ad.notificar_documento_disponivel(
                ativo_id=10,
                ticker="MXRF11",
                nome_doc="Relatório Gerencial",
                data_publicacao=datetime(2026, 10, 17),
                url_pdf="https://exemplo/arquivo.pdf",
            )

        self.assertEqual(total, 2)
        self.assertEqual([c for (c, _m, _t) in enviados], [111, 222])
        texto = enviados[0][1]
        for trecho in ("MXRF11", "Relatório Gerencial", "17/10/2026", "https://exemplo/arquivo.pdf"):
            self.assertIn(trecho, texto)
        self.assertEqual(
            enviados[0][2]["inline_keyboard"][0][0]["callback_data"],
            "novos_documentos",
        )

    def test_envia_foto_com_legenda_quando_ha_logo(self):
        destinatarios = [SimpleNamespace(telegram_chat_id=111, telegram_user_id=111)]
        fotos = []
        mensagens = []

        def _fake_foto(chat_id, ticker, foto, legenda, teclado=None, parse_mode=None):
            fotos.append((chat_id, ticker, foto, legenda))
            return True

        def _fake_msg(chat_id, mensagem, teclado=None, parse_mode=None):
            mensagens.append(chat_id)
            return True

        with mock.patch.object(
            ad, "_destinatarios_do_ativo", return_value=destinatarios
        ), mock.patch.object(
            ad, "obter_media_logo_rapida", return_value="https://logos/MXRF11.png"
        ), mock.patch.object(
            ad, "_enviar_foto_telegram", _fake_foto
        ), mock.patch.object(
            ad, "_enviar_mensagem_telegram", _fake_msg
        ), mock.patch.object(
            ad.config, "TELEGRAM_BOT_TOKEN", "123456:FAKE"
        ):
            total = ad.notificar_documento_disponivel(
                ativo_id=10, ticker="MXRF11", nome_doc="Fato Relevante"
            )

        self.assertEqual(total, 1)
        self.assertEqual(mensagens, [])
        self.assertEqual(fotos[0][:3], (111, "MXRF11", "https://logos/MXRF11.png"))
        self.assertIn("MXRF11", fotos[0][3])

    def test_falha_da_foto_cai_para_mensagem_textual(self):
        destinatarios = [SimpleNamespace(telegram_chat_id=111, telegram_user_id=111)]
        mensagens = []

        def _fake_msg(chat_id, mensagem, teclado=None, parse_mode=None):
            mensagens.append(chat_id)
            return True

        with mock.patch.object(
            ad, "_destinatarios_do_ativo", return_value=destinatarios
        ), mock.patch.object(
            ad, "obter_media_logo_rapida", return_value="https://logos/MXRF11.png"
        ), mock.patch.object(
            ad, "_enviar_foto_telegram", return_value=False
        ), mock.patch.object(
            ad, "_enviar_mensagem_telegram", _fake_msg
        ), mock.patch.object(
            ad.config, "TELEGRAM_BOT_TOKEN", "123456:FAKE"
        ):
            total = ad.notificar_documento_disponivel(
                ativo_id=10, ticker="MXRF11", nome_doc="Fato Relevante"
            )

        self.assertEqual(total, 1)
        self.assertEqual(mensagens, [111])

    def test_sem_seguidores_nao_envia_nada(self):
        with mock.patch.object(
            ad, "_destinatarios_do_ativo", return_value=[]
        ), mock.patch.object(ad, "_enviar_mensagem_telegram") as enviar:
            total = ad.notificar_documento_disponivel(
                ativo_id=10, ticker="MXRF11", nome_doc="Fato Relevante"
            )
        self.assertEqual(total, 0)
        enviar.assert_not_called()

    def test_ativo_ausente_nao_consulta_banco_nem_envia(self):
        with mock.patch.object(ad, "_destinatarios_do_ativo") as destinatarios, \
                mock.patch.object(ad, "_enviar_mensagem_telegram") as enviar:
            total = ad.notificar_documento_disponivel(
                ativo_id=None, ticker=None, nome_doc="Documento"
            )
        self.assertEqual(total, 0)
        destinatarios.assert_not_called()
        enviar.assert_not_called()

    def test_falha_ao_resolver_seguidores_nao_propaga(self):
        with mock.patch.object(
            ad, "_destinatarios_do_ativo", side_effect=RuntimeError("db fora")
        ), mock.patch.object(ad, "_enviar_mensagem_telegram") as enviar:
            total = ad.notificar_documento_disponivel(
                ativo_id=10, ticker="MXRF11", nome_doc="Documento"
            )
        self.assertEqual(total, 0)
        enviar.assert_not_called()


if __name__ == "__main__":
    unittest.main()
