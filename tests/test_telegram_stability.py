"""Testes isolados da estabilização dos comandos do Telegram (Etapa 1).

Não acessam serviços reais: nenhuma chamada HTTP é feita. O bot é instanciado
com a validação de token do telebot neutralizada e os métodos de envio são
substituídos por fakes.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import telebot  # noqa: E402
import telebot.util  # noqa: E402
from telebot import types  # noqa: E402

from bot import telegram_utils  # noqa: E402


def _update_callback(data, chat_id=8867098987):
    payload = {
        "update_id": 1,
        "callback_query": {
            "id": "cb1",
            "from": {"id": chat_id, "is_bot": False, "first_name": "Teste"},
            "chat_instance": "ci",
            "data": data,
            "message": {
                "message_id": 10,
                "date": 0,
                "chat": {"id": chat_id, "type": "private"},
                "from": {"id": 1, "is_bot": True, "first_name": "Bot"},
                "text": "menu",
            },
        },
    }
    return types.Update.de_json(json.dumps(payload))


def _update_mensagem(texto, chat_id=8867098987):
    payload = {
        "update_id": 2,
        "message": {
            "message_id": 3,
            "date": 0,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": chat_id, "is_bot": False, "first_name": "Teste"},
            "text": texto,
        },
    }
    return types.Update.de_json(json.dumps(payload))


class FakeBot:
    def __init__(self):
        self._update_em_processamento = None
        self._falha_no_update = None
        self.sent = []
        self.answered = []
        self.falhar_envio = False

    def send_message(self, chat_id, text, **kwargs):
        if self.falhar_envio:
            raise RuntimeError("sem rede")
        self.sent.append((chat_id, text))

    def answer_callback_query(self, callback_query_id, text=None, **kwargs):
        if self.falhar_envio:
            raise RuntimeError("sem rede")
        self.answered.append((callback_query_id, text))


class TestAutorizacaoEDescricao(unittest.TestCase):
    def test_chat_id_de_mensagem(self):
        self.assertEqual(
            telegram_utils.chat_id_do_update(_update_mensagem("/start")),
            8867098987,
        )

    def test_chat_id_de_callback(self):
        self.assertEqual(
            telegram_utils.chat_id_do_update(_update_callback("menu_fiis")),
            8867098987,
        )

    def test_chat_id_ausente(self):
        self.assertIsNone(telegram_utils.chat_id_do_update(types.Update.de_json(
            json.dumps({"update_id": 9})
        )))

    def test_autorizado_por_lista(self):
        self.assertTrue(
            telegram_utils.chat_autorizado(
                _update_mensagem("/start"), chats_autorizados=["8867098987"]
            )
        )

    def test_nao_autorizado(self):
        self.assertFalse(
            telegram_utils.chat_autorizado(
                _update_mensagem("/start", chat_id=111), chats_autorizados=["8867098987"]
            )
        )

    def test_update_sem_chat_e_aceito(self):
        update = types.Update.de_json(json.dumps({"update_id": 9}))
        self.assertTrue(telegram_utils.chat_autorizado(update, chats_autorizados=[]))

    def test_descrever_mensagem_e_callback(self):
        self.assertIn("text='/start'", telegram_utils.descrever_update(_update_mensagem("/start")))
        self.assertIn(
            "data='menu_fiis'", telegram_utils.descrever_update(_update_callback("menu_fiis"))
        )


class TestCallbackDesconhecido(unittest.TestCase):
    def test_responde_callback_desconhecido(self):
        bot = FakeBot()
        self.assertTrue(telegram_utils.responder_callback_desconhecido(bot, "cb1"))
        self.assertEqual(len(bot.answered), 1)
        self.assertEqual(bot.answered[0][0], "cb1")
        self.assertEqual(
            bot.answered[0][1], telegram_utils.TEXTO_CALLBACK_DESCONHECIDO
        )

    def test_falha_ao_responder_nao_propaga(self):
        bot = FakeBot()
        bot.falhar_envio = True
        self.assertFalse(telegram_utils.responder_callback_desconhecido(bot, "cb1"))


class TestAjudaContextual(unittest.TestCase):
    def test_guia_do_visitante_explica_o_projeto_sem_comandos_admin(self):
        texto = telegram_utils.montar_guia_comandos(formulario_ativo=True)
        self.assertIn("agosto de 2026", texto)
        self.assertIn("etapa de cadastro", texto)
        self.assertNotIn("/forcar_cvm", texto)
        self.assertNotIn("/resetar_docs", texto)

    def test_guia_pendente_nao_promete_menu(self):
        texto = telegram_utils.montar_guia_comandos(status="pendente")
        self.assertIn("aguardando aprovação", texto)
        self.assertNotIn("/forcar_cvm", texto)

    def test_guia_admin_inclui_comandos_administrativos(self):
        texto = telegram_utils.montar_guia_comandos(papel="admin")
        self.assertIn("/controles", texto)
        self.assertIn("/resetar_docs", texto)

    def test_guia_do_visitante_pede_start(self):
        texto = telegram_utils.montar_guia_comandos()
        self.assertIn("envie /start", texto.lower())
        self.assertNotIn("/forcar_cvm", texto)


class TestNotificadorDeFalhas(unittest.TestCase):
    def test_notifica_callback(self):
        bot = FakeBot()
        bot._update_em_processamento = _update_callback("x")
        notificador = telegram_utils.NotificadorDeFalhas()
        notificador.bot = bot

        self.assertTrue(notificador.handle(RuntimeError("boom")))
        self.assertEqual(bot.answered[0][1], telegram_utils.TEXTO_FALHA_CALLBACK)
        self.assertIsInstance(bot._falha_no_update, RuntimeError)

    def test_notifica_mensagem(self):
        bot = FakeBot()
        bot._update_em_processamento = _update_mensagem("/start")
        notificador = telegram_utils.NotificadorDeFalhas()
        notificador.bot = bot

        notificador.handle(RuntimeError("boom"))
        self.assertEqual(bot.sent[0], (8867098987, telegram_utils.TEXTO_FALHA_COMANDO))


class TestBotAutorizadoIntegracao(unittest.TestCase):
    """Valida o despacho e o tratamento de falhas do bot real (sem rede)."""

    @classmethod
    def setUpClass(cls):
        telebot.util.validate_token = lambda *args, **kwargs: None
        import config

        config.TELEGRAM_BOT_TOKEN = "123456:FAKE-TOKEN-PARA-TESTE"
        sys.modules.pop("bot.loader", None)
        import bot.loader as loader

        cls.loader = loader
        cls.bot = loader.bot
        cls.executados = []

        @cls.bot.callback_query_handler(func=lambda c: c.data == "teste_ok")
        def _ok(call):
            cls.executados.append("ok")

        @cls.bot.callback_query_handler(func=lambda c: c.data == "teste_boom")
        def _boom(call):
            raise RuntimeError("falha simulada")

    def setUp(self):
        type(self).executados.clear()
        self.chamadas = {"answer": [], "send": []}
        self.bot.answer_callback_query = (
            lambda cid, text=None, **k: self.chamadas["answer"].append((cid, text))
        )
        self.bot.send_message = (
            lambda chat_id, text, **k: self.chamadas["send"].append((chat_id, text))
        )

    def test_update_autorizado_executa_handler(self):
        self.bot.process_new_updates([_update_callback("teste_ok")])
        self.assertEqual(self.executados, ["ok"])
        self.assertIsNone(self.bot._falha_no_update)

    def test_update_nao_autorizado_e_descartado(self):
        self.bot.process_new_updates([_update_callback("teste_ok", chat_id=999)])
        self.assertEqual(self.executados, [])
        self.assertEqual(self.chamadas["answer"], [])

    def test_excecao_no_handler_nao_fica_silenciosa(self):
        self.bot.process_new_updates([_update_callback("teste_boom")])
        self.assertIsInstance(self.bot._falha_no_update, RuntimeError)
        self.assertEqual(len(self.chamadas["answer"]), 1)
        self.assertEqual(self.chamadas["answer"][0][1], telegram_utils.TEXTO_FALHA_CALLBACK)


if __name__ == "__main__":
    unittest.main()
