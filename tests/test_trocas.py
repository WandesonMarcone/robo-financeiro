"""Testes das solicitacoes de troca de favorito (bot.trocas + repositorio).

SQLite em memoria isolado, sem conexao ao Neon e sem Telegram real: o bot e
instanciado com validacao de token neutralizada e envios substituidos por fakes
(mesmo padrao de ``tests/test_favoritos.py``).
"""

import datetime
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import telebot  # noqa: E402
import telebot.util  # noqa: E402
from telebot import types  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import config  # noqa: E402
import pipeline_dados.repositorio_favoritos as rf  # noqa: E402
import pipeline_dados.repositorio_trocas as rt  # noqa: E402
import pipeline_dados.repositorio_usuarios as ru  # noqa: E402
from pipeline_dados.banco_dados import Ativo, Base, TipoAtivo  # noqa: E402
from pipeline_dados.modelos_ativos import BaseAcompanhados  # noqa: E402
from pipeline_dados.modelos_trocas import BaseTrocas, SolicitacaoTroca  # noqa: E402
from pipeline_dados.modelos_usuarios import (  # noqa: E402
    STATUS_APROVADO,
    BaseUsuarios,
    Usuario,
)
from pipeline_dados.repositorio_favoritos import RepositorioFavoritos  # noqa: E402
from pipeline_dados.repositorio_trocas import (  # noqa: E402
    RepositorioTrocas,
    TrocaInvalidaError,
)

TOKEN_FALSO = "123456:FAKE-TOKEN-TROCAS-TESTE"
ADMIN_ID = 8867098987
USER1_ID = 5336458734
USER2_ID = 111111111


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


class _BaseBanco:
    def _preparar_banco(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        for base in (Base, BaseUsuarios, BaseAcompanhados, BaseTrocas):
            base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self._orig = (
            rf.obter_session_factory,
            ru.obter_session_factory,
            rt.obter_session_factory,
        )
        rf.obter_session_factory = lambda: self.Session
        ru.obter_session_factory = lambda: self.Session
        rt.obter_session_factory = lambda: self.Session

    def _encerrar_banco(self):
        (
            rf.obter_session_factory,
            ru.obter_session_factory,
            rt.obter_session_factory,
        ) = self._orig
        self.engine.dispose()

    def _criar_ativo(self, ticker, tipo):
        sessao = self.Session()
        try:
            enum_tipo = TipoAtivo.FII if tipo == "fii" else TipoAtivo.ACAO
            ativo = Ativo(ticker=ticker, cnpj=f"cnpj-{ticker}", tipo=enum_tipo)
            sessao.add(ativo)
            sessao.commit()
            sessao.refresh(ativo)
            return ativo.id
        finally:
            sessao.close()

    def _criar_usuario(self, telegram_id, papel="user"):
        sessao = self.Session()
        try:
            usuario = Usuario(
                nome=f"user-{telegram_id}",
                papel=papel,
                ativo=True,
                telegram_user_id=int(telegram_id),
                telegram_chat_id=int(telegram_id),
                status_cadastro=STATUS_APROVADO,
            )
            sessao.add(usuario)
            sessao.commit()
            sessao.refresh(usuario)
            return usuario.id
        finally:
            sessao.close()

    def _tickers(self, usuario_id, tipo=None):
        return sorted(
            f.ticker for f in RepositorioFavoritos().listar(usuario_id, tipo)
        )


class TestRepositorioTrocas(_BaseBanco, unittest.TestCase):
    def setUp(self):
        self._preparar_banco()
        self.user = self._criar_usuario(USER1_ID)
        self.mxrf = self._criar_ativo("MXRF11", "fii")
        self.hglg = self._criar_ativo("HGLG11", "fii")
        self.petr = self._criar_ativo("PETR4", "acao")
        RepositorioFavoritos().adicionar(self.user, "MXRF11")
        self.repo = RepositorioTrocas()

    def tearDown(self):
        self._encerrar_banco()

    def test_criar_nao_altera_favoritos(self):
        dto, criado = self.repo.criar(self.user, self.mxrf, self.hglg)
        self.assertTrue(criado)
        self.assertEqual(self._tickers(self.user), ["MXRF11"])
        self.assertEqual(self.repo.pendente_do_usuario(self.user).id, dto.id)

    def test_pendente_duplicada_retorna_a_existente(self):
        a, _ = self.repo.criar(self.user, self.mxrf, self.hglg)
        b, criado = self.repo.criar(self.user, self.mxrf, self.hglg)
        self.assertFalse(criado)
        self.assertEqual(a.id, b.id)

    def test_tipos_diferentes_sao_recusados(self):
        with self.assertRaises(Exception):
            self.repo.criar(self.user, self.mxrf, self.petr)

    def test_aprovar_aplica_troca_uma_unica_vez(self):
        dto, _ = self.repo.criar(self.user, self.mxrf, self.hglg)
        _d, aplicado = self.repo.aplicar_aprovacao(dto.id, autor_id=ADMIN_ID)
        self.assertTrue(aplicado)
        self.assertEqual(self._tickers(self.user), ["HGLG11"])
        # Segundo clique: idempotente, nada muda.
        _d, aplicado = self.repo.aplicar_aprovacao(dto.id, autor_id=ADMIN_ID)
        self.assertFalse(aplicado)
        self.assertEqual(self._tickers(self.user), ["HGLG11"])


    def test_historico_permite_nova_solicitacao_do_mesmo_ativo(self):
        dto, _ = self.repo.criar(self.user, self.mxrf, self.hglg)
        self.repo.decidir(
            dto.id,
            "rejeitada",
            autor_id=ADMIN_ID,
            origens_permitidas={"pendente"},
        )
        novo, criado = self.repo.criar(self.user, self.mxrf, self.hglg)
        self.assertTrue(criado)
        self.assertNotEqual(novo.id, dto.id)
        self.assertEqual(
            self.repo.contar_por_status("rejeitada"), 1
        )

    def test_indice_parcial_bloqueia_duas_pendentes_do_mesmo_ativo(self):
        self.repo.criar(self.user, self.mxrf, self.hglg)
        sessao = self.Session()
        try:
            sessao.add(
                SolicitacaoTroca(
                    usuario_id=self.user,
                    ativo_saida_id=self.mxrf,
                    ativo_entrada_id=self.hglg,
                    status="pendente",
                    criado_em=datetime.datetime.now(),
                )
            )
            with self.assertRaises(IntegrityError):
                sessao.commit()
        finally:
            sessao.rollback()
            sessao.close()

    def test_aprovacao_recusa_quando_vinculo_de_saida_sumiu(self):
        dto, _ = self.repo.criar(self.user, self.mxrf, self.hglg)
        RepositorioFavoritos().remover(self.user, "MXRF11")
        with self.assertRaises(TrocaInvalidaError):
            self.repo.aplicar_aprovacao(dto.id, autor_id=ADMIN_ID)
        self.assertEqual(self.repo.obter(dto.id).status, "pendente")
        self.assertEqual(self._tickers(self.user), [])

    def test_aprovacao_recusa_tipo_divergente_sem_alterar_favoritos(self):
        dto, _ = self.repo.criar(self.user, self.mxrf, self.hglg)
        sessao = self.Session()
        try:
            entrada = sessao.get(Ativo, self.hglg)
            entrada.tipo = TipoAtivo.ACAO
            sessao.commit()
        finally:
            sessao.close()
        with self.assertRaises(TrocaInvalidaError):
            self.repo.aplicar_aprovacao(dto.id, autor_id=ADMIN_ID)
        self.assertEqual(self.repo.obter(dto.id).status, "pendente")
        self.assertEqual(self._tickers(self.user), ["MXRF11"])

    def test_expirada_nao_pode_ser_aprovada_e_historico_permanece(self):
        dto, _ = self.repo.criar(self.user, self.mxrf, self.hglg)
        sessao = self.Session()
        try:
            troca = sessao.get(SolicitacaoTroca, dto.id)
            troca.criado_em = datetime.datetime.utcnow() - datetime.timedelta(hours=5)
            sessao.commit()
        finally:
            sessao.close()
        self.assertGreaterEqual(self.repo.expirar_vencidas(1), 1)
        _d, aplicado = self.repo.aplicar_aprovacao(dto.id, autor_id=ADMIN_ID)
        self.assertFalse(aplicado)
        self.assertEqual(self._tickers(self.user), ["MXRF11"])
        self.assertEqual(self.repo.obter(dto.id).status, "expirada")  # historico


class TestTrocasNoBot(_BaseBanco, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._backup = {
            nome: getattr(config, nome, None)
            for nome in (
                "USUARIOS_AUTORIZADOS",
                "CHATS_AUTORIZADOS",
                "TELEGRAM_BOT_TOKEN",
                "TELEGRAM_CHAT_ID",
                "TELEGRAM_ADMIN_ID",
                "TROCAS_PRAZO_HORAS",
            )
        }
        config.USUARIOS_AUTORIZADOS = {str(ADMIN_ID): config.PAPEL_ADMIN}
        config.CHATS_AUTORIZADOS = [str(ADMIN_ID)]
        config.TELEGRAM_CHAT_ID = str(ADMIN_ID)
        config.TELEGRAM_ADMIN_ID = str(ADMIN_ID)
        telebot.util.validate_token = lambda *a, **k: None
        config.TELEGRAM_BOT_TOKEN = TOKEN_FALSO

        # Reimporta com um bot novo (modulos que guardam ``bot`` no import).
        import bot as pacote

        for nome in ("trocas", "cadastro", "menu_principal", "favoritos", "loader"):
            sys.modules.pop(f"bot.{nome}", None)
            if hasattr(pacote, nome):
                delattr(pacote, nome)
        import bot.loader as loader

        cls.bot = loader.bot
        cls.genericos = []
        import bot.trocas as trocas  # antes do handler generico (ordem de main.py)

        cls.trocas = trocas

        @cls.bot.callback_query_handler(func=lambda call: True)
        def _generico(call):
            cls.genericos.append(call.data)

    @classmethod
    def tearDownClass(cls):
        for chave, valor in cls._backup.items():
            setattr(config, chave, valor)
        import bot as pacote

        for nome in ("trocas", "cadastro", "menu_principal", "favoritos", "loader"):
            sys.modules.pop(f"bot.{nome}", None)
            if hasattr(pacote, nome):
                delattr(pacote, nome)

    def setUp(self):
        self._preparar_banco()
        config.TROCAS_PRAZO_HORAS = 48
        self.user = self._criar_usuario(USER1_ID)
        self.user2 = self._criar_usuario(USER2_ID)
        self.mxrf = self._criar_ativo("MXRF11", "fii")
        self.hglg = self._criar_ativo("HGLG11", "fii")
        self._criar_ativo("PETR4", "acao")
        RepositorioFavoritos().adicionar(self.user, "MXRF11")
        type(self).genericos.clear()
        self.enviados, self.respostas, self.editados = [], [], []
        self.bot.send_message = (
            lambda chat_id, text, **k: self.enviados.append((str(chat_id), text))
        )
        self.bot.answer_callback_query = (
            lambda cid, text=None, **k: self.respostas.append(text or "")
        )
        self.bot.edit_message_text = (
            lambda text, chat_id, msg_id, **k: self.editados.append(text)
        )

    def tearDown(self):
        self._encerrar_banco()

    def _cb(self, dados, uid):
        self.bot.process_new_updates([_update_callback(dados, uid)])

    def _solicitar(self):
        self._cb("troca_conf_MXRF11_HGLG11", USER1_ID)
        pend = RepositorioTrocas().pendente_do_usuario(self.user)
        self.assertIsNotNone(pend)
        return pend.id

    def _tudo(self):
        return self.editados + [t for (_c, t) in self.enviados] + self.respostas

    # -- registro / ordem -------------------------------------------------
    def test_main_importa_trocas_antes_do_handler_generico(self):
        with open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "main.py"),
            encoding="utf-8",
        ) as arq:
            fonte = arq.read()
        self.assertLess(
            fonte.index("import bot.trocas"), fonte.index("import bot.callbacks_menus")
        )

    # -- solicitacao ------------------------------------------------------
    def test_solicitacao_registra_notifica_admin_e_nao_troca(self):
        self._solicitar()
        self.assertEqual(self._tickers(self.user), ["MXRF11"])
        para_admin = [t for (c, t) in self.enviados if c == str(ADMIN_ID)]
        self.assertTrue(para_admin, "admin nao foi notificado")
        msg = para_admin[-1]
        for trecho in ("user-%s" % USER1_ID, "FIIs", "MXRF11", "HGLG11", "Data"):
            self.assertIn(trecho, msg)

    def test_nao_solicita_troca_de_ativo_que_nao_e_favorito(self):
        self._cb("troca_conf_PETR4_HGLG11", USER1_ID)
        self.assertIsNone(RepositorioTrocas().pendente_do_usuario(self.user))

    def test_nao_solicita_troca_de_favorito_de_outro_usuario(self):
        self._cb("troca_conf_MXRF11_HGLG11", USER2_ID)  # user2 nao segue MXRF11
        self.assertIsNone(RepositorioTrocas().pendente_do_usuario(self.user2))

    def test_ativo_inexistente_ou_de_outro_tipo_e_recusado(self):
        self._cb("troca_conf_MXRF11_XXXX99", USER1_ID)
        self._cb("troca_conf_MXRF11_PETR4", USER1_ID)
        self.assertIsNone(RepositorioTrocas().pendente_do_usuario(self.user))

    # -- decisao ----------------------------------------------------------
    def test_aprovar_efetiva_a_troca_e_avisa_usuario(self):
        tid = self._solicitar()
        self._cb(f"trocaadm_do_aprovar_{tid}_pend_0", ADMIN_ID)
        self.assertEqual(self._tickers(self.user), ["HGLG11"])
        self.assertTrue(any(c == str(USER1_ID) for (c, _t) in self.enviados))

    def test_rejeitar_mantem_favoritos(self):
        tid = self._solicitar()
        self._cb(f"trocaadm_do_rejeitar_{tid}_pend_0", ADMIN_ID)
        self.assertEqual(self._tickers(self.user), ["MXRF11"])
        self.assertEqual(RepositorioTrocas().obter(tid).status, "rejeitada")

    def test_clique_duplo_nao_reaplica_nem_inverte(self):
        tid = self._solicitar()
        self._cb(f"trocaadm_do_aprovar_{tid}_pend_0", ADMIN_ID)
        self._cb(f"trocaadm_do_aprovar_{tid}_pend_0", ADMIN_ID)
        self._cb(f"trocaadm_do_rejeitar_{tid}_pend_0", ADMIN_ID)  # callback antigo
        self.assertEqual(self._tickers(self.user), ["HGLG11"])
        self.assertEqual(RepositorioTrocas().obter(tid).status, "aprovada")

    def test_usuario_comum_nao_decide_nem_abre_a_fila(self):
        tid = self._solicitar()
        self._cb(f"trocaadm_do_aprovar_{tid}_pend_0", USER1_ID)
        self._cb("trocaadm_home", USER1_ID)
        self.assertEqual(self._tickers(self.user), ["MXRF11"])
        self.assertEqual(RepositorioTrocas().obter(tid).status, "pendente")

    def test_pedido_vencido_nao_e_aprovado_automaticamente_nem_depois(self):
        tid = self._solicitar()
        config.TROCAS_PRAZO_HORAS = 1
        sessao = self.Session()
        try:
            sessao.get(SolicitacaoTroca, tid).criado_em = (
                datetime.datetime.utcnow() - datetime.timedelta(hours=3)
            )
            sessao.commit()
        finally:
            sessao.close()
        self._cb(f"trocaadm_do_aprovar_{tid}_pend_0", ADMIN_ID)
        self.assertEqual(self._tickers(self.user), ["MXRF11"])
        self.assertEqual(RepositorioTrocas().obter(tid).status, "expirada")

    def test_pedido_vencido_nao_bloqueia_nova_solicitacao(self):
        tid = self._solicitar()
        config.TROCAS_PRAZO_HORAS = 1
        sessao = self.Session()
        try:
            sessao.get(SolicitacaoTroca, tid).criado_em = (
                datetime.datetime.utcnow() - datetime.timedelta(hours=3)
            )
            sessao.commit()
        finally:
            sessao.close()
        self._cb("troca_ini_MXRF11_0", USER1_ID)
        self.assertEqual(RepositorioTrocas().obter(tid).status, "expirada")
        self.assertIsNone(RepositorioTrocas().pendente_do_usuario(self.user))


if __name__ == "__main__":
    unittest.main()
