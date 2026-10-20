"""Testes da correcao de inicializacao e conexao com o banco.

Cobrem os requisitos da etapa:

* boot sem ``GROQ_API_KEY`` (importacao e funcionalidade sem IA);
* erro controlado quando uma funcionalidade que exige IA roda sem credencial;
* normalizacao de ``DATABASE_URL`` (``postgres://`` -> ``postgresql://``);
* criacao do engine usando a URL efetivamente normalizada;
* ausencia de alteracao automatica/destrutiva do banco na inicializacao;
* importacao dos modulos principais sem efeitos colaterais desnecessarios.

Nenhum banco real e acessado: os testes usam URLs fakes (o ``create_engine`` do
SQLAlchemy nao abre conexao) e nunca executam comandos de escrita. Nenhuma
credencial e real.
"""

import importlib
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from pipeline_dados import conexao  # noqa: E402

PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANCO_SQLITE_LOCAL = os.path.join(
    PROJETO, "pipeline_dados", "banco_institucional.db"
)
TOKEN_FALSO = "123456:FAKE-TOKEN-PARA-TESTE-DE-BOOT-1234567890"


def _sem_variavel(nome, valor_config=None):
    """Patch combinado de ``os.environ`` e ``config`` para simular ausencia."""
    env = mock.patch.dict(os.environ)
    env.start()
    os.environ.pop(nome, None)
    config_patch = None
    if valor_config is not None:
        config_patch = mock.patch.object(config, nome, valor_config)
        config_patch.start()
    return env, config_patch


class TestNormalizacaoDatabaseUrl(unittest.TestCase):
    def test_prefixo_legado_postgres_convertido(self):
        self.assertEqual(
            conexao.normalizar_database_url("postgres://u:p@host:5432/db"),
            "postgresql+psycopg://u:p@host:5432/db",
        )

    def test_prefixo_postgresql_usa_driver_psycopg3(self):
        self.assertEqual(
            conexao.normalizar_database_url("postgresql://u:p@host/db"),
            "postgresql+psycopg://u:p@host/db",
        )

    def test_driver_explicito_e_preservado(self):
        self.assertEqual(
            conexao.normalizar_database_url("postgresql+psycopg://u:p@host/db"),
            "postgresql+psycopg://u:p@host/db",
        )

    def test_espacos_removidos(self):
        self.assertEqual(
            conexao.normalizar_database_url("  postgresql://u:p@host/db  "),
            "postgresql+psycopg://u:p@host/db",
        )

    def test_valores_ausentes_retornam_none(self):
        self.assertIsNone(conexao.normalizar_database_url(None))
        self.assertIsNone(conexao.normalizar_database_url(""))
        self.assertIsNone(conexao.normalizar_database_url("   "))

    def test_sqlite_explicito_e_preservado(self):
        self.assertEqual(
            conexao.normalizar_database_url("sqlite:///dados.db"),
            "sqlite:///dados.db",
        )


class TestCriacaoDoEngine(unittest.TestCase):
    def tearDown(self):
        conexao.resetar_conexao()

    def test_engine_usa_url_normalizada(self):
        engine = conexao.criar_engine("postgres://user:senha@host:5432/neon")
        try:
            self.assertEqual(engine.url.drivername, "postgresql+psycopg")
            self.assertEqual(engine.url.host, "host")
            self.assertEqual(engine.url.database, "neon")
        finally:
            engine.dispose()

    def test_engine_via_resolver_usa_config_normalizada(self):
        env, config_patch = _sem_variavel(
            "DATABASE_URL", "postgres://user:senha@host/db"
        )
        try:
            engine = conexao.criar_engine()
            try:
                self.assertEqual(engine.url.drivername, "postgresql+psycopg")
            finally:
                engine.dispose()
        finally:
            if config_patch:
                config_patch.stop()
            env.stop()

    def test_engine_sem_url_falha_controlado(self):
        env, config_patch = _sem_variavel("DATABASE_URL", None)
        try:
            with self.assertRaises(conexao.BancoNaoConfiguradoError) as ctx:
                conexao.criar_engine()
            mensagem = str(ctx.exception)
            self.assertIn("DATABASE_URL", mensagem)
            self.assertNotIn("sqlite", mensagem.lower())
        finally:
            if config_patch:
                config_patch.stop()
            env.stop()

    def test_engine_nao_faz_fallback_para_sqlite(self):
        enviado = os.environ.get("DATABASE_URL")
        os.environ.pop("DATABASE_URL", None)
        try:
            with mock.patch.object(config, "DATABASE_URL", None):
                with self.assertRaises(conexao.BancoNaoConfiguradoError):
                    conexao.criar_engine()
            self.assertFalse(os.path.exists(BANCO_SQLITE_LOCAL))
        finally:
            if enviado is not None:
                os.environ["DATABASE_URL"] = enviado


class TestFabricaDeSessao(unittest.TestCase):
    def tearDown(self):
        conexao.resetar_conexao()

    def test_session_factory_nao_trava_e_usa_url_normalizada(self):
        """Regressao: obter_session_factory nao pode dar deadlock ao obter engine."""
        import queue
        import threading

        resultado = queue.Queue()

        def trabalhador():
            try:
                conexao.resetar_conexao()
                with mock.patch.object(
                    config, "DATABASE_URL", "postgres://u:p@host/db"
                ):
                    factory = conexao.obter_session_factory()
                    sessao = factory()
                    resultado.put(
                        (
                            "ok",
                            factory.kw["bind"].url.drivername,
                            type(sessao).__name__,
                        )
                    )
                    sessao.close()
            except Exception as exc:  # pragma: no cover - diagnostico
                resultado.put(("erro", repr(exc)))

        thread = threading.Thread(target=trabalhador, daemon=True)
        thread.start()
        thread.join(timeout=10)
        self.assertFalse(thread.is_alive(), "obter_session_factory travou (deadlock?)")
        status = resultado.get_nowait()
        self.assertEqual(status[0], "ok", status)
        self.assertEqual(status[1], "postgresql+psycopg")


class TestBootSemGroq(unittest.TestCase):
    def tearDown(self):
        import atualizador_documentos as mod

        mod._cliente_groq = None

    def test_importacao_sem_groq_nao_quebra(self):
        env, config_patch = _sem_variavel("GROQ_API_KEY", None)
        try:
            sys.modules.pop("atualizador_documentos", None)
            modulo = importlib.import_module("atualizador_documentos")
            self.assertTrue(hasattr(modulo, "SessionDB"))
            self.assertTrue(hasattr(modulo, "obter_cliente_groq"))
        finally:
            if config_patch:
                config_patch.stop()
            env.stop()

    def test_funcionalidade_que_exige_ia_sem_chave_falha_controlado(self):
        import atualizador_documentos as mod

        env, config_patch = _sem_variavel("GROQ_API_KEY", None)
        try:
            mod._cliente_groq = None
            with self.assertRaises(mod.IAIndisponivelError) as ctx:
                mod.obter_cliente_groq()
            self.assertNotIn("None", str(ctx.exception))
        finally:
            if config_patch:
                config_patch.stop()
            env.stop()

    def test_classificacao_sem_chave_degrada_sem_quebrar(self):
        import atualizador_documentos as mod

        env, config_patch = _sem_variavel("GROQ_API_KEY", None)
        try:
            mod._cliente_groq = None
            resultado = mod.classificar_documento_com_ia(
                "Relatorio Gerencial", "texto extraido de um pdf"
            )
            self.assertEqual(resultado, ("Relatorio Gerencial", 0))
        finally:
            if config_patch:
                config_patch.stop()
            env.stop()

    def test_dupla_checagem_so_autosave_quando_as_duas_concordam(self):
        import atualizador_documentos as mod

        with mock.patch.object(
            mod,
            "classificar_documento_com_ia",
            side_effect=[
                ("Fato Relevante", 90),
                ("Fato Relevante", 85),
            ],
        ):
            tipo, confianca, acordo = mod.classificar_documento_fii_dupla(
                "Outros", "fato relevante publicado pelo fundo"
            )
        self.assertTrue(acordo)
        self.assertEqual(tipo, "Fato Relevante")
        self.assertEqual(confianca, 85)

        with mock.patch.object(
            mod,
            "classificar_documento_com_ia",
            side_effect=[
                ("Fato Relevante", 90),
                ("Comunicado ao Mercado", 88),
            ],
        ):
            tipo, confianca, acordo = mod.classificar_documento_fii_dupla(
                "Outros", "texto ambiguo"
            )
        self.assertFalse(acordo)
        self.assertEqual(tipo, "Outros")

    def test_dupla_checagem_expoe_as_duas_leituras(self):
        import json
        import atualizador_documentos as mod

        with mock.patch.object(
            mod,
            "classificar_documento_com_ia",
            side_effect=[
                ("Fato Relevante", 90),
                ("Comunicado ao Mercado", 70),
            ],
        ):
            detalhes = mod._dupla_checagem_fii("Outros", "texto ambiguo")
        self.assertFalse(detalhes["acordo"])
        self.assertEqual(detalhes["checagem_1"], ("Fato Relevante", 90))
        self.assertEqual(detalhes["checagem_2"], ("Comunicado ao Mercado", 70))
        resumo = json.loads(mod._resumo_dupla_checagem(detalhes))
        self.assertEqual(resumo["checagem_1"]["tipo"], "Fato Relevante")
        self.assertEqual(resumo["checagem_2"]["tipo"], "Comunicado ao Mercado")


class TestSemAlteracaoAutomaticaDoBanco(unittest.TestCase):
    def setUp(self):
        conexao.resetar_conexao()

    def tearDown(self):
        conexao.resetar_conexao()

    def test_importacao_nao_cria_engine_nem_banco(self):
        enviado = os.environ.get("DATABASE_URL")
        os.environ.pop("DATABASE_URL", None)
        try:
            with mock.patch.object(config, "DATABASE_URL", None):
                sys.modules.pop("atualizador_documentos", None)
                importlib.import_module("atualizador_documentos")
                self.assertIsNone(conexao._engine)
                self.assertIsNone(conexao._session_factory)
                self.assertFalse(os.path.exists(BANCO_SQLITE_LOCAL))
        finally:
            if enviado is not None:
                os.environ["DATABASE_URL"] = enviado

    def test_criar_tabelas_e_opt_in_e_nao_roda_por_padrao(self):
        enviado = os.environ.get("CRIAR_TABELAS")
        os.environ.pop("CRIAR_TABELAS", None)
        try:
            import main

            with mock.patch.object(main, "obter_engine") as obter:
                main.criar_tabelas_se_solicitado()
                obter.assert_not_called()
        finally:
            if enviado is not None:
                os.environ["CRIAR_TABELAS"] = enviado


class TestImportMainSemEfeitosColaterais(unittest.TestCase):
    def setUp(self):
        self._token = config.TELEGRAM_BOT_TOKEN
        config.TELEGRAM_BOT_TOKEN = TOKEN_FALSO
        # Evita qualquer descoberta de rede do Google durante a importacao.
        self._patch_build = mock.patch(
            "googleapiclient.discovery.build", lambda *a, **k: object()
        )
        self._patch_build.start()

    def tearDown(self):
        self._patch_build.stop()
        config.TELEGRAM_BOT_TOKEN = self._token
        sys.modules.pop("main", None)

    def test_import_main_nao_inicia_scheduler_nem_altera_banco(self):
        enviado = os.environ.get("DATABASE_URL")
        os.environ.pop("DATABASE_URL", None)
        os.environ.pop("ROBO_INICIAR_NO_IMPORT", None)
        try:
            sys.modules.pop("main", None)
            main = importlib.import_module("main")
            self.assertFalse(main.scheduler.running)
            self.assertFalse(os.path.exists(BANCO_SQLITE_LOCAL))
        finally:
            if enviado is not None:
                os.environ["DATABASE_URL"] = enviado

    def test_import_main_nao_registra_webhook(self):
        import telebot

        chamadas = []
        with mock.patch.object(
            telebot.TeleBot, "set_webhook", lambda self, *a, **k: chamadas.append("set")
        ), mock.patch.object(
            telebot.TeleBot, "remove_webhook", lambda self, *a, **k: chamadas.append("remove")
        ):
            sys.modules.pop("main", None)
            importlib.import_module("main")
        self.assertEqual(chamadas, [])


class TestImportSemEfeitosColateraisGoogleDrive(unittest.TestCase):
    """Os modulos que usam Drive nao podem instancia-lo na importacao."""

    def test_import_nao_instancia_drive_manager(self):
        # Se a importacao chamasse GoogleDriveManager(), a descoberta de rede do
        # Google ocorreria aqui; o patch garante que isso seria detectado.
        def _explodir(*args, **kwargs):  # pragma: no cover - so dispara em falha
            raise AssertionError("GoogleDriveManager foi criado na importacao")

        with mock.patch("googleapiclient.discovery.build", _explodir):
            sys.modules.pop("services.dashboard_menus", None)
            sys.modules.pop("bot.callbacks_revisao", None)
            dashboard = importlib.import_module("services.dashboard_menus")
            revisao = importlib.import_module("bot.callbacks_revisao")

        self.assertIsNone(dashboard._drive_manager)
        self.assertIsNone(revisao._drive_manager)
        self.assertTrue(callable(dashboard.obter_drive_manager))
        self.assertTrue(callable(revisao.obter_drive_manager))


class TestMascaramentoDeSegredos(unittest.TestCase):
    def test_mascara_senha_da_url_de_conexao(self):
        mascarada = conexao.mascarar_url("postgresql://usuario:senha-secreta@host/db")
        self.assertNotIn("senha-secreta", mascarada)
        self.assertIn("usuario", mascarada)
        self.assertIn("***", mascarada)
        self.assertIn("host/db", mascarada)

    def test_mascara_url_sem_senha_nao_quebra(self):
        self.assertEqual(
            conexao.mascarar_url("postgresql://host/db"),
            "postgresql://host/db",
        )
        self.assertIsNone(conexao.mascarar_url(None))


if __name__ == "__main__":
    unittest.main()
