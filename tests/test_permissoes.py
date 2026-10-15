"""Testes do controle de usuários e permissões (Fase 2).

Cobrem a identificação de usuários por Telegram ID, a resolução de papéis e o
bloqueio de comandos e callbacks administrativos para o usuário limitado. Nenhum
serviço externo é acessado: o bot é criado com a validação de token neutralizada
e os métodos de envio são substituídos por fakes.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import telebot  # noqa: E402
import telebot.util  # noqa: E402
from telebot import types  # noqa: E402

import config  # noqa: E402
from bot import permissoes  # noqa: E402
from bot.telegram_utils import TEXTO_ACESSO_NEGADO  # noqa: E402

ADMIN_ID = 8867098987
USER_ID = 5336458734
DESCONHECIDO_ID = 111111111
NAO_AUTORIZADO_NO_CHAT = 777777777


def _update_mensagem(texto, user_id):
    payload = {
        "update_id": 1,
        "message": {
            "message_id": 3,
            "date": 0,
            "chat": {"id": user_id, "type": "private"},
            "from": {"id": user_id, "is_bot": False, "first_name": "Teste"},
            "text": texto,
        },
    }
    return types.Update.de_json(json.dumps(payload))


def _update_callback(data, user_id):
    payload = {
        "update_id": 2,
        "callback_query": {
            "id": "cb1",
            "from": {"id": user_id, "is_bot": False, "first_name": "Teste"},
            "chat_instance": "ci",
            "data": data,
            "message": {
                "message_id": 10,
                "date": 0,
                "chat": {"id": user_id, "type": "private"},
                "from": {"id": 1, "is_bot": True, "first_name": "Bot"},
                "text": "menu",
            },
        },
    }
    return types.Update.de_json(json.dumps(payload))


class _FakeFromUser:
    def __init__(self, user_id):
        self.id = user_id


class _FakeCallback:
    def __init__(self, data, from_user=None, message=None):
        self.data = data
        self.from_user = from_user
        self.message = message
        self.id = "cb-fake"


class _FakeUpdate:
    def __init__(self, callback=None, message=None):
        self.callback_query = callback
        self.message = message


class TestIdentificacaoDeUsuarios(unittest.TestCase):
    """Funções puras de identificação e classificação de operações."""

    def setUp(self):
        self._original = config.USUARIOS_AUTORIZADOS
        config.USUARIOS_AUTORIZADOS = {
            str(ADMIN_ID): config.PAPEL_ADMIN,
            str(USER_ID): config.PAPEL_USUARIO,
        }

    def tearDown(self):
        config.USUARIOS_AUTORIZADOS = self._original

    def test_administrador_identificado(self):
        self.assertEqual(permissoes.obter_papel(ADMIN_ID), config.PAPEL_ADMIN)
        self.assertTrue(permissoes.esta_autorizado(ADMIN_ID))

    def test_usuario_limitado_identificado(self):
        self.assertEqual(permissoes.obter_papel(USER_ID), config.PAPEL_USUARIO)
        self.assertTrue(permissoes.esta_autorizado(USER_ID))

    def test_usuario_desconhecido_sem_acesso(self):
        self.assertIsNone(permissoes.obter_papel(DESCONHECIDO_ID))
        self.assertFalse(permissoes.esta_autorizado(DESCONHECIDO_ID))

    def test_identificacao_ausente_nao_concede(self):
        self.assertIsNone(permissoes.obter_papel(None))
        self.assertIsNone(permissoes.obter_papel(""))
        self.assertFalse(permissoes.esta_autorizado(None))

    def test_admin_pode_tudo(self):
        self.assertTrue(permissoes.pode_executar(ADMIN_ID, permissoes.NIVEL_ADMIN))
        self.assertTrue(permissoes.pode_executar(ADMIN_ID, permissoes.NIVEL_USUARIO))

    def test_usuario_limitado_apenas_nivel_usuario(self):
        self.assertTrue(permissoes.pode_executar(USER_ID, permissoes.NIVEL_USUARIO))
        self.assertFalse(permissoes.pode_executar(USER_ID, permissoes.NIVEL_ADMIN))

    def test_classificacao_de_comandos(self):
        self.assertEqual(
            permissoes.operacao_de_comando("/forcar_cvm")[1], permissoes.NIVEL_ADMIN
        )
        self.assertEqual(
            permissoes.operacao_de_comando("/relatorios")[1], permissoes.NIVEL_USUARIO
        )
        self.assertEqual(
            permissoes.operacao_de_comando("/docs")[1], permissoes.NIVEL_USUARIO
        )
        self.assertEqual(
            permissoes.operacao_de_comando("/start@MeuBot")[1], permissoes.NIVEL_USUARIO
        )
        self.assertEqual(
            permissoes.operacao_de_comando("/comando_inexistente")[1],
            permissoes.NIVEL_ADMIN,
        )
        self.assertIsNone(permissoes.operacao_de_comando("texto comum"))
        self.assertIsNone(permissoes.operacao_de_comando(None))

    def test_classificacao_de_callbacks(self):
        self.assertEqual(
            permissoes.operacao_de_callback("menu_fiis")[1], permissoes.NIVEL_USUARIO
        )
        self.assertEqual(
            permissoes.operacao_de_callback("painel_PETR4_acao")[1],
            permissoes.NIVEL_USUARIO,
        )
        self.assertEqual(
            permissoes.operacao_de_callback("ver_raiox_docs")[1],
            permissoes.NIVEL_ADMIN,
        )
        self.assertEqual(
            permissoes.operacao_de_callback("rev_t_PETR4")[1], permissoes.NIVEL_ADMIN
        )
        self.assertEqual(
            permissoes.operacao_de_callback("confirmar_reset")[1],
            permissoes.NIVEL_ADMIN,
        )
        self.assertEqual(
            permissoes.operacao_de_callback("callback_inexistente")[1],
            permissoes.NIVEL_ADMIN,
        )

    def test_verificar_update_sem_operacao_libera(self):
        permitido, operacao = permissoes.verificar_update(
            _update_mensagem("bom dia", USER_ID)
        )
        self.assertTrue(permitido)
        self.assertIsNone(operacao)

    def test_verificar_update_comando_admin_bloqueia_usuario(self):
        permitido, operacao = permissoes.verificar_update(
            _update_mensagem("/resetar_docs", USER_ID)
        )
        self.assertFalse(permitido)
        self.assertEqual(operacao, "comando:/resetar_docs")

    def test_verificar_update_comando_consulta_libera_usuario(self):
        permitido, _ = permissoes.verificar_update(
            _update_mensagem("/relatorios", USER_ID)
        )
        self.assertTrue(permitido)

    def test_ausencia_de_identificacao_bloqueia_operacao(self):
        callback = _FakeCallback("confirmar_reset", from_user=None, message=None)
        update = _FakeUpdate(callback=callback)
        self.assertIsNone(permissoes.usuario_id_do_update(update))
        permitido, operacao = permissoes.verificar_update(update)
        self.assertFalse(permitido)
        self.assertEqual(operacao, "callback:confirmar_reset")


class TestBotPermissoesIntegracao(unittest.TestCase):
    """Valida o bloqueio efetivo por comando e callback sem executar handlers."""

    @classmethod
    def setUpClass(cls):
        cls._config_backup = {
            "USUARIOS_AUTORIZADOS": config.USUARIOS_AUTORIZADOS,
            "CHATS_AUTORIZADOS": config.CHATS_AUTORIZADOS,
            "TELEGRAM_BOT_TOKEN": getattr(config, "TELEGRAM_BOT_TOKEN", None),
        }
        config.USUARIOS_AUTORIZADOS = {
            str(ADMIN_ID): config.PAPEL_ADMIN,
            str(USER_ID): config.PAPEL_USUARIO,
        }
        config.CHATS_AUTORIZADOS = [str(ADMIN_ID), str(USER_ID)]

        telebot.util.validate_token = lambda *args, **kwargs: None
        config.TELEGRAM_BOT_TOKEN = "123456:FAKE-TOKEN-PARA-TESTE"
        sys.modules.pop("bot.loader", None)
        import bot.loader as loader

        cls.loader = loader
        cls.bot = loader.bot
        cls.executados = []

        @cls.bot.message_handler(commands=["forcar_cvm"])
        def _cmd_admin(message):
            cls.executados.append(("cmd", "forcar_cvm"))

        @cls.bot.message_handler(commands=["relatorios"])
        def _cmd_usuario(message):
            cls.executados.append(("cmd", "relatorios"))

        @cls.bot.callback_query_handler(func=lambda c: c.data == "menu_fiis")
        def _cb_usuario(call):
            cls.executados.append(("cb", "menu_fiis"))

        @cls.bot.callback_query_handler(func=lambda c: c.data == "ver_raiox_docs")
        def _cb_admin(call):
            cls.executados.append(("cb", "ver_raiox_docs"))

        @cls.bot.callback_query_handler(func=lambda c: c.data == "confirmar_reset")
        def _cb_admin_reset(call):
            cls.executados.append(("cb", "confirmar_reset"))

    @classmethod
    def tearDownClass(cls):
        config.USUARIOS_AUTORIZADOS = cls._config_backup["USUARIOS_AUTORIZADOS"]
        config.CHATS_AUTORIZADOS = cls._config_backup["CHATS_AUTORIZADOS"]
        config.TELEGRAM_BOT_TOKEN = cls._config_backup["TELEGRAM_BOT_TOKEN"]
        sys.modules.pop("bot.loader", None)

    def setUp(self):
        type(self).executados.clear()
        self.chamadas = {"send": [], "answer": []}
        self.bot.send_message = (
            lambda chat_id, text, **k: self.chamadas["send"].append((chat_id, text))
        )
        self.bot.answer_callback_query = (
            lambda cid, text=None, **k: self.chamadas["answer"].append((cid, text))
        )

    def test_admin_executa_comando_administrativo(self):
        self.bot.process_new_updates([_update_mensagem("/forcar_cvm", ADMIN_ID)])
        self.assertEqual(self.executados, [("cmd", "forcar_cvm")])

    def test_admin_mantem_acesso_a_consulta(self):
        self.bot.process_new_updates([_update_mensagem("/relatorios", ADMIN_ID)])
        self.assertEqual(self.executados, [("cmd", "relatorios")])

    def test_usuario_limitado_acessa_consulta(self):
        self.bot.process_new_updates([_update_mensagem("/relatorios", USER_ID)])
        self.assertEqual(self.executados, [("cmd", "relatorios")])

    def test_usuario_limitado_nao_executa_comando_admin(self):
        self.bot.process_new_updates([_update_mensagem("/forcar_cvm", USER_ID)])
        self.assertEqual(self.executados, [])
        self.assertEqual(self.chamadas["send"][-1][1], TEXTO_ACESSO_NEGADO)

    def test_usuario_limitado_acessa_callback_consulta(self):
        self.bot.process_new_updates([_update_callback("menu_fiis", USER_ID)])
        self.assertEqual(self.executados, [("cb", "menu_fiis")])

    def test_usuario_limitado_nao_executa_callback_admin(self):
        self.bot.process_new_updates([_update_callback("confirmar_reset", USER_ID)])
        self.assertEqual(self.executados, [])
        self.assertEqual(
            self.chamadas["answer"][-1][1],
            TEXTO_ACESSO_NEGADO,
        )

    def test_admin_executa_callback_administrativo(self):
        self.bot.process_new_updates([_update_callback("ver_raiox_docs", ADMIN_ID)])
        self.assertEqual(self.executados, [("cb", "ver_raiox_docs")])

    def test_usuario_desconhecido_e_descartado(self):
        self.bot.process_new_updates([_update_mensagem("/relatorios", DESCONHECIDO_ID)])
        self.assertEqual(self.executados, [])
        self.assertEqual(self.chamadas["send"], [])
        self.assertEqual(self.chamadas["answer"], [])

    def test_autorizado_no_chat_sem_papel_e_negado(self):
        original = config.CHATS_AUTORIZADOS
        config.CHATS_AUTORIZADOS = [*original, str(NAO_AUTORIZADO_NO_CHAT)]
        try:
            self.bot.process_new_updates(
                [_update_mensagem("/relatorios", NAO_AUTORIZADO_NO_CHAT)]
            )
        finally:
            config.CHATS_AUTORIZADOS = original
        self.assertEqual(self.executados, [])
        self.assertEqual(
            self.chamadas["send"][-1][1],
            TEXTO_ACESSO_NEGADO,
        )

    def test_erro_na_verificacao_nao_interrompe_o_bot(self):
        original = permissoes.verificar_update

        def _explodir(_update):
            raise RuntimeError("falha simulada na verificacao")

        permissoes.verificar_update = _explodir
        try:
            self.bot.process_new_updates([_update_callback("menu_fiis", ADMIN_ID)])
        finally:
            permissoes.verificar_update = original
        self.assertEqual(self.executados, [])
        self.assertEqual(
            self.chamadas["answer"][-1][1],
            TEXTO_ACESSO_NEGADO,
        )


if __name__ == "__main__":
    unittest.main()
