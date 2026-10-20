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
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import telebot  # noqa: E402
import telebot.util  # noqa: E402
from telebot import types  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import config  # noqa: E402
import pipeline_dados.repositorio_favoritos as fav_mod  # noqa: E402
import pipeline_dados.repositorio_usuarios as repo_mod  # noqa: E402
from bot import permissoes  # noqa: E402
from bot import sessao_cadastro  # noqa: E402
from bot.telegram_utils import TEXTO_ACESSO_NEGADO  # noqa: E402
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
from pipeline_dados.repositorio_favoritos import RepositorioFavoritos  # noqa: E402
from pipeline_dados.repositorio_usuarios import RepositorioUsuarios  # noqa: E402

ADMIN_ID = 8867098987
USER_ID = 5336458734
NOVO_ID = 111111111
DESCONHECIDO_ID = 222222222
TOKEN_FALSO = "123456:FAKE-TOKEN-CADASTRO-TESTE"

# Textos exclusivos do painel apos acesso liberado (nao aparecem no cadastro).
MARCADOR_PAINEL_USUARIO = "painel de investimentos"
MARCADOR_PAINEL_ADMIN = "Painel administrativo"


def _autor(user_id, username=None, last_name=None):
    autor = {"id": user_id, "is_bot": False, "first_name": "Teste"}
    if username is not None:
        autor["username"] = username
    if last_name is not None:
        autor["last_name"] = last_name
    return autor


def _update_mensagem(texto, user_id, username=None, last_name=None):
    payload = {
        "update_id": 1,
        "message": {
            "message_id": 3,
            "date": 0,
            "chat": {"id": user_id, "type": "private"},
            "from": _autor(user_id, username=username, last_name=last_name),
            "text": texto,
        },
    }
    return types.Update.de_json(json.dumps(payload))


def _update_callback(data, user_id, username=None, last_name=None):
    payload = {
        "update_id": 2,
        "callback_query": {
            "id": "cb1",
            "from": _autor(user_id, username=username, last_name=last_name),
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
        sessao_cadastro.limpar_tudo()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        BaseUsuarios.metadata.create_all(self.engine)
        BaseAcompanhados.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        # `obter_session_factory` deve RETORNAR a fabrica (que o repositorio
        # entao chama para abrir cada sessao).
        repo_mod.obter_session_factory = lambda: self.Session
        self._fav_factory_original = fav_mod.obter_session_factory
        fav_mod.obter_session_factory = lambda: self.Session

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
        fav_mod.obter_session_factory = self._fav_factory_original
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

    def _ultima_notificacao_admin(self):
        notificacoes = self._notificacoes_admin()
        return notificacoes[-1] if notificacoes else None

    def _preencher_formulario(
        self,
        user_id,
        nome="João da Silva",
        email="joao.silva@exemplo.com",
        username=None,
        last_name=None,
        confirmar=True,
    ):
        """Executa o formulário completo via bot real (allowlist + permissões)."""
        self.bot.process_new_updates(
            [_update_mensagem("/start", user_id, username=username, last_name=last_name)]
        )
        self.bot.process_new_updates(
            [_update_mensagem(nome, user_id, username=username, last_name=last_name)]
        )
        self.bot.process_new_updates(
            [_update_mensagem(email, user_id, username=username, last_name=last_name)]
        )
        if confirmar:
            self.bot.process_new_updates(
                [
                    _update_callback(
                        "formcad_confirmar",
                        user_id,
                        username=username,
                        last_name=last_name,
                    )
                ]
            )

    # -- FASE C: cadastro --------------------------------------------------

    def test_start_de_novo_usuario_inicia_formulario_sem_criar_registro(self):
        self.bot.process_new_updates([_update_mensagem("/start", NOVO_ID)])

        self.assertIsNone(self._usuario(NOVO_ID))
        self.assertEqual(self._contar(NOVO_ID), 0)
        self.assertEqual(self._notificacoes_admin(), [])
        self.assertTrue(
            any("nome completo" in t.lower() for t in self._textos_para(NOVO_ID)),
            "o formulário deve pedir o nome completo",
        )
        self.assertTrue(
            any("agosto de 2026" in t.lower() for t in self._textos_para(NOVO_ID)),
            "a apresentação inicial deve citar o início do projeto",
        )
        self.assertTrue(
            any("/help" in t for t in self._textos_para(NOVO_ID)),
            "a apresentação inicial deve indicar onde encontrar ajuda",
        )

    def test_formulario_completo_cria_pendente_e_notifica_admin(self):
        self._preencher_formulario(
            NOVO_ID, nome="João da Silva", email="joao.silva@exemplo.com",
            username="joaosilva", last_name="da Silva",
        )

        dto = self._usuario(NOVO_ID)
        self.assertIsNotNone(dto)
        self.assertEqual(dto.status, STATUS_PENDENTE)
        self.assertEqual(dto.telegram_chat_id, NOVO_ID)
        self.assertEqual(dto.nome, "João da Silva")
        self.assertEqual(dto.email, "joao.silva@exemplo.com")

        notificacao = self._ultima_notificacao_admin()
        self.assertIsNotNone(notificacao)
        self.assertIn("João da Silva", notificacao)
        self.assertIn("joao.silva@exemplo.com", notificacao)
        self.assertIn("@joaosilva", notificacao)
        self.assertIn(str(NOVO_ID), notificacao)
        self.assertIn(f"#{dto.id}", notificacao)
        self.assertIn("Pendente", notificacao)

    def test_email_normalizado_para_minusculas(self):
        self._preencher_formulario(NOVO_ID, email="Joao.SILVA@Exemplo.COM")
        self.assertEqual(self._usuario(NOVO_ID).email, "joao.silva@exemplo.com")

    def test_criacao_registra_dados_do_telegram_na_auditoria(self):
        # Username e nome de exibição não têm coluna no banco; devem constar da
        # trilha de auditoria (requisito: registrar os dados do Telegram).
        with self.assertLogs("robo.auditoria", level="INFO") as registro:
            self._preencher_formulario(
                NOVO_ID,
                username="joaosilva",
                last_name="da Silva",
            )
        trilha = "\n".join(registro.output)
        self.assertIn("AUDITORIA_CADASTRO", trilha)
        self.assertIn("acao=solicitacao", trilha)
        self.assertIn("resultado=criada", trilha)
        self.assertIn("username=@joaosilva", trilha)
        self.assertIn("nome_telegram=Teste da Silva", trilha)

    def test_email_invalido_nao_avanca_e_nao_cria_registro(self):
        self.bot.process_new_updates([_update_mensagem("/start", NOVO_ID)])
        self.bot.process_new_updates([_update_mensagem("João da Silva", NOVO_ID)])
        self.bot.process_new_updates([_update_mensagem("joao-arroba-invalido", NOVO_ID)])

        self.assertIsNone(self._usuario(NOVO_ID))
        self.assertTrue(
            any("mail inválido" in t.lower() for t in self._textos_para(NOVO_ID)),
            "deve avisar que o e-mail é inválido",
        )
        # Continua no formulário (sessão ativa), permitindo corrigir.
        self.assertTrue(sessao_cadastro.tem_sessao_ativa(NOVO_ID))

    def test_nome_invalido_nao_avanca(self):
        self.bot.process_new_updates([_update_mensagem("/start", NOVO_ID)])
        self.bot.process_new_updates([_update_mensagem("X", NOVO_ID)])

        self.assertTrue(
            any("Nome inválido" in t for t in self._textos_para(NOVO_ID))
        )
        self.assertIsNone(self._usuario(NOVO_ID))

    def test_help_durante_formulario_nao_encerra_cadastro(self):
        self.bot.process_new_updates([_update_mensagem("/start", NOVO_ID)])
        self.bot.process_new_updates([_update_mensagem("/help", NOVO_ID)])
        self.assertTrue(sessao_cadastro.tem_sessao_ativa(NOVO_ID))
        self.assertIsNone(self._usuario(NOVO_ID))

    def test_cancelar_por_comando_encerra_formulario_sem_registro(self):
        self.bot.process_new_updates([_update_mensagem("/start", NOVO_ID)])
        self.bot.process_new_updates([_update_mensagem("/cancelar", NOVO_ID)])

        self.assertFalse(sessao_cadastro.tem_sessao_ativa(NOVO_ID))
        self.assertIsNone(self._usuario(NOVO_ID))
        self.assertTrue(any("cancelado" in t.lower() for t in self._textos_para(NOVO_ID)))

    def test_cancelar_por_botao_encerra_formulario_sem_registro(self):
        self.bot.process_new_updates([_update_mensagem("/start", NOVO_ID)])
        self.bot.process_new_updates([_update_mensagem("João da Silva", NOVO_ID)])
        self.bot.process_new_updates([_update_mensagem("joao@exemplo.com", NOVO_ID)])
        self.bot.process_new_updates([_update_callback("formcad_cancelar", NOVO_ID)])

        self.assertFalse(sessao_cadastro.tem_sessao_ativa(NOVO_ID))
        self.assertIsNone(self._usuario(NOVO_ID))

    def test_retomar_apos_cancelar_nao_duplica(self):
        self.bot.process_new_updates([_update_mensagem("/start", NOVO_ID)])
        self.bot.process_new_updates([_update_mensagem("/cancelar", NOVO_ID)])
        self._preencher_formulario(NOVO_ID)

        self.assertEqual(self._contar(NOVO_ID), 1)
        self.assertEqual(len(self._notificacoes_admin()), 1)

    def test_solicitacoes_repetidas_nao_duplicam_cadastro(self):
        self._preencher_formulario(NOVO_ID)
        # Repetir /start com solicitação pendente apenas informa o estado.
        self.bot.process_new_updates([_update_mensagem("/start", NOVO_ID)])
        self.bot.process_new_updates([_update_mensagem("/start", NOVO_ID)])

        self.assertEqual(self._contar(NOVO_ID), 1)
        # A notificacao ao admin acontece somente na criacao (uma vez).
        self.assertEqual(len(self._notificacoes_admin()), 1)
        self.assertTrue(
            any("aguardando" in t for t in self._textos_para(NOVO_ID)),
            "o solicitante pendente deve ser informado de que aguarda aprovação",
        )

    def test_confirmar_repetido_nao_duplica(self):
        self._preencher_formulario(NOVO_ID)
        # Segundo clique no botão de confirmação (sessão já encerrada) é inócuo.
        self.bot.process_new_updates([_update_callback("formcad_confirmar", NOVO_ID)])
        self.assertEqual(self._contar(NOVO_ID), 1)
        self.assertEqual(len(self._notificacoes_admin()), 1)

    def test_conta_administrativa_existente_nao_e_recriada(self):
        self.bot.process_new_updates([_update_mensagem("/start", ADMIN_ID)])

        # O admin ja e autorizado por config: entra direto, sem criar conta.
        self.assertIsNone(self._usuario(ADMIN_ID))
        self.assertEqual(self._contar(ADMIN_ID), 0)
        self.assertTrue(
            any(MARCADOR_PAINEL_ADMIN in t for t in self._textos_para(ADMIN_ID))
        )

    def test_usuario_aprovado_recebe_menu_ao_enviar_start(self):
        self._seed(NOVO_ID, STATUS_APROVADO, chat_id=NOVO_ID)
        self.bot.process_new_updates([_update_mensagem("/start", NOVO_ID)])
        self.assertTrue(
            any(MARCADOR_PAINEL_USUARIO in t for t in self._textos_para(NOVO_ID))
        )

    def test_usuario_rejeitado_recebe_negacao_controlada(self):
        self._seed(NOVO_ID, STATUS_REJEITADO, chat_id=NOVO_ID)
        self.bot.process_new_updates([_update_mensagem("/start", NOVO_ID)])
        self.assertTrue(
            any("recusado" in t for t in self._textos_para(NOVO_ID))
        )
        self.assertFalse(
            any(MARCADOR_PAINEL_USUARIO in t for t in self._textos_para(NOVO_ID))
        )

    def test_usuario_suspenso_recebe_negacao_controlada(self):
        self._seed(NOVO_ID, STATUS_SUSPENSO, chat_id=NOVO_ID)
        self.bot.process_new_updates([_update_mensagem("/start", NOVO_ID)])
        self.assertTrue(
            any("suspenso" in t for t in self._textos_para(NOVO_ID))
        )

    def test_falha_de_banco_no_cadastro_nao_concede_acesso(self):
        class RepositorioQuebrado:
            def obter_por_telegram_id(self, *args, **kwargs):
                return None

            def atualizar_chat_id(self, *args, **kwargs):
                return None

            def criar_solicitacao(self, *args, **kwargs):
                raise RuntimeError("banco indisponivel")

        original = self.cadastro.RepositorioUsuarios
        self.cadastro.RepositorioUsuarios = RepositorioQuebrado
        try:
            self._preencher_formulario(NOVO_ID)
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
            any(MARCADOR_PAINEL_USUARIO in t for t in self._textos_para(NOVO_ID))
        )

    # -- Segurança do formulário ------------------------------------------

    def test_callback_de_confirmacao_sem_sessao_nao_cria_registro(self):
        # Sem /start não há sessão; um callback forjado não pode criar conta.
        self.bot.process_new_updates([_update_callback("formcad_confirmar", NOVO_ID)])

        self.assertIsNone(self._usuario(NOVO_ID))
        self.assertEqual(self._contar(NOVO_ID), 0)
        self.assertEqual(self._notificacoes_admin(), [])

    def test_texto_sem_sessao_e_descartado(self):
        # Mensagem de texto de chat sem sessão ativa e sem cadastro é descartada.
        self.bot.process_new_updates([_update_mensagem("João da Silva", NOVO_ID)])

        self.assertIsNone(self._usuario(NOVO_ID))
        self.assertEqual(self._textos_para(NOVO_ID), [])

    def test_usuario_comum_nao_confirma_formulario_de_outro(self):
        # A sessão é resolvida pelo autor do callback, nunca pelo conteúdo.
        self.bot.process_new_updates([_update_mensagem("/start", NOVO_ID)])
        self.bot.process_new_updates([_update_callback("formcad_confirmar", USER_ID)])

        # USER_ID (autorizado por config) não tem sessão: nada é criado para ele.
        self.assertIsNone(self._usuario(USER_ID))
        # E a sessão do NOVO_ID permanece intacta (não foi consumida).
        self.assertTrue(sessao_cadastro.tem_sessao_ativa(NOVO_ID))

    def test_suspenso_nao_inicia_formulario(self):
        self._seed(NOVO_ID, STATUS_SUSPENSO, chat_id=NOVO_ID)
        self.bot.process_new_updates([_update_mensagem("/start", NOVO_ID)])

        self.assertFalse(sessao_cadastro.tem_sessao_ativa(NOVO_ID))
        self.assertEqual(self._usuario(NOVO_ID).status, STATUS_SUSPENSO)


    def _seed_ativo(self, ticker, tipo):
        sessao = self.Session()
        try:
            enum_tipo = TipoAtivo.FII if tipo == "fii" else TipoAtivo.ACAO
            ativo = Ativo(ticker=ticker, cnpj=f"cnpj-{ticker}", tipo=enum_tipo)
            sessao.add(ativo)
            sessao.commit()
        finally:
            sessao.close()

    def _iniciar_formulario(self, user_id):
        self.bot.process_new_updates([_update_mensagem("/start", user_id)])
        self.bot.process_new_updates([_update_mensagem("João da Silva", user_id)])
        self.bot.process_new_updates(
            [_update_mensagem("joao.silva@exemplo.com", user_id)]
        )

    def test_favoritos_escolhidos_ficam_pendentes_ate_aprovacao(self):
        self._seed_ativo("MXRF11", "fii")
        self._seed_ativo("HGLG11", "fii")
        self._seed_ativo("PETR4", "acao")
        self._iniciar_formulario(NOVO_ID)

        self.bot.process_new_updates([_update_callback("formcad_fii", NOVO_ID)])
        self.bot.process_new_updates([_update_callback("formcad_ft_MXRF11", NOVO_ID)])
        self.bot.process_new_updates([_update_callback("formcad_ft_HGLG11", NOVO_ID)])
        self.bot.process_new_updates([_update_callback("formcad_fd", NOVO_ID)])
        self.bot.process_new_updates([_update_callback("formcad_acao", NOVO_ID)])
        self.bot.process_new_updates([_update_callback("formcad_at_PETR4", NOVO_ID)])
        self.bot.process_new_updates([_update_callback("formcad_ad", NOVO_ID)])
        self.bot.process_new_updates([_update_callback("formcad_confirmar", NOVO_ID)])

        dto = self._usuario(NOVO_ID)
        self.assertIsNotNone(dto)
        self.assertEqual(dto.status, STATUS_PENDENTE)
        pendentes = RepositorioUsuarios().obter_favoritos_pendentes(dto.id)
        self.assertEqual(pendentes["fii"], ["MXRF11", "HGLG11"])
        self.assertEqual(pendentes["acao"], ["PETR4"])
        # Nada e vinculado antes da aprovacao.
        self.assertEqual(RepositorioFavoritos().listar(dto.id), [])

    def test_aprovacao_aplica_favoritos_pendentes_e_limpa_selecao(self):
        self._seed_ativo("MXRF11", "fii")
        self._seed_ativo("PETR4", "acao")
        self._iniciar_formulario(NOVO_ID)
        self.bot.process_new_updates([_update_callback("formcad_fii", NOVO_ID)])
        self.bot.process_new_updates([_update_callback("formcad_ft_MXRF11", NOVO_ID)])
        self.bot.process_new_updates([_update_callback("formcad_fd", NOVO_ID)])
        self.bot.process_new_updates([_update_callback("formcad_acao", NOVO_ID)])
        self.bot.process_new_updates([_update_callback("formcad_at_PETR4", NOVO_ID)])
        self.bot.process_new_updates([_update_callback("formcad_ad", NOVO_ID)])
        self.bot.process_new_updates([_update_callback("formcad_confirmar", NOVO_ID)])

        dto = self._usuario(NOVO_ID)
        self.bot.process_new_updates(
            [_update_callback(f"cad_aprovar_{dto.id}", ADMIN_ID)]
        )

        dto = self._usuario(NOVO_ID)
        self.assertEqual(dto.status, STATUS_APROVADO)
        favoritos = RepositorioFavoritos().listar(dto.id)
        self.assertEqual(
            sorted((f.tipo, f.ticker) for f in favoritos),
            [("acao", "PETR4"), ("fii", "MXRF11")],
        )
        self.assertEqual(
            RepositorioUsuarios().obter_favoritos_pendentes(dto.id),
            {"fii": [], "acao": []},
        )

    def test_rejeicao_descarta_favoritos_pendentes_sem_vincular(self):
        self._seed_ativo("MXRF11", "fii")
        self._iniciar_formulario(NOVO_ID)
        self.bot.process_new_updates([_update_callback("formcad_fii", NOVO_ID)])
        self.bot.process_new_updates([_update_callback("formcad_ft_MXRF11", NOVO_ID)])
        self.bot.process_new_updates([_update_callback("formcad_fd", NOVO_ID)])
        self.bot.process_new_updates([_update_callback("formcad_confirmar", NOVO_ID)])

        dto = self._usuario(NOVO_ID)
        self.bot.process_new_updates(
            [_update_callback(f"cad_rejeitar_{dto.id}", ADMIN_ID)]
        )

        dto = self._usuario(NOVO_ID)
        self.assertEqual(dto.status, STATUS_REJEITADO)
        self.assertEqual(RepositorioFavoritos().listar(dto.id), [])
        self.assertEqual(
            RepositorioUsuarios().obter_favoritos_pendentes(dto.id),
            {"fii": [], "acao": []},
        )

    def test_limite_de_favoritos_e_respeitado_na_selecao(self):
        self._seed_ativo("MXRF11", "fii")
        self._seed_ativo("HGLG11", "fii")
        original = config.FAVORITOS_LIMITES
        config.FAVORITOS_LIMITES = {"fii": 1, "acao": None}
        try:
            self._iniciar_formulario(NOVO_ID)
            self.bot.process_new_updates([_update_callback("formcad_fii", NOVO_ID)])
            self.bot.process_new_updates(
                [_update_callback("formcad_ft_MXRF11", NOVO_ID)]
            )
            self.bot.process_new_updates(
                [_update_callback("formcad_ft_HGLG11", NOVO_ID)]
            )
            sessao = sessao_cadastro.obter(NOVO_ID)
            self.assertEqual(sessao.favoritos_fii, ["MXRF11"])
            self.assertTrue(
                any("Limite" in (t or "") for (_cid, t) in self.respostas)
            )
        finally:
            config.FAVORITOS_LIMITES = original

    def test_concluir_selecao_de_favoritos_nao_quebra_callback(self):
        self._seed_ativo("MXRF11", "fii")
        self._iniciar_formulario(NOVO_ID)
        self.bot.process_new_updates([_update_callback("formcad_fii", NOVO_ID)])
        self.bot.process_new_updates([_update_callback("formcad_fd", NOVO_ID)])
        self.assertTrue(sessao_cadastro.tem_sessao_ativa(NOVO_ID))
        self.assertEqual(sessao_cadastro.obter(NOVO_ID).etapa, "confirmacao")
        self.assertTrue(self.respostas, "o callback formcad_fd deve ser respondido")

    def test_ativo_fora_do_catalogo_nao_e_selecionado(self):
        self._seed_ativo("MXRF11", "fii")
        self._iniciar_formulario(NOVO_ID)
        self.bot.process_new_updates([_update_callback("formcad_fii", NOVO_ID)])
        self.bot.process_new_updates([_update_callback("formcad_ft_ZZZZ9", NOVO_ID)])
        sessao = sessao_cadastro.obter(NOVO_ID)
        self.assertEqual(sessao.favoritos_fii, [])


    def test_falha_de_banco_ao_aplicar_preserva_selecao_pendente(self):
        self._seed_ativo("MXRF11", "fii")
        dto, criado = RepositorioUsuarios().criar_solicitacao(
            NOVO_ID,
            NOVO_ID,
            nome="João da Silva",
            email="joao.silva@exemplo.com",
            favoritos_pendentes={"fii": ["MXRF11"], "acao": []},
        )
        self.assertTrue(criado)

        with mock.patch.object(
            RepositorioFavoritos, "listar", side_effect=RuntimeError("db fora")
        ):
            self.assertEqual(self.cadastro.aplicar_favoritos_pendentes(dto.id), 0)

        self.assertEqual(
            RepositorioUsuarios().obter_favoritos_pendentes(dto.id),
            {"fii": ["MXRF11"], "acao": []},
        )
        self.assertEqual(RepositorioFavoritos().listar(dto.id), [])

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

    def test_decisao_registra_status_anterior_na_auditoria(self):
        # Requisito: a decisão revalida o estado atual da solicitação. O estado
        # anterior deve constar da trilha de auditoria.
        dto = self._seed(NOVO_ID, STATUS_PENDENTE, chat_id=NOVO_ID)
        with self.assertLogs("robo.auditoria", level="INFO") as registro:
            self.bot.process_new_updates(
                [_update_callback(f"cad_aprovar_{dto.id}", ADMIN_ID)]
            )
        trilha = "\n".join(registro.output)
        self.assertIn("acao=aprovar", trilha)
        self.assertIn("resultado=aplicada", trilha)
        self.assertIn("status_anterior=pendente", trilha)

    def test_decisao_repetida_registra_estado_anterior_atualizado(self):
        dto = self._seed(NOVO_ID, STATUS_PENDENTE, chat_id=NOVO_ID)
        self.bot.process_new_updates(
            [_update_callback(f"cad_aprovar_{dto.id}", ADMIN_ID)]
        )
        with self.assertLogs("robo.auditoria", level="INFO") as registro:
            self.bot.process_new_updates(
                [_update_callback(f"cad_aprovar_{dto.id}", ADMIN_ID)]
            )
        trilha = "\n".join(registro.output)
        self.assertIn("resultado=ja_constava", trilha)
        self.assertIn("status_anterior=aprovado", trilha)

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


class TestValidacaoEFormulario(unittest.TestCase):
    """Testes unitários da validação de campos e do estado do formulário."""

    def test_normalizar_nome_valido(self):
        import bot.cadastro as cadastro

        self.assertEqual(cadastro.normalizar_nome("  João   da Silva "), "João da Silva")
        self.assertEqual(cadastro.normalizar_nome("Ana Paula"), "Ana Paula")

    def test_normalizar_nome_invalido(self):
        import bot.cadastro as cadastro

        self.assertIsNone(cadastro.normalizar_nome(""))
        self.assertIsNone(cadastro.normalizar_nome("João"))  # exige sobrenome
        self.assertIsNone(cadastro.normalizar_nome("Jo4o Silva"))
        self.assertIsNone(cadastro.normalizar_nome("A B"))

    def test_normalizar_email_valido(self):
        import bot.cadastro as cadastro

        self.assertEqual(
            cadastro.normalizar_email("  Joao.SILVA@Exemplo.COM "),
            "joao.silva@exemplo.com",
        )

    def test_normalizar_email_invalido(self):
        import bot.cadastro as cadastro

        self.assertIsNone(cadastro.normalizar_email("sem-arroba"))
        self.assertIsNone(cadastro.normalizar_email("a@b"))
        self.assertIsNone(cadastro.normalizar_email("a@b.c"))
        self.assertIsNone(cadastro.normalizar_email("@exemplo.com"))

    def test_sessao_cadastro_ciclo_de_vida(self):
        sessao_cadastro.limpar_tudo()
        self.assertFalse(sessao_cadastro.tem_sessao_ativa(1))
        sessao = sessao_cadastro.iniciar(1, 1)
        self.assertEqual(sessao.etapa, "nome")
        self.assertTrue(sessao_cadastro.tem_sessao_ativa(1))
        sessao_cadastro.atualizar(1, nome="Ana Paula", etapa="email")
        self.assertEqual(sessao_cadastro.obter(1).nome, "Ana Paula")
        self.assertTrue(sessao_cadastro.cancelar(1))
        self.assertFalse(sessao_cadastro.tem_sessao_ativa(1))
        self.assertFalse(sessao_cadastro.cancelar(1))

    def test_sessao_cadastro_expira(self):
        sessao_cadastro.limpar_tudo()
        sessao_cadastro.iniciar(7, 7)
        sessao = sessao_cadastro.obter(7)
        sessao.atualizado_em -= sessao_cadastro.TTL_SEGUNDOS + 1
        self.assertFalse(sessao_cadastro.tem_sessao_ativa(7))


if __name__ == "__main__":
    unittest.main()

