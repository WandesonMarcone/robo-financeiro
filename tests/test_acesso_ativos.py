"""Acesso por ativo: favoritos ativos como limite de consulta do usuario comum.

SQLite em memoria; sem Neon e sem Telegram real. Cobre ``tickers_permitidos`` /
``pode_acessar_ativo`` (bot.permissoes) e a filtragem de "Novos documentos".
"""

import datetime
import os
import sys
import types as pytypes
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import telebot.util  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import config  # noqa: E402
import pipeline_dados.repositorio_favoritos as rf  # noqa: E402
import pipeline_dados.repositorio_usuarios as ru  # noqa: E402
from bot import permissoes  # noqa: E402
from pipeline_dados.banco_dados import (  # noqa: E402
    Ativo,
    Base,
    DocumentosQualitativos,
    TipoAtivo,
)
from pipeline_dados.modelos_ativos import BaseAcompanhados  # noqa: E402
from pipeline_dados.modelos_usuarios import (  # noqa: E402
    STATUS_APROVADO,
    STATUS_PENDENTE,
    STATUS_SUSPENSO,
    BaseUsuarios,
    Usuario,
)
from pipeline_dados.repositorio_favoritos import RepositorioFavoritos  # noqa: E402

ADMIN_ID = 8867098987
USER_ID = 5336458734
PENDENTE_ID = 222222222
SUSPENSO_ID = 333333333
DESCONHECIDO_ID = 444444444


class TestAcessoPorAtivo(unittest.TestCase):
    def setUp(self):
        self._backup = config.USUARIOS_AUTORIZADOS
        config.USUARIOS_AUTORIZADOS = {str(ADMIN_ID): config.PAPEL_ADMIN}
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        for base in (Base, BaseUsuarios, BaseAcompanhados):
            base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self._orig = (rf.obter_session_factory, ru.obter_session_factory)
        rf.obter_session_factory = lambda: self.Session
        ru.obter_session_factory = lambda: self.Session

        self.ids = {}
        for ticker, tipo in (
            ("MXRF11", TipoAtivo.FII),
            ("HGLG11", TipoAtivo.FII),
            ("PETR4", TipoAtivo.ACAO),
        ):
            sessao = self.Session()
            ativo = Ativo(ticker=ticker, cnpj=f"cnpj-{ticker}", tipo=tipo)
            sessao.add(ativo)
            sessao.commit()
            self.ids[ticker] = ativo.id
            sessao.close()

        self.usuario = self._usuario(USER_ID, STATUS_APROVADO, True)
        self._usuario(PENDENTE_ID, STATUS_PENDENTE, False)
        self._usuario(SUSPENSO_ID, STATUS_SUSPENSO, False)
        for ticker in ("MXRF11", "PETR4"):
            RepositorioFavoritos().adicionar(self.usuario, ticker)

    def tearDown(self):
        rf.obter_session_factory, ru.obter_session_factory = self._orig
        config.USUARIOS_AUTORIZADOS = self._backup
        self.engine.dispose()

    def _usuario(self, telegram_id, status, ativo):
        sessao = self.Session()
        try:
            u = Usuario(
                nome=f"user-{telegram_id}",
                papel="user",
                ativo=ativo,
                telegram_user_id=telegram_id,
                telegram_chat_id=telegram_id,
                status_cadastro=status,
            )
            sessao.add(u)
            sessao.commit()
            return u.id
        finally:
            sessao.close()

    def test_admin_tem_visao_ampla(self):
        self.assertIsNone(permissoes.tickers_permitidos(ADMIN_ID))
        self.assertTrue(permissoes.pode_acessar_ativo(ADMIN_ID, "HGLG11"))

    def test_usuario_comum_so_favoritos(self):
        self.assertEqual(
            permissoes.tickers_permitidos(USER_ID), frozenset({"MXRF11", "PETR4"})
        )
        self.assertTrue(permissoes.pode_acessar_ativo(USER_ID, "mxrf11"))
        self.assertFalse(permissoes.pode_acessar_ativo(USER_ID, "HGLG11"))
        self.assertFalse(permissoes.pode_acessar_ativo(USER_ID, ""))
        self.assertFalse(permissoes.pode_acessar_ativo(USER_ID, None))

    def test_conta_nao_aprovada_ou_desconhecida_nao_acessa_nada(self):
        for uid in (PENDENTE_ID, SUSPENSO_ID, DESCONHECIDO_ID, None):
            self.assertEqual(permissoes.tickers_permitidos(uid), frozenset(), uid)

    def test_troca_aprovada_vale_para_consultas_futuras(self):
        repo = RepositorioFavoritos()
        repo.remover(self.usuario, "MXRF11")
        repo.adicionar(self.usuario, "HGLG11")
        self.assertTrue(permissoes.pode_acessar_ativo(USER_ID, "HGLG11"))
        self.assertFalse(permissoes.pode_acessar_ativo(USER_ID, "MXRF11"))

    def test_falha_de_banco_nega(self):
        def _explodir():
            raise RuntimeError("banco fora")

        ru.obter_session_factory = _explodir
        self.assertEqual(permissoes.tickers_permitidos(USER_ID), frozenset())
        self.assertFalse(permissoes.pode_acessar_ativo(USER_ID, "MXRF11"))

    def test_callbacks_forjados_sao_negados_pelo_gate(self):
        def update(dados, uid):
            cb = pytypes.SimpleNamespace(
                data=dados, from_user=pytypes.SimpleNamespace(id=uid), message=None
            )
            return pytypes.SimpleNamespace(message=None, callback_query=cb)

        def liberado(dados, uid=USER_ID):
            return permissoes.verificar_update(update(dados, uid))[0]

        for ok in ("painel_MXRF11_fii", "dl_PETR4_t_Fato", "ajuda_cvm_PETR4_menu"):
            self.assertTrue(liberado(ok), ok)
        for negado in (
            "painel_HGLG11_fii",
            "dados_HGLG11_fii",
            "ano_HGLG11_fii_2024",
            "mes_HGLG11_fii_2024-03-31",
            "docs_HGLG11_fii",
            "dnav_HGLG11_t",
            "dl_HGLG11_t_Fato",
            "ia_HGLG11_fii_parecer",
            "ajuda_cvm_HGLG11_menu",
            "painel_",
            "menu_fiis",
            "consultar_indicadores",
            "trocaadm_home",
        ):
            self.assertFalse(liberado(negado), negado)
        self.assertTrue(liberado("painel_HGLG11_fii", ADMIN_ID))


class TestFiltroDeDocumentos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._token = getattr(config, "TELEGRAM_BOT_TOKEN", None)
        telebot.util.validate_token = lambda *a, **k: None
        config.TELEGRAM_BOT_TOKEN = "123456:FAKE-TOKEN-ACESSO-TESTE"
        from bot import menu_principal

        cls.menu = menu_principal

    @classmethod
    def tearDownClass(cls):
        config.TELEGRAM_BOT_TOKEN = cls._token

    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        sessao = self.Session()
        for n, (ticker, tipo) in enumerate(
            (("MXRF11", TipoAtivo.FII), ("PETR4", TipoAtivo.ACAO)), start=1
        ):
            ativo = Ativo(ticker=ticker, cnpj=f"cnpj-{ticker}", tipo=tipo)
            sessao.add(ativo)
            sessao.flush()
            sessao.add(
                DocumentosQualitativos(
                    ativo_id=ativo.id,
                    data_publicacao=datetime.date(2026, 1, n),
                    tipo_documento=f"Doc-{ticker}",
                    url_pdf=f"https://exemplo/{ticker}.pdf",
                )
            )
        sessao.commit()
        sessao.close()
        self._modulo = sys.modules.get("atualizador_documentos")
        sys.modules["atualizador_documentos"] = pytypes.SimpleNamespace(
            SessionDB=self.Session
        )

    def tearDown(self):
        if self._modulo is None:
            sys.modules.pop("atualizador_documentos", None)
        else:
            sys.modules["atualizador_documentos"] = self._modulo
        self.engine.dispose()

    def test_admin_ve_todos_os_documentos(self):
        texto = self.menu.texto_novos_documentos(tickers_permitidos=None)
        self.assertIn("MXRF11", texto)
        self.assertIn("PETR4", texto)

    def test_usuario_ve_somente_documentos_dos_favoritos(self):
        texto = self.menu.texto_novos_documentos(tickers_permitidos=frozenset({"MXRF11"}))
        self.assertIn("MXRF11", texto)
        self.assertNotIn("PETR4", texto)

    def test_sem_favoritos_nao_lista_nem_consulta_o_banco(self):
        sys.modules["atualizador_documentos"] = pytypes.SimpleNamespace(
            SessionDB=lambda: (_ for _ in ()).throw(AssertionError("nao deveria consultar"))
        )
        texto = self.menu.texto_novos_documentos(tickers_permitidos=frozenset())
        self.assertEqual(texto, self.menu.TEXTO_ATIVOS_VAZIOS)


if __name__ == "__main__":
    unittest.main()
