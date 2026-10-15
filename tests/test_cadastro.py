"""Testes do cadastro de usuarios e da aprovacao pelo administrador (Etapa 2).

Cobrem o fluxo completo atraves do bot real (``bot.loader.BotAutorizado``) sem
nenhuma chamada de rede e sem tocar no Neon:

* o banco e um SQLite em memoria isolado, ligado ao repositorio por um
  ``sessionmaker`` injetado (``pipeline_dados.repositorio_usuarios``);
* ``telebot`` e instanciado com a validacao de token neutralizada;
* ``send_message``/``answer_callback_query``/``edit_message_text`` sao
  substituidos por fakes que apenas registram as chamadas.

Nenhum teste acessa ``DATABASE_URL`` real: o repositorio nunca chama
``obter_session_factory`` original durante os testes.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import telebot  # noqa: E402
import telebot.util  # noqa: E402
from telebot import types  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import config  # noqa: E402
import pipeline_dados.repositorio_usuarios as repo_mod  # noqa: E402
from bot import permissoes  # noqa: E402
from bot.telegram_utils import TEXTO_ACESSO_NEGADO  # noqa: E402
from pipeline_dados.modelos_usuarios import (  # noqa: E402
    STATUS_APROVADO,
    STATUS_PENDENTE,
    STATUS_REJEITADO,
    STATUS_SUSPENSO,
    BaseUsuarios,
    Usuario,
)
from pipeline_dados.repositorio_usuarios import RepositorioUsuarios  # noqa: E402

ADMIN_ID = 8867098987
USER_ID = 5336458734
NOVO_ID = 111111111
DESCONHECIDO_ID = 222222222
TOKEN_FALSO = "123456:FAKE-TOKEN-CADASTRO-TESTE"


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


class TestCadastroEAprovacao(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._backup = {
            "USUARIOS_AUTORIZADOS": config.USUARIOS_AUTORIZADOS,
            "CHATS_AUTORIZADOS": config.CHATS_AUTORIZADOS,
            "TELEGRAM_BOT_TOKEN": getattr(config, "TELEGRAM_BOT_TOKEN", None),
            "TELEGRAM_CHAT_ID": getattr(config, "TELEGRAM_CHAT_ID", None),
            "TELEGRAM_ADMIN_ID": getattr(config, "TELEGRAM_ADMIN_ID", None),
        }
        config.USUARIOS_AUTORIZADOS = {
            str(ADMIN_ID): config.PAPEL_ADMIN,
            str(USER_ID): config.PAPEL_USUARIO,
        }
        config.CHATS_AUTORIZADOS = [str(ADMIN_ID), str(USER_ID)]
        config.TELEGRAM_CHAT_ID = str(ADMIN_ID)
        config.TELEGRAM_ADMIN_ID = str(ADMIN_ID)

        telebot.util.validate_token = lambda *args, **kwargs: None
        config.TELEGRAM_BOT_TOKEN = TOKEN_FALSO

        cls._factory_original = repo_mod.obter_session_factory

        sys.modules.pop("bot.cadastro", None)
        sys.modules.pop("bot.loader", None)
        import bot.loader as loader

        # Importar o cadastro DEPOIS do loader registra seus handlers no mesmo
        # objeto `bot` utilizado pelo loader.
        import bot.cadastro as cadastro

        cls.loader = loader
        cls.cadastro = cadastro
        cls.bot = loader.bot
        cls.executados = []

        @cls.bot.message_handler(commands=["relatorios"])
        def _relatorios(message):
            cls.executados.append(("cmd", "relatorios"))

        @cls.bot.message_handler(commands=["forcar_cvm"])
        def _forcar_cvm(message):
            cls.executados.append(("cmd", "forcar_cvm"))

    @classmethod
    def tearDownClass(cls):
        repo_mod.obter_session_factory = cls._factory_original
        for chave, valor in cls._backup.items():
            setattr(config, chave, valor)
        sys.modules.pop("bot.cadastro", None)
        sys.modules.pop("bot.loader", None)

    # -- Infraestrutura de teste -------------------------------------------

    def setUp(self):
        type(self).executados.clear()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        BaseUsuarios.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        # `obter_session_factory` deve RETORNAR a fabrica (que o repositorio
        # entao chama para abrir cada sessao).
        repo_mod.obter_session_factory = lambda: self.Session

        self.enviados = []
        self.respostas = []
        self.editados = []
        self.bot.send_message = (
            lambda chat_id, text, **k: self.enviados.append((chat_id, text, k))
        )
        self.bot.answer_callback_query = (
            lambda cid, text=None, **k: self.respostas.append((cid, text))
        )
        self.bot.edit_message_text = (
            lambda text, chat_id, msg_id, **k: self.editados.append(
                (chat_id, msg_id, text)
            )
        )

    def tearDown(self):
        self.engine.dispose()

    # -- Utilitarios -------------------------------------------------------

    def _seed(self, telegram_user_id, status, papel="user", nome=None, chat_id=None):
        sessao = self.Session()
        try:
            usuario = Usuario(
                nome=nome,
                papel=papel,
                ativo=(status == STATUS_APROVADO),
                telegram_user_id=int(telegram_user_id),
                telegram_chat_id=chat_id,
                status_cadastro=status,
            )
            sessao.add(usuario)
            sessao.commit()
            sessao.refresh(usuario)
            return usuario.para_dto()
        finally:
            sessao.close()

    def _usuario(self, telegram_user_id):
        return RepositorioUsuarios().obter_por_telegram_id(telegram_user_id)

    def _contar(self, telegram_user_id):
        sessao = self.Session()
        try:
            return (
                sessao.query(Usuario)
                .filter(Usuario.telegram_user_id == int(telegram_user_id))
                .count()
            )
        finally:
            sessao.close()

    def _textos_para(self, destino):
        return [t for (cid, t, _k) in self.enviados if str(cid) == str(destino)]

    def _notificacoes_admin(self):
        return [
            t
            for (cid, t, _k) in self.enviados
            if str(cid) == str(ADMIN_ID) and "Nova solicitação" in t
        ]

    def _assert_negado(self):
        self.assertTrue(
            any(r[1] == TEXTO_ACESSO_NEGADO for r in self.respostas)
            or any(t == TEXTO_ACESSO_NEGADO for t in (c[1] for c in self.enviados)),
            "esperava uma resposta de acesso negado",
        )

    # -- FASE C: cadastro --------------------------------------------------

    def test_novo_usuario_recebe_pendente_e_admin_notificado(self):
        self.bot.process_new_updates([_update_mensagem("/start", NOVO_ID)])

        dto = self._usuario(NOVO_ID)
        self.assertIsNotNone(dto)
        self.assertEqual(dto.status, STATUS_PENDENTE)
        self.assertEqual(dto.telegram_chat_id, NOVO_ID)

        self.assertEqual(len(self._notificacoes_admin()), 1)
        self.assertTrue(
            any("aguardando" in t for t in self._textos_para(NOVO_ID)),
            "o solicitante deve ser informado de que aguarda aprovacao",
        )

    def test_solicitacoes_repetidas_nao_duplicam_cadastro(self):
        for _ in range(3):
            self.bot.process_new_updates([_update_mensagem("/start", NOVO_ID)])

        self.assertEqual(self._contar(NOVO_ID), 1)
        # A notificacao ao admin acontece somente na criacao (uma vez).
        self.assertEqual(len(self._notificacoes_admin()), 1)

    def test_conta_administrativa_existente_nao_e_recriada(self):
        self.bot.process_new_updates([_update_mensagem("/start", ADMIN_ID)])

        # O admin ja e autorizado por config: entra direto, sem criar conta.
        self.assertIsNone(self._usuario(ADMIN_ID))
        self.assertEqual(self._contar(ADMIN_ID), 0)
        self.assertTrue(
            any("Terminal Institucional" in t for t in self._textos_para(ADMIN_ID))
        )

    def test_usuario_aprovado_recebe_menu_ao_enviar_start(self):
        self._seed(NOVO_ID, STATUS_APROVADO, chat_id=NOVO_ID)
        self.bot.process_new_updates([_update_mensagem("/start", NOVO_ID)])
        self.assertTrue(
            any("Terminal Institucional" in t for t in self._textos_para(NOVO_ID))
        )

    def test_usuario_rejeitado_recebe_negacao_controlada(self):
        self._seed(NOVO_ID, STATUS_REJEITADO, chat_id=NOVO_ID)
        self.bot.process_new_updates([_update_mensagem("/start", NOVO_ID)])
        self.assertTrue(
            any("recusado" in t for t in self._textos_para(NOVO_ID))
        )
        self.assertFalse(
            any("Terminal Institucional" in t for t in self._textos_para(NOVO_ID))
        )

    def test_usuario_suspenso_recebe_negacao_controlada(self):
        self._seed(NOVO_ID, STATUS_SUSPENSO, chat_id=NOVO_ID)
        self.bot.process_new_updates([_update_mensagem("/start", NOVO_ID)])
        self.assertTrue(
            any("suspenso" in t for t in self._textos_para(NOVO_ID))
        )

    def test_falha_de_banco_no_cadastro_nao_concede_acesso(self):
        class RepositorioQuebrado:
            def criar_solicitacao(self, *args, **kwargs):
                raise RuntimeError("banco indisponivel")

        original = self.cadastro.RepositorioUsuarios
        self.cadastro.RepositorioUsuarios = RepositorioQuebrado
        try:
            self.bot.process_new_updates([_update_mensagem("/start", NOVO_ID)])
        finally:
            self.cadastro.RepositorioUsuarios = original

        self.assertTrue(
            any(
                "Nao foi possível concluir o cadastro" in t
                or "Não foi possível concluir o cadastro" in t
                for t in self._textos_para(NOVO_ID)
            )
        )
        self.assertFalse(
            any("Terminal Institucional" in t for t in self._textos_para(NOVO_ID))
        )

    # -- FASE E: controle de acesso ---------------------------------------

    def test_usuario_pendente_nao_acessa_comando_protegido(self):
        self._seed(NOVO_ID, STATUS_PENDENTE, chat_id=NOVO_ID)
        self.bot.process_new_updates([_update_mensagem("/relatorios", NOVO_ID)])
        self.assertEqual(self.executados, [])
        self._assert_negado()

    def test_usuario_aprovado_acessa_somente_o_que_o_papel_permite(self):
        self._seed(NOVO_ID, STATUS_APROVADO, chat_id=NOVO_ID)
        self.bot.process_new_updates([_update_mensagem("/relatorios", NOVO_ID)])
        self.assertEqual(self.executados, [("cmd", "relatorios")])

        type(self).executados.clear()
        self.bot.process_new_updates([_update_mensagem("/forcar_cvm", NOVO_ID)])
        self.assertEqual(self.executados, [])
        self._assert_negado()

    def test_usuario_rejeitado_nao_acessa_comando_protegido(self):
        self._seed(NOVO_ID, STATUS_REJEITADO, chat_id=NOVO_ID)
        self.bot.process_new_updates([_update_mensagem("/relatorios", NOVO_ID)])
        self.assertEqual(self.executados, [])

    def test_usuario_suspenso_nao_acessa_comando_protegido(self):
        self._seed(NOVO_ID, STATUS_SUSPENSO, chat_id=NOVO_ID)
        self.bot.process_new_updates([_update_mensagem("/relatorios", NOVO_ID)])
        self.assertEqual(self.executados, [])

    def test_administrador_mantem_suas_permissoes(self):
        self.bot.process_new_updates([_update_mensagem("/forcar_cvm", ADMIN_ID)])
        self.assertEqual(self.executados, [("cmd", "forcar_cvm")])

    def test_falha_de_banco_na_autorizacao_nao_concede_acesso(self):
        def _explodir():
            raise RuntimeError("banco indisponivel")

        original = repo_mod.obter_session_factory
        repo_mod.obter_session_factory = _explodir
        try:
            self.assertIsNone(permissoes.obter_papel(DESCONHECIDO_ID))
            permitido, operacao = permissoes.verificar_update(
                _update_mensagem("/relatorios", DESCONHECIDO_ID)
            )
        finally:
            repo_mod.obter_session_factory = original

        self.assertFalse(permitido)
        self.assertEqual(operacao, "comando:/relatorios")

    # -- FASE D: aprovacao administrativa ---------------------------------

    def test_usuario_comum_nao_consegue_aprovar(self):
        dto = self._seed(NOVO_ID, STATUS_PENDENTE, chat_id=NOVO_ID)
        self.bot.process_new_updates(
            [_update_callback(f"cad_aprovar_{dto.id}", USER_ID)]
        )

        self.assertEqual(self._usuario(NOVO_ID).status, STATUS_PENDENTE)
        self._assert_negado()

    def test_administrador_autorizado_aprova_e_notifica(self):
        dto = self._seed(NOVO_ID, STATUS_PENDENTE, chat_id=NOVO_ID)
        self.bot.process_new_updates(
            [_update_callback(f"cad_aprovar_{dto.id}", ADMIN_ID)]
        )

        self.assertEqual(self._usuario(NOVO_ID).status, STATUS_APROVADO)
        self.assertTrue(
            any("APROVADA" in (t or "") for (_cid, t) in self.respostas)
        )
        self.assertTrue(
            any("liberado" in t for t in self._textos_para(NOVO_ID)),
            "o solicitante deve ser avisado da aprovacao",
        )

    def test_administrador_autorizado_rejeita_e_notifica(self):
        dto = self._seed(NOVO_ID, STATUS_PENDENTE, chat_id=NOVO_ID)
        self.bot.process_new_updates(
            [_update_callback(f"cad_rejeitar_{dto.id}", ADMIN_ID)]
        )

        self.assertEqual(self._usuario(NOVO_ID).status, STATUS_REJEITADO)
        self.assertTrue(any("REJEITADA" in (t or "") for (_cid, t) in self.respostas))

    def test_callback_repetido_e_idempotente(self):
        dto = self._seed(NOVO_ID, STATUS_PENDENTE, chat_id=NOVO_ID)
        callback = _update_callback(f"cad_aprovar_{dto.id}", ADMIN_ID)

        self.bot.process_new_updates([callback])
        self.bot.process_new_updates([callback])

        self.assertEqual(self._usuario(NOVO_ID).status, STATUS_APROVADO)
        # A notificacao de liberacao ao usuario ocorre apenas uma vez.
        self.assertEqual(
            sum(1 for t in self._textos_para(NOVO_ID) if "liberado" in t), 1
        )
        self.assertTrue(
            any("Já constava" in (t or "") for (_cid, t) in self.respostas)
        )

    def test_callback_para_solicitacao_inexistente(self):
        self.bot.process_new_updates(
            [_update_callback("cad_aprovar_999999", ADMIN_ID)]
        )
        self.assertTrue(
            any(
                "Não foi possível" in (t or "") or "Nao foi possível" in (t or "")
                for (_cid, t) in self.respostas
            )
        )

    def test_callback_malformado_negado(self):
        self.bot.process_new_updates([_update_callback("cad_xyz", ADMIN_ID)])
        self._assert_negado()

    def test_callback_de_autor_desconhecido_negado(self):
        dto = self._seed(NOVO_ID, STATUS_PENDENTE, chat_id=NOVO_ID)
        self.bot.process_new_updates(
            [_update_callback(f"cad_aprovar_{dto.id}", DESCONHECIDO_ID)]
        )
        # O update e descartado antes do handler (chat fora da allowlist).
        self.assertEqual(self._usuario(NOVO_ID).status, STATUS_PENDENTE)


if __name__ == "__main__":
    unittest.main()
