"""Testes dos favoritos individuais por usuario (Etapa 3).

Cobrem o repositorio (``pipeline_dados.repositorio_favoritos``) e a interface do
bot (``bot.favoritos``), sempre com um SQLite em memoria isolado e sem nenhuma
conexao ao Neon:

* o repositorio recebe uma ``session_factory`` injetada (via monkeypatch do
  atributo de modulo) e as tabelas ``usuarios``, ``ativos`` e
  ``ativos_acompanhados`` sao criadas apenas no banco de teste;
* o bot e instanciado com a validacao de token neutralizada e os metodos de
  envio substituidos por fakes.

Nenhum teste le ``DATABASE_URL`` nem abre conexao real.
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
import pipeline_dados.repositorio_favoritos as rf  # noqa: E402
import pipeline_dados.repositorio_usuarios as ru  # noqa: E402
from pipeline_dados.banco_dados import Ativo, Base, TipoAtivo  # noqa: E402
from pipeline_dados.modelos_ativos import BaseAcompanhados  # noqa: E402
from pipeline_dados.modelos_usuarios import (  # noqa: E402
    STATUS_APROVADO,
    STATUS_PENDENTE,
    STATUS_REJEITADO,
    STATUS_SUSPENSO,
    BaseUsuarios,
    Usuario,
)
from pipeline_dados.repositorio_favoritos import (  # noqa: E402
    AtivoNaoCadastradoError,
    RepositorioFavoritos,
)

ADMIN_ID = 8867098987
USER1_ID = 5336458734
USER2_ID = 111111111
TOKEN_FALSO = "123456:FAKE-TOKEN-FAVORITOS-TESTE"


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


def _update_mensagem(texto, user_id):
    payload = {
        "update_id": 3,
        "message": {
            "message_id": 3,
            "date": 0,
            "chat": {"id": user_id, "type": "private"},
            "from": {"id": user_id, "is_bot": False, "first_name": "Teste"},
            "text": texto,
        },
    }
    return types.Update.de_json(json.dumps(payload))


class _BaseBanco:
    """Cria um banco SQLite isolado e injeta as fabricas de sessao."""

    def _preparar_banco(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        BaseUsuarios.metadata.create_all(self.engine)
        BaseAcompanhados.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self._rf_original = rf.obter_session_factory
        self._ru_original = ru.obter_session_factory
        rf.obter_session_factory = lambda: self.Session
        ru.obter_session_factory = lambda: self.Session

    def _encerrar_banco(self):
        rf.obter_session_factory = self._rf_original
        ru.obter_session_factory = self._ru_original
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

    def _criar_usuario(self, telegram_id, status, papel="user", ativo=None):
        sessao = self.Session()
        try:
            if ativo is None:
                ativo = status == STATUS_APROVADO
            usuario = Usuario(
                nome=f"user-{telegram_id}",
                papel=papel,
                ativo=ativo,
                telegram_user_id=int(telegram_id),
                telegram_chat_id=int(telegram_id),
                status_cadastro=status,
            )
            sessao.add(usuario)
            sessao.commit()
            sessao.refresh(usuario)
            return usuario.id
        finally:
            sessao.close()


class TestRepositorioFavoritos(_BaseBanco, unittest.TestCase):
    def setUp(self):
        self._preparar_banco()
        self.user1 = self._criar_usuario(USER1_ID, STATUS_APROVADO)
        self.user2 = self._criar_usuario(USER2_ID, STATUS_APROVADO)
        self.ativo_fii = self._criar_ativo("MXRF11", "fii")
        self.ativo_acao = self._criar_ativo("PETR4", "acao")
        self.repo = RepositorioFavoritos()

    def tearDown(self):
        self._encerrar_banco()

    def test_listar_inicialmente_vazio(self):
        self.assertEqual(self.repo.listar(self.user1, "fii"), [])

    def test_adicionar_ativo_existente(self):
        dto, criado = self.repo.adicionar(self.user1, "MXRF11")
        self.assertTrue(criado)
        self.assertEqual(dto.ticker, "MXRF11")
        self.assertEqual(dto.tipo, "fii")
        self.assertTrue(self.repo.esta_acompanhado(self.user1, self.ativo_fii))
        self.assertEqual(
            [f.ticker for f in self.repo.listar(self.user1, "fii")], ["MXRF11"]
        )

    def test_impedir_duplicacoes(self):
        self.repo.adicionar(self.user1, "MXRF11")
        _dto, criado = self.repo.adicionar(self.user1, "MXRF11")
        self.assertFalse(criado)
        self.assertEqual(len(self.repo.listar(self.user1, "fii")), 1)

    def test_remover_ativo(self):
        self.repo.adicionar(self.user1, "MXRF11")
        self.assertTrue(self.repo.remover(self.user1, "MXRF11"))
        self.assertEqual(self.repo.listar(self.user1, "fii"), [])

    def test_remover_ativo_nao_favoritado(self):
        self.assertFalse(self.repo.remover(self.user1, "MXRF11"))

    def test_rejeitar_ativo_inexistente(self):
        with self.assertRaises(AtivoNaoCadastradoError):
            self.repo.adicionar(self.user1, "ZZZZ9")
        self.assertEqual(self.repo.listar(self.user1), [])

    def test_remover_ativo_inexistente_nao_quebra(self):
        self.assertFalse(self.repo.remover(self.user1, "ZZZZ9"))

    def test_isolamento_entre_usuarios(self):
        self.repo.adicionar(self.user1, "MXRF11")
        self.repo.adicionar(self.user2, "PETR4")
        self.assertEqual(
            [f.ticker for f in self.repo.listar(self.user1, "fii")], ["MXRF11"]
        )
        self.assertEqual(self.repo.listar(self.user1, "acao"), [])
        self.assertEqual(
            [f.ticker for f in self.repo.listar(self.user2, "acao")], ["PETR4"]
        )
        self.assertEqual(self.repo.listar(self.user2, "fii"), [])
        # Um usuario nao remove o favorito de outro.
        self.assertFalse(self.repo.remover(self.user2, "MXRF11"))
        self.assertTrue(self.repo.esta_acompanhado(self.user1, self.ativo_fii))

    def test_listar_disponiveis_exclui_ja_acompanhados(self):
        self.repo.adicionar(self.user1, "MXRF11")
        disponiveis = self.repo.listar_disponiveis(self.user1, "fii")
        self.assertNotIn("MXRF11", disponiveis)
        self.assertIn("PETR4", self.repo.listar_disponiveis(self.user1, "acao"))

    def test_conflito_de_insercao_e_idempotente(self):
        self.repo.adicionar(self.user1, "MXRF11")

        real_obter = self.repo._obter_vinculo
        estado = {"chamadas": 0}

        def _obter_que_perde_a_corrida(usuario_id, ativo_id):
            estado["chamadas"] += 1
            if estado["chamadas"] == 1:
                return None  # simula a pre-checagem falhando (corrida)
            return real_obter(usuario_id, ativo_id)

        self.repo._obter_vinculo = _obter_que_perde_a_corrida
        try:
            dto, criado = self.repo.adicionar(self.user1, "MXRF11")
        finally:
            self.repo._obter_vinculo = real_obter

        self.assertFalse(criado)
        self.assertIsNotNone(dto)
        self.assertEqual(len(self.repo.listar(self.user1, "fii")), 1)

    def test_falha_de_banco_propaga(self):
        def _explodir():
            raise RuntimeError("banco indisponivel")

        rf.obter_session_factory = _explodir
        try:
            with self.assertRaises(RuntimeError):
                self.repo.listar(self.user1, "fii")
        finally:
            rf.obter_session_factory = lambda: self.Session


class TestFavoritosNoBot(_BaseBanco, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._backup = {
            "USUARIOS_AUTORIZADOS": config.USUARIOS_AUTORIZADOS,
            "CHATS_AUTORIZADOS": config.CHATS_AUTORIZADOS,
            "TELEGRAM_BOT_TOKEN": getattr(config, "TELEGRAM_BOT_TOKEN", None),
        }
        config.USUARIOS_AUTORIZADOS = {str(ADMIN_ID): config.PAPEL_ADMIN}
        config.CHATS_AUTORIZADOS = [str(ADMIN_ID)]

        telebot.util.validate_token = lambda *args, **kwargs: None
        config.TELEGRAM_BOT_TOKEN = TOKEN_FALSO

        sys.modules.pop("bot.favoritos", None)
        sys.modules.pop("bot.loader", None)
        import bot.loader as loader

        cls.loader = loader
        cls.bot = loader.bot
        cls.genericos = []
        cls.financeiros = []

        # Ordem: bot.favoritos e importado ANTES do handler generico, espelhando
        # a ordem de main.py (favoritos antes de callbacks_menus).
        import bot.favoritos as favoritos

        cls.favoritos = favoritos

        @cls.bot.callback_query_handler(func=lambda c: c.data == "menu_fiis")
        def _financeiro(call):
            cls.financeiros.append(call.data)

        @cls.bot.callback_query_handler(func=lambda call: True)
        def _generico(call):
            cls.genericos.append(call.data)

    @classmethod
    def tearDownClass(cls):
        for chave, valor in cls._backup.items():
            setattr(config, chave, valor)
        sys.modules.pop("bot.favoritos", None)
        sys.modules.pop("bot.loader", None)

    def setUp(self):
        self._preparar_banco()
        self.user = self._criar_usuario(USER1_ID, STATUS_APROVADO)
        self._criar_ativo("MXRF11", "fii")
        self._criar_ativo("PETR4", "acao")

        type(self).genericos.clear()
        type(self).financeiros.clear()
        self.enviados = []
        self.respostas = []
        self.editados = []
        self.bot.send_message = (
            lambda chat_id, text, **k: self.enviados.append((chat_id, text))
        )
        self.bot.answer_callback_query = (
            lambda cid, text=None, **k: self.respostas.append((cid, text))
        )
        self.bot.edit_message_text = (
            lambda text, chat_id, msg_id, **k: self.editados.append((chat_id, msg_id, text))
        )

    def tearDown(self):
        self._encerrar_banco()

    def _textos(self):
        return [t for (_cid, _mid, t) in self.editados] + [t for (_cid, t) in self.enviados]

    def _respostas_texto(self):
        return [t or "" for (_cid, t) in self.respostas]

    def _semear_favorito(self, usuario_id, ticker):
        RepositorioFavoritos().adicionar(usuario_id, ticker)

    # -- Ordem dos handlers ------------------------------------------------

    def test_callback_especifico_antes_do_generico(self):
        self.bot.process_new_updates([_update_callback("favoritos_fiis", USER1_ID)])
        self.assertEqual(self.genericos, [])
        self.assertTrue(any("Favoritos" in t for t in self._textos()))

    def test_callback_financeiro_continua_fluindo(self):
        self.bot.process_new_updates([_update_callback("menu_fiis", USER1_ID)])
        self.assertEqual(self.financeiros, ["menu_fiis"])
        self.assertEqual(self.genericos, [])

    def test_callback_nao_favorito_cai_no_generico(self):
        self.bot.process_new_updates([_update_callback("painel_PETR4_acao", USER1_ID)])
        self.assertEqual(self.genericos, ["painel_PETR4_acao"])

    # -- Listar / adicionar / remover -------------------------------------

    def test_listar_favoritos_do_usuario(self):
        self._semear_favorito(self.user, "MXRF11")
        self.bot.process_new_updates([_update_callback("favoritos_fiis", USER1_ID)])
        self.assertTrue(any("MXRF11" in t for t in self._textos()))

    def test_adicionar_ativo_existente_pelo_bot(self):
        self.bot.process_new_updates([_update_callback("favnew_MXRF11_fii", USER1_ID)])
        self.assertTrue(
            RepositorioFavoritos().esta_acompanhado(
                self.user, RepositorioFavoritos().resolver_ativo("MXRF11")[0]
            )
        )
        self.assertTrue(any("adicionado" in t for t in self._respostas_texto()))

    def test_impedir_duplicacao_pelo_bot(self):
        self._semear_favorito(self.user, "MXRF11")
        self.bot.process_new_updates([_update_callback("favnew_MXRF11_fii", USER1_ID)])
        self.assertTrue(any("já estava" in t for t in self._respostas_texto()))
        self.assertEqual(len(RepositorioFavoritos().listar(self.user, "fii")), 1)

    def test_remover_ativo_pelo_bot(self):
        self._semear_favorito(self.user, "MXRF11")
        self.bot.process_new_updates([_update_callback("favrem_MXRF11_fii", USER1_ID)])
        self.assertEqual(RepositorioFavoritos().listar(self.user, "fii"), [])
        self.assertTrue(any("removido" in t for t in self._respostas_texto()))

    def test_adicionar_ativo_inexistente_pelo_bot(self):
        self.bot.process_new_updates([_update_callback("favnew_ZZZZ9_fii", USER1_ID)])
        self.assertTrue(
            any("não está cadastrado" in t for t in self._respostas_texto())
        )
        self.assertEqual(RepositorioFavoritos().listar(self.user, "fii"), [])

    def test_abrir_lista_de_adicionar(self):
        self.bot.process_new_updates([_update_callback("favadd_fii_0", USER1_ID)])
        self.assertTrue(any("Adicionar" in t for t in self._textos()))
        self.assertTrue(any("MXRF11" in t for t in self._textos()))

    # -- Autorizacao -------------------------------------------------------

    def test_usuario_pendente_e_bloqueado(self):
        self._criar_usuario(USER2_ID, STATUS_PENDENTE)
        self.bot.process_new_updates([_update_callback("favoritos_fiis", USER2_ID)])
        self.assertTrue(any("permissão" in t or "permissao" in t for t in self._respostas_texto()))
        self.assertEqual(self.editados, [])

    def test_usuario_rejeitado_e_bloqueado(self):
        self._criar_usuario(USER2_ID, STATUS_REJEITADO)
        self.bot.process_new_updates([_update_callback("favoritos_fiis", USER2_ID)])
        self.assertEqual(self.editados, [])

    def test_usuario_suspenso_e_bloqueado(self):
        self._criar_usuario(USER2_ID, STATUS_SUSPENSO)
        self.bot.process_new_updates([_update_callback("favoritos_fiis", USER2_ID)])
        self.assertEqual(self.editados, [])

    def test_usuario_nao_pode_alterar_favorito_de_outro(self):
        self._semear_favorito(self.user, "MXRF11")
        self._criar_usuario(USER2_ID, STATUS_APROVADO)
        # Usuario 2 tenta remover via callback (o vinculo e do usuario 1).
        self.bot.process_new_updates([_update_callback("favrem_MXRF11_fii", USER2_ID)])
        ativo_id = RepositorioFavoritos().resolver_ativo("MXRF11")[0]
        self.assertTrue(
            RepositorioFavoritos().esta_acompanhado(self.user, ativo_id)
        )

    # -- Permissoes administrativas e financeiras preservadas -------------

    def test_admin_mantem_permissoes(self):
        permitido, operacao = self.loader.permissoes.verificar_update(
            _update_mensagem("/forcar_cvm", ADMIN_ID)
        )
        self.assertTrue(permitido)
        self.assertEqual(operacao, "comando:/forcar_cvm")

    def test_admin_sem_conta_nao_recebe_favoritos_de_outro(self):
        # Admin autorizado por config, mas sem conta no banco: negado com aviso.
        self.bot.process_new_updates([_update_callback("favoritos_fiis", ADMIN_ID)])
        self.assertTrue(
            any("cadastro" in t.lower() for t in self._respostas_texto())
        )

    def test_admin_com_conta_pendente_acessa_favoritos(self):
        # Admin autorizado pela configuracao continua funcionando mesmo com o
        # registro no banco em status "pendente", desde que a conta exista.
        admin_id = self._criar_usuario(
            ADMIN_ID, STATUS_PENDENTE, papel=config.PAPEL_ADMIN, ativo=True
        )
        self._semear_favorito(admin_id, "MXRF11")

        self.bot.process_new_updates([_update_callback("favoritos_fiis", ADMIN_ID)])

        self.assertEqual(self.genericos, [])
        self.assertTrue(any("Favoritos" in t for t in self._textos()))
        self.assertTrue(any("MXRF11" in t for t in self._textos()))

    def test_admin_com_conta_pendente_pode_adicionar_favorito(self):
        self._criar_usuario(
            ADMIN_ID, STATUS_PENDENTE, papel=config.PAPEL_ADMIN, ativo=True
        )

        self.bot.process_new_updates([_update_callback("favnew_MXRF11_fii", ADMIN_ID)])

        self.assertTrue(any("adicionado" in t for t in self._respostas_texto()))

    def test_superadmin_no_banco_nao_concede_privilegios(self):
        # Papel armazenado no banco (nao resolvido por `permissoes`) NAO concede
        # acesso: um usuario "SUPERADMIN" nao reconhecido e tratado como comum e
        # barrado pelo controle de permissoes existente.
        outro_id = 333333333
        self._criar_usuario(outro_id, STATUS_APROVADO, papel="SUPERADMIN", ativo=True)

        self.bot.process_new_updates([_update_callback("favoritos_fiis", outro_id)])

        self.assertEqual(self.editados, [])
        self.assertTrue(
            any("permissão" in (t or "") for (_cid, t) in self.respostas)
        )

    def test_falha_de_banco_na_autorizacao_bloqueia(self):
        def _explodir():
            raise RuntimeError("banco indisponivel")

        ru.obter_session_factory = _explodir
        try:
            self.bot.process_new_updates([_update_callback("favoritos_fiis", USER1_ID)])
        finally:
            ru.obter_session_factory = lambda: self.Session
        self.assertEqual(self.editados, [])


if __name__ == "__main__":
    unittest.main()
