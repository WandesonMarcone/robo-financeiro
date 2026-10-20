"""Verificacoes isoladas do boot do bot (Etapa 1.1) e da separacao import/init.

Contrato atualizado (preparacao para publicacao controlada):

* importar ``bot/loader.py`` -- e os modulos que apenas registram handlers --
  NAO deve exigir ``TELEGRAM_BOT_TOKEN``;
* a inicializacao efetiva (``inicializar_bot`` / primeira operacao real) DEVE
  exigir a configuracao e falhar com mensagem clara quando ela faltar;
* nenhum token ficticio e usado e a validacao de producao nao e enfraquecida.

Nenhuma chamada de rede e feita: o telebot valida apenas o formato do token
antes de construir o objeto.
"""

import importlib
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402

TOKEN_FALSO = "123456:TOKEN-FALSO-PARA-TESTE"


class TestBotBoot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._token_original = config.TELEGRAM_BOT_TOKEN

    @classmethod
    def tearDownClass(cls):
        config.TELEGRAM_BOT_TOKEN = cls._token_original
        sys.modules.pop("bot.loader", None)

    def tearDown(self):
        config.TELEGRAM_BOT_TOKEN = self._token_original
        sys.modules.pop("bot.loader", None)

    def _carregar_loader(self):
        sys.modules.pop("bot.loader", None)
        return importlib.import_module("bot.loader")

    # -- Importacao nao exige token ---------------------------------------

    def test_importacao_sem_token_nao_exige_credencial(self):
        config.TELEGRAM_BOT_TOKEN = None
        loader = self._carregar_loader()
        self.assertIsNotNone(loader.bot)
        # O bot permanece preguicoso: nada foi construido so por importar.
        self.assertIsNone(loader.bot._real)

    def test_modulo_de_handlers_importa_sem_token(self):
        config.TELEGRAM_BOT_TOKEN = None
        sys.modules.pop("bot.loader", None)
        sys.modules.pop("bot.favoritos", None)
        modulo = importlib.import_module("bot.favoritos")
        self.assertTrue(hasattr(modulo, "mostrar_favoritos"))

    # -- Inicializacao exige token ----------------------------------------

    def test_token_ausente_falha_com_mensagem_clara(self):
        config.TELEGRAM_BOT_TOKEN = None
        loader = self._carregar_loader()
        with self.assertRaises(RuntimeError) as ctx:
            loader.inicializar_bot()
        mensagem = str(ctx.exception)
        self.assertIn("TELEGRAM_BOT_TOKEN", mensagem)
        self.assertNotIn("None", mensagem)

    def test_token_vazio_falha(self):
        config.TELEGRAM_BOT_TOKEN = ""
        loader = self._carregar_loader()
        with self.assertRaises(RuntimeError):
            loader.inicializar_bot()

    def test_token_somente_espacos_falha(self):
        config.TELEGRAM_BOT_TOKEN = "   "
        loader = self._carregar_loader()
        with self.assertRaises(RuntimeError):
            loader.inicializar_bot()

    def test_operacao_real_sem_token_falha(self):
        config.TELEGRAM_BOT_TOKEN = None
        loader = self._carregar_loader()
        with self.assertRaises(RuntimeError):
            loader.bot.remove_webhook()

    def test_token_presente_inicializa_bot(self):
        config.TELEGRAM_BOT_TOKEN = TOKEN_FALSO
        loader = self._carregar_loader()
        real = loader.inicializar_bot()
        self.assertIsNotNone(real)
        self.assertIs(loader.bot._real, real)

    def test_mensagem_nao_expoe_credencial(self):
        config.TELEGRAM_BOT_TOKEN = ""
        loader = self._carregar_loader()
        with self.assertRaises(RuntimeError) as ctx:
            loader.inicializar_bot()
        self.assertNotIn(TOKEN_FALSO, str(ctx.exception))


class TestImportMainSemToken(unittest.TestCase):
    """Importar a aplicacao nao pode exigir TELEGRAM_BOT_TOKEN."""

    def setUp(self):
        self._token = config.TELEGRAM_BOT_TOKEN
        self._patch_build = mock.patch(
            "googleapiclient.discovery.build", lambda *a, **k: object()
        )
        self._patch_build.start()

    def tearDown(self):
        self._patch_build.stop()
        config.TELEGRAM_BOT_TOKEN = self._token
        for nome in ("main", "bot.loader"):
            sys.modules.pop(nome, None)

    def test_import_main_sem_token(self):
        config.TELEGRAM_BOT_TOKEN = None
        usuario_token = os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        try:
            sys.modules.pop("main", None)
            main = importlib.import_module("main")
            self.assertTrue(hasattr(main, "criar_tabelas_se_solicitado"))
        finally:
            if usuario_token is not None:
                os.environ["TELEGRAM_BOT_TOKEN"] = usuario_token


if __name__ == "__main__":
    unittest.main()
