"""Testes do atalho administrativo "Iniciar Revisão Manual".

Regressão coberta: o callback ``iniciar_revisao_pendencias`` e emitido pelo
relatorio pos-varredura (``bot/comandos.py``) e documentado como administrativo.
Ele precisa ser tratado por um handler especifico (que abre a mesma Central de
Revisao do comando ``/revisao``), e nao cair no handler generico de
``bot.callbacks_menus`` respondendo "botao invalido".

Nenhuma rede/banco real: SQLite em memoria isolado e fakes dos metodos de envio.
O bot e instanciado com a validacao de token neutralizada.
"""

import json
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import telebot  # noqa: E402
import telebot.util  # noqa: E402
from telebot import types  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import config  # noqa: E402
from bot import permissoes  # noqa: E402
from bot.telegram_utils import TEXTO_ACESSO_NEGADO, TEXTO_CALLBACK_DESCONHECIDO  # noqa: E402
from pipeline_dados.banco_dados import (  # noqa: E402
    Ativo,
    Base,
    DocumentosQualitativos,
    TipoAtivo,
)

ADMIN_ID = 8867098987
USER_ID = 5336458734
TOKEN_FALSO = "123456:FAKE-TOKEN-REVISAO-TESTE"


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
                "text": "relatorio",
            },
        },
    }
    return types.Update.de_json(json.dumps(payload))


class TestAtalhoRevisaoManual(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._backup = {
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
        config.TELEGRAM_BOT_TOKEN = TOKEN_FALSO

        for nome in ("bot.callbacks_revisao", "bot.loader"):
            sys.modules.pop(nome, None)

        import bot.loader as loader  # noqa: E402
        import bot.callbacks_revisao as revisao  # noqa: E402

        cls.loader = loader
        cls.revisao = revisao
        cls.bot = loader.bot
        cls.bot.inicializar()

        # Imita o handler generico de bot.callbacks_menus, registrado DEPOIS dos
        # callbacks especificos (mesma ordem do main.py). Ele nao deve capturar o
        # atalho de revisao.
        cls.genericos = []

        @cls.bot.callback_query_handler(func=lambda call: True)
        def _generico(call):
            cls.genericos.append(call.data)
            cls.bot.answer_callback_query(call.id, text=TEXTO_CALLBACK_DESCONHECIDO)

    @classmethod
    def tearDownClass(cls):
        for chave, valor in cls._backup.items():
            setattr(config, chave, valor)
        for nome in ("bot.callbacks_revisao", "bot.loader"):
            sys.modules.pop(nome, None)

    def setUp(self):
        type(self).genericos.clear()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self._sessiondb_original = self.revisao.SessionDB
        self.revisao.SessionDB = lambda: self.Session()

        self.enviados = []
        self.respostas = []
        self.editados = []
        self.bot.send_message = (
            lambda chat_id, text, **k: self.enviados.append((chat_id, text, k))
        )
        self.bot.edit_message_text = (
            lambda text, chat_id, msg_id, **k: self.editados.append(
                (chat_id, msg_id, text, k)
            )
        )
        self.bot.answer_callback_query = (
            lambda cid, text=None, **k: self.respostas.append((cid, text, k))
        )

    def tearDown(self):
        self.revisao.SessionDB = self._sessiondb_original
        self.engine.dispose()

    def _semear_pendente(self, ticker="MXRF11", tipo=TipoAtivo.FII):
        sessao = self.Session()
        try:
            ativo = Ativo(ticker=ticker, cnpj=f"cnpj-{ticker}", tipo=tipo)
            sessao.add(ativo)
            sessao.commit()
            sessao.refresh(ativo)
            doc = DocumentosQualitativos(
                ativo_id=ativo.id,
                data_publicacao=date(2026, 5, 1),
                tipo_documento="Relatório Gerencial",
                url_pdf="https://drive.example.com/arquivo.pdf",
                status_processamento="AGUARDANDO_REVISAO",
            )
            sessao.add(doc)
            sessao.commit()
            return ativo.id
        finally:
            sessao.close()

    # -- Classificacao -----------------------------------------------------

    def test_atalho_e_classificado_como_administrativo(self):
        _nome, nivel = permissoes.operacao_de_callback("iniciar_revisao_pendencias")
        self.assertEqual(nivel, permissoes.NIVEL_ADMIN)

    # -- Administrador -----------------------------------------------------

    def test_admin_abre_a_central_de_revisao(self):
        self._semear_pendente()
        self.bot.process_new_updates(
            [_update_callback("iniciar_revisao_pendencias", ADMIN_ID)]
        )
        # Nao caiu no handler generico.
        self.assertEqual(self.genericos, [])
        self.assertTrue(self.editados)
        _chat, _msg, texto, kwargs = self.editados[-1]
        self.assertIn("Central de Revisoes", texto)
        self.assertIn("duas checagens da IA", texto)
        callbacks = [
            botao.callback_data
            for linha in kwargs["reply_markup"].keyboard
            for botao in linha
            if botao.callback_data
        ]
        self.assertIn("rev_t_MXRF11", callbacks)

    def test_admin_sem_pendencias_mostra_mesa_limpa(self):
        self.bot.process_new_updates(
            [_update_callback("iniciar_revisao_pendencias", ADMIN_ID)]
        )
        self.assertEqual(self.genericos, [])
        self.assertTrue(self.editados)
        _chat, _msg, texto, _kwargs = self.editados[-1]
        self.assertIn("Nao ha documentos aguardando revisao", texto)

    # -- Usuario comum -----------------------------------------------------

    def test_dupla_checagem_aparece_no_texto_de_inspecao(self):
        from types import SimpleNamespace
        from bot.callbacks_revisao import _texto_dupla_checagem

        doc = SimpleNamespace(
            resumo_ia='{"checagem_1": {"tipo": "Fato Relevante", "confianca": 90}, '
            '"checagem_2": {"tipo": "Comunicado ao Mercado", "confianca": 70}, '
            '"acordo": false}'
        )
        texto = _texto_dupla_checagem(doc, "Outros")
        self.assertIn("Duas checagens da IA", texto)
        self.assertIn("Fato Relevante", texto)
        self.assertIn("Comunicado ao Mercado", texto)

    def test_usuario_comum_nao_abre_a_revisao(self):
        self._semear_pendente()
        self.bot.process_new_updates(
            [_update_callback("iniciar_revisao_pendencias", USER_ID)]
        )
        self.assertEqual(self.genericos, [])
        self.assertEqual(self.editados, [])
        self.assertTrue(self.respostas)
        self.assertEqual(self.respostas[-1][1], TEXTO_ACESSO_NEGADO)


if __name__ == "__main__":
    unittest.main()
