"""Testes da Central de Controles administrativa.

Cobrem o fluxo completo atraves do bot real (``bot.loader.BotAutorizado``) sem
nenhuma chamada de rede e sem tocar no Neon:

* o banco e um SQLite em memoria isolado, ligado ao repositorio por um
  ``sessionmaker`` injetado (``pipeline_dados.repositorio_usuarios``);
* ``telebot`` e instanciado com a validacao de token neutralizada;
* ``send_message``/``answer_callback_query``/``edit_message_text``/``get_chat``
  sao substituidos por fakes que apenas registram as chamadas.

Os testes navegam pelos botoes exibidos (como o administrador faria) e tambem
forjam ``callback_data`` para provar que a autorizacao e o estado do usuario sao
revalidados no servidor, e nao deduzidos da existencia do botao.
"""

import json
import os
import sys
import unittest
from datetime import datetime
from types import SimpleNamespace

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
from bot.telegram_utils import (  # noqa: E402
    TEXTO_ACESSO_NEGADO,
    construir_menu_inicial,
)
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
USER_ID = 5336458734  # usuario comum definido em config
ALVO_ID = 111111111
OUTRO_ID = 222222222
ADMIN_DB_ID = 333333333  # administrador reconhecido apenas pelo banco
DESCONHECIDO_ID = 999999999
TOKEN_FALSO = "123456:FAKE-TOKEN-CENTRAL-TESTE"

LIMITE_CALLBACK_DATA = 64  # bytes (limite do Telegram)
LIMITE_TEXTO = 4096  # caracteres (limite do Telegram)


def _autor(user_id):
    return {"id": user_id, "is_bot": False, "first_name": "Teste"}


def _update_mensagem(texto, user_id):
    payload = {
        "update_id": 1,
        "message": {
            "message_id": 3,
            "date": 0,
            "chat": {"id": user_id, "type": "private"},
            "from": _autor(user_id),
            "text": texto,
        },
    }
    return types.Update.de_json(json.dumps(payload))


def _update_callback(data, user_id):
    payload = {
        "update_id": 2,
        "callback_query": {
            "id": "cb1",
            "from": _autor(user_id),
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


class _BaseCentral(unittest.TestCase):
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

        for nome in ("bot.central_controles", "bot.cadastro", "bot.loader"):
            sys.modules.pop(nome, None)
        import bot.loader as loader

        # Mesma ordem do main.py: cadastro e central ANTES do handler generico.
        import bot.cadastro as cadastro
        import bot.central_controles as central

        cls.loader = loader
        cls.cadastro = cadastro
        cls.central = central
        cls.bot = loader.bot
        cls.genericos = []

        # Imita o handler generico de bot.callbacks_menus (func=lambda: True).
        @cls.bot.callback_query_handler(func=lambda call: True)
        def _generico(call):
            cls.genericos.append(call.data)

    @classmethod
    def tearDownClass(cls):
        repo_mod.obter_session_factory = cls._factory_original
        for chave, valor in cls._backup.items():
            setattr(config, chave, valor)
        for nome in ("bot.central_controles", "bot.cadastro", "bot.loader"):
            sys.modules.pop(nome, None)

    # -- Infraestrutura ----------------------------------------------------

    def setUp(self):
        type(self).genericos.clear()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        BaseUsuarios.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        repo_mod.obter_session_factory = lambda: self.Session

        self.enviados = []  # (chat_id, texto, kwargs)
        self.respostas = []  # (callback_id, texto, kwargs)
        self.editados = []  # (chat_id, msg_id, texto, kwargs)
        self.telas = []  # (texto, markup) das telas da Central
        self.usernames = {}  # chat_id -> username (get_chat)

        def _registrar_tela(texto, kwargs):
            markup = kwargs.get("reply_markup")
            if markup is not None and (
                "CENTRAL DE CONTROLES" in texto
                or "CONFIRMAÇÃO" in texto
                or "NOTIFICACOES" in texto
            ):
                self.telas.append((texto, markup))

        def _send(chat_id, text, **k):
            self.enviados.append((chat_id, text, k))
            _registrar_tela(text, k)

        def _edit(text, chat_id, msg_id, **k):
            self.editados.append((chat_id, msg_id, text, k))
            _registrar_tela(text, k)

        def _get_chat(chat_id):
            if int(chat_id) not in self.usernames:
                raise RuntimeError("chat not found")
            return SimpleNamespace(username=self.usernames[int(chat_id)])

        self.bot.send_message = _send
        self.bot.edit_message_text = _edit
        self.bot.answer_callback_query = (
            lambda cid, text=None, **k: self.respostas.append((cid, text, k))
        )
        self.bot.get_chat = _get_chat

    def tearDown(self):
        self.engine.dispose()
        repo_mod.obter_session_factory = lambda: self.Session

    # -- Utilitarios -------------------------------------------------------

    def _seed(
        self,
        telegram_user_id,
        status,
        nome="Fulano de Tal",
        email="fulano@exemplo.com",
        papel="user",
        chat_id=None,
        criado_em=None,
    ):
        sessao = self.Session()
        try:
            usuario = Usuario(
                nome=nome,
                email=email,
                papel=papel,
                ativo=(status == STATUS_APROVADO),
                telegram_user_id=int(telegram_user_id),
                telegram_chat_id=chat_id if chat_id is not None else int(telegram_user_id),
                criado_em=criado_em or datetime(2026, 3, 5, 14, 30),
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

    def _total_linhas(self):
        sessao = self.Session()
        try:
            return sessao.query(Usuario).count()
        finally:
            sessao.close()

    def _msg(self, texto, user_id=ADMIN_ID):
        self.bot.process_new_updates([_update_mensagem(texto, user_id)])

    def _cb(self, data, user_id=ADMIN_ID):
        self.bot.process_new_updates([_update_callback(data, user_id)])

    @staticmethod
    def _botoes(markup):
        return [(b.text, b.callback_data) for linha in markup.keyboard for b in linha]

    def _tela(self):
        self.assertTrue(self.telas, "nenhuma tela da Central foi exibida")
        return self.telas[-1]

    def _dado_do_botao(self, parte_do_texto):
        _texto, markup = self._tela()
        for rotulo, dado in self._botoes(markup):
            if parte_do_texto in rotulo:
                return dado
        self.fail(
            f"botao com {parte_do_texto!r} nao encontrado em "
            f"{[r for r, _ in self._botoes(markup)]}"
        )

    def _clicar(self, parte_do_texto, user_id=ADMIN_ID):
        dado = self._dado_do_botao(parte_do_texto)
        self._cb(dado, user_id)
        return dado

    def _tem_botao(self, parte_do_texto):
        _texto, markup = self._tela()
        return any(parte_do_texto in r for r, _ in self._botoes(markup))

    def _abrir_area(self, rotulo):
        self._msg("/controles")
        self._clicar("Usuarios")
        self._clicar(rotulo)

    def _abrir_usuario(self, rotulo_area, parte_do_nome):
        self._abrir_area(rotulo_area)
        self._clicar(parte_do_nome)

    def _textos_para(self, destino):
        return [t for (cid, t, _k) in self.enviados if str(cid) == str(destino)]

    def _toasts(self):
        return [t for (_cid, t, _k) in self.respostas]

    def _telas_da_central(self):
        return len(self.telas)

    def _assert_negado(self):
        self.assertTrue(
            any(t == TEXTO_ACESSO_NEGADO for t in self._toasts())
            or any(t == TEXTO_ACESSO_NEGADO for (_c, t, _k) in self.enviados),
            "esperava uma resposta de acesso negado",
        )


class TestAutorizacaoEVisibilidade(_BaseCentral):
    """Somente o administrador autorizado ve e executa a Central."""

    def test_admin_abre_hub_com_tres_botoes(self):
        self._msg("/controles")
        texto, markup = self._tela()
        self.assertIn("CENTRAL DE CONTROLES", texto)
        rotulos = [r for r, _ in self._botoes(markup)]
        self.assertIn("👥 Usuarios", rotulos)
        self.assertIn("🔔 Notificacoes", rotulos)
        self.assertIn("⚖️ Central de Revisoes", rotulos)
        callbacks = [d for _r, d in self._botoes(markup)]
        self.assertIn("adm_usuarios", callbacks)
        self.assertIn("adm_notificacoes", callbacks)
        self.assertIn("adm_revisoes", callbacks)

    def test_admin_abre_notificacoes_com_recorte_por_pessoa_e_ativos(self):
        self._msg("/controles")
        self._clicar("Notificacoes")
        texto, markup = self._tela()
        self.assertIn("NOTIFICACOES", texto)
        self.assertIn("Por pessoa", texto)
        rotulos = [r for r, _ in self._botoes(markup)]
        self.assertIn("👤 Por pessoa", rotulos)
        self.assertIn("🏢 Por FIIs/acoes favoritados", rotulos)

    def test_admin_abre_usuarios_com_as_quatro_areas_e_contagens(self):
        self._seed(1001, STATUS_PENDENTE, nome="Pendente Um")
        self._seed(1002, STATUS_PENDENTE, nome="Pendente Dois")
        self._seed(1003, STATUS_APROVADO, nome="Aprovado Um")
        for i in range(3):
            self._seed(1010 + i, STATUS_REJEITADO, nome=f"Rejeitado {i}")
        self._seed(1020, STATUS_SUSPENSO, nome="Suspenso Um")

        self._msg("/controles")
        self._clicar("Usuarios")

        texto, markup = self._tela()
        self.assertIn("CENTRAL DE CONTROLES", texto)
        self.assertIn("Solicitações pendentes: 2", texto)
        self.assertIn("Usuários aprovados: 1", texto)
        self.assertIn("Usuários rejeitados: 3", texto)
        self.assertIn("Usuários suspensos: 1", texto)
        rotulos = [r for r, _ in self._botoes(markup)]
        for esperado in (
            "Solicitações pendentes (2)",
            "Usuários aprovados (1)",
            "Usuários rejeitados (3)",
            "Usuários suspensos (1)",
        ):
            self.assertTrue(any(esperado in r for r in rotulos), esperado)

    def test_botao_da_central_aparece_no_menu_apenas_para_o_admin(self):
        def tem_adm(markup):
            return any(d == "adm_home" for _t, d in self._botoes(markup))

        self.assertTrue(tem_adm(construir_menu_inicial(incluir_admin=True)))
        self.assertFalse(tem_adm(construir_menu_inicial(incluir_admin=False)))
        self.assertFalse(tem_adm(construir_menu_inicial()))

        # Pelo fluxo real do /start (usa permissoes para decidir o botao).
        self.enviados.clear()
        self._msg("/start", ADMIN_ID)
        menu_admin = [k["reply_markup"] for (c, _t, k) in self.enviados if c == ADMIN_ID]
        self.assertTrue(menu_admin and tem_adm(menu_admin[-1]))

        self.enviados.clear()
        self._msg("/start", USER_ID)
        menu_user = [k["reply_markup"] for (c, _t, k) in self.enviados if c == USER_ID]
        self.assertTrue(menu_user and not tem_adm(menu_user[-1]))

    def test_usuarios_nao_administradores_nao_abrem_a_central(self):
        self._seed(ALVO_ID, STATUS_PENDENTE, nome="Pendente")
        self._seed(OUTRO_ID, STATUS_APROVADO, nome="Aprovado Comum", papel="user")
        self._seed(444444444, STATUS_REJEITADO, nome="Rejeitado")
        self._seed(555555555, STATUS_SUSPENSO, nome="Suspenso")

        for autor in (USER_ID, ALVO_ID, OUTRO_ID, 444444444, 555555555):
            with self.subTest(autor=autor):
                self.enviados.clear()
                self.telas.clear()
                self._msg("/controles", autor)
                self.assertEqual(self.telas, [], "a Central nao pode ser exibida")
                self.assertTrue(
                    any(t == TEXTO_ACESSO_NEGADO for (_c, t, _k) in self.enviados)
                )

    def test_usuario_desconhecido_e_descartado_antes_do_handler(self):
        self._msg("/controles", DESCONHECIDO_ID)
        self._cb("adm_home", DESCONHECIDO_ID)
        self.assertEqual(self.telas, [])
        self.assertEqual(self.genericos, [])

    def test_nenhum_callback_administrativo_executa_para_nao_admin(self):
        alvo = self._seed(ALVO_ID, STATUS_PENDENTE, nome="Pendente")
        aprovado = self._seed(OUTRO_ID, STATUS_APROVADO, nome="Aprovado")
        callbacks = [
            "adm_home",
            "adm_area_pend_0",
            f"adm_ver_{alvo.id}_pend_0",
            f"adm_conf_rejeitar_{alvo.id}_pend_0",
            f"adm_do_aprovar_{alvo.id}_pend_0",
            f"adm_do_rejeitar_{alvo.id}_pend_0",
            f"adm_conf_suspender_{aprovado.id}_aprov_0",
            f"adm_do_suspender_{aprovado.id}_aprov_0",
        ]
        for autor in (USER_ID, OUTRO_ID, ALVO_ID):
            for data in callbacks:
                with self.subTest(autor=autor, data=data):
                    self.respostas.clear()
                    self._cb(data, autor)
                    self.assertEqual(self.telas, [])
                    self.assertEqual(self.editados, [])
                    self.assertIn(TEXTO_ACESSO_NEGADO, self._toasts())

        self.assertEqual(self._usuario(ALVO_ID).status, STATUS_PENDENTE)
        self.assertEqual(self._usuario(OUTRO_ID).status, STATUS_APROVADO)
        self.assertEqual(self.enviados, [], "nenhuma notificacao pode ser enviada")

    def test_handlers_revalidam_autorizacao_mesmo_sem_o_despachante(self):
        """Defesa em profundidade: chamando o handler direto (sem loader)."""
        alvo = self._seed(ALVO_ID, STATUS_PENDENTE)
        update = _update_callback(f"adm_do_aprovar_{alvo.id}_pend_0", USER_ID)
        with self.assertLogs("robo.auditoria", level="INFO") as registro:
            self.central.tratar_callback(update.callback_query)
        self.assertIn("acao=central_negada", "\n".join(registro.output))
        self.assertIn(TEXTO_ACESSO_NEGADO, self._toasts())
        self.assertEqual(self._usuario(ALVO_ID).status, STATUS_PENDENTE)

        self.enviados.clear()
        mensagem = _update_mensagem("/controles", USER_ID).message
        self.central.abrir_central(mensagem)
        self.assertEqual(self.telas, [])
        self.assertTrue(
            any(t == TEXTO_ACESSO_NEGADO for (_c, t, _k) in self.enviados)
        )

    def test_perda_de_privilegio_do_admin_bloqueia_callbacks_seguintes(self):
        self._seed(ALVO_ID, STATUS_PENDENTE, nome="Pendente")
        self._msg("/controles")
        self._clicar("Usuarios")
        self._clicar("Solicitações pendentes")
        self._clicar("Pendente")

        original = config.USUARIOS_AUTORIZADOS
        config.USUARIOS_AUTORIZADOS = {str(USER_ID): config.PAPEL_USUARIO}
        try:
            self._cb(self._dado_do_botao("Aprovar solicitação"))
        finally:
            config.USUARIOS_AUTORIZADOS = original

        self.assertEqual(self._usuario(ALVO_ID).status, STATUS_PENDENTE)
        self._assert_negado()

    def test_classificacao_administrativa_em_permissoes(self):
        self.assertEqual(
            permissoes.operacao_de_comando("/controles")[1], permissoes.NIVEL_ADMIN
        )
        for dado in ("adm_home", "adm_do_aprovar_1_pend_0", "adm_qualquer_coisa"):
            self.assertEqual(
                permissoes.operacao_de_callback(dado)[1], permissoes.NIVEL_ADMIN
            )
        self.assertNotIn("controles", permissoes.COMANDOS_USUARIO)

    def test_admin_reconhecido_apenas_pelo_banco_tambem_acessa(self):
        self._seed(ADMIN_DB_ID, STATUS_APROVADO, nome="Admin Banco", papel="admin")
        self._msg("/controles", ADMIN_DB_ID)
        self.assertEqual(len(self.telas), 1)


class TestRegistroNoBoot(_BaseCentral):
    def test_central_e_registrada_antes_do_handler_generico(self):
        self._msg("/controles")
        self._cb("adm_home")
        self.assertEqual(self.genericos, [], "o handler generico nao pode engolir adm_*")
        self.assertEqual(len(self.telas), 2)

    def test_main_importa_a_central_antes_de_callbacks_menus(self):
        caminho = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py"
        )
        with open(caminho, encoding="utf-8") as arquivo:
            codigo = arquivo.read()
        linhas = [l.strip() for l in codigo.splitlines()]
        self.assertIn("import bot.central_controles", linhas)
        self.assertLess(
            linhas.index("import bot.central_controles"),
            linhas.index("import bot.callbacks_menus"),
        )


class TestListagemEDetalhes(_BaseCentral):
    def test_cada_area_lista_somente_os_usuarios_do_seu_status(self):
        self._seed(1001, STATUS_PENDENTE, nome="Pessoa Pendente")
        self._seed(1002, STATUS_APROVADO, nome="Pessoa Aprovada")
        self._seed(1003, STATUS_REJEITADO, nome="Pessoa Rejeitada")
        self._seed(1004, STATUS_SUSPENSO, nome="Pessoa Suspensa")
        esperado = {
            "Solicitações pendentes": "Pessoa Pendente",
            "Usuários aprovados": "Pessoa Aprovada",
            "Usuários rejeitados": "Pessoa Rejeitada",
            "Usuários suspensos": "Pessoa Suspensa",
        }
        for area, nome in esperado.items():
            with self.subTest(area=area):
                self._abrir_area(area)
                _texto, markup = self._tela()
                rotulos = " | ".join(r for r, _ in self._botoes(markup))
                self.assertIn(nome, rotulos)
                for outro in esperado.values():
                    if outro != nome:
                        self.assertNotIn(outro, rotulos)

    def test_area_vazia_informa_e_oferece_retorno(self):
        self._abrir_area("Usuários suspensos")
        texto, markup = self._tela()
        self.assertIn("Nenhum usuário nesta área", texto)
        self.assertTrue(any("Voltar" in r for r, _ in self._botoes(markup)))

    def test_detalhes_mostram_os_dados_de_identificacao(self):
        dto = self._seed(
            ALVO_ID,
            STATUS_PENDENTE,
            nome="Maria Oliveira Santos",
            email="maria@exemplo.com",
            criado_em=datetime(2026, 3, 5, 14, 30),
        )
        self.usernames[ALVO_ID] = "maria_os"
        self._abrir_usuario("Solicitações pendentes", "Maria Oliveira")

        texto, _markup = self._tela()
        self.assertIn("Nome completo: Maria Oliveira Santos", texto)
        self.assertIn("E-mail: maria@exemplo.com", texto)
        self.assertIn(f"Telegram User ID: {ALVO_ID}", texto)
        self.assertIn("Username: @maria_os", texto)
        self.assertIn("Data de cadastro: 05/03/2026 14:30", texto)
        self.assertIn("Situação atual: Pendente de aprovação", texto)
        self.assertIn(f"#{dto.id}", texto)

    def test_username_indisponivel_nao_quebra_a_tela(self):
        self._seed(ALVO_ID, STATUS_PENDENTE, nome="Sem Username")
        self._abrir_usuario("Solicitações pendentes", "Sem Username")
        texto, _markup = self._tela()
        self.assertIn("Username: não disponível", texto)

    def test_campos_ausentes_tem_texto_padrao(self):
        self._seed(ALVO_ID, STATUS_PENDENTE, nome=None, email=None)
        sessao = self.Session()
        try:
            usuario = sessao.query(Usuario).first()
            usuario.criado_em = None
            sessao.commit()
        finally:
            sessao.close()
        self._abrir_usuario("Solicitações pendentes", "Sem nome")
        texto, _markup = self._tela()
        self.assertIn("Nome completo: Não informado", texto)
        self.assertIn("E-mail: Não informado", texto)
        self.assertIn("Data de cadastro: Não informada", texto)

    def test_nome_com_caracteres_especiais_e_exibido_como_texto_simples(self):
        self._seed(ALVO_ID, STATUS_PENDENTE, nome="Ana_*[x](y) <b>Souza")
        self._abrir_usuario("Solicitações pendentes", "Ana_")
        for (_c, _m, _t, k) in self.editados:
            self.assertNotIn("parse_mode", k)

    def test_consulta_nao_altera_estado_nem_notifica(self):
        self._seed(ALVO_ID, STATUS_PENDENTE, nome="Somente Consulta")
        self._abrir_usuario("Solicitações pendentes", "Somente Consulta")
        self._clicar("Atualizar dados")
        self.assertEqual(self._usuario(ALVO_ID).status, STATUS_PENDENTE)
        self.assertEqual(self._textos_para(ALVO_ID), [])


class TestPaginacao(_BaseCentral):
    def _seed_pendentes(self, quantidade):
        for i in range(quantidade):
            self._seed(5000 + i, STATUS_PENDENTE, nome=f"Pessoa {i + 1:02d}")

    def _nomes_na_tela(self):
        _t, markup = self._tela()
        return [r for r, d in self._botoes(markup) if d.startswith("adm_ver_")]

    def test_paginas_de_oito_com_navegacao_nos_dois_sentidos(self):
        self._seed_pendentes(20)
        self._abrir_area("Solicitações pendentes")

        texto, _m = self._tela()
        self.assertIn("Página 1/3 — 20 registro(s)", texto)
        self.assertEqual(len(self._nomes_na_tela()), 8)
        self.assertTrue(self._tem_botao("Próxima"))
        self.assertFalse(self._tem_botao("Anterior"))
        self.assertIn("Pessoa 01", self._nomes_na_tela()[0])

        self._clicar("Próxima")
        texto, _m = self._tela()
        self.assertIn("Página 2/3", texto)
        self.assertEqual(len(self._nomes_na_tela()), 8)
        self.assertIn("Pessoa 09", self._nomes_na_tela()[0])
        self.assertTrue(self._tem_botao("Próxima") and self._tem_botao("Anterior"))

        self._clicar("Próxima")
        texto, _m = self._tela()
        self.assertIn("Página 3/3", texto)
        self.assertEqual(len(self._nomes_na_tela()), 4)
        self.assertIn("Pessoa 17", self._nomes_na_tela()[0])
        self.assertFalse(self._tem_botao("Próxima"))
        self.assertTrue(self._tem_botao("Anterior"))

        self._clicar("Anterior")
        texto, _m = self._tela()
        self.assertIn("Página 2/3", texto)

    def test_nenhuma_pessoa_se_repete_entre_paginas(self):
        self._seed_pendentes(20)
        self._abrir_area("Solicitações pendentes")
        vistos = list(self._nomes_na_tela())
        self._clicar("Próxima")
        vistos += self._nomes_na_tela()
        self._clicar("Próxima")
        vistos += self._nomes_na_tela()
        self.assertEqual(len(vistos), 20)
        self.assertEqual(len(set(vistos)), 20)

    def test_mensagens_e_callbacks_respeitam_os_limites_do_telegram(self):
        self._seed_pendentes(20)
        self._seed(7000, STATUS_APROVADO, nome="N" * 120)
        self._abrir_area("Solicitações pendentes")
        self._clicar("Próxima")
        self._clicar("Pessoa 09")
        self._clicar("Rejeitar")
        self._msg("/controles")
        self._clicar("Usuarios")
        self._clicar("Usuários aprovados")
        self._clicar("NNN")
        self._clicar("Suspender")

        self.assertGreater(len(self.telas), 5)
        for texto, markup in self.telas:
            self.assertLessEqual(len(texto), LIMITE_TEXTO)
            for _rotulo, dado in self._botoes(markup):
                self.assertLessEqual(len(dado.encode("utf-8")), LIMITE_CALLBACK_DATA, dado)

    def test_pagina_fora_do_intervalo_e_ajustada(self):
        self._seed_pendentes(9)
        self._cb("adm_area_pend_999")
        texto, _m = self._tela()
        self.assertIn("Página 2/2", texto)
        self.assertEqual(len(self._nomes_na_tela()), 1)

    def test_apos_decisao_a_pagina_e_reajustada(self):
        self._seed_pendentes(9)  # 2 paginas: 8 + 1
        self._abrir_area("Solicitações pendentes")
        self._clicar("Próxima")
        self._clicar("Pessoa 09")
        self._clicar("Aprovar solicitação")
        texto, _m = self._tela()
        self.assertIn("Página 1/1 — 8 registro(s)", texto)
        self.assertEqual(len(self._nomes_na_tela()), 8)


class TestAprovacao(_BaseCentral):
    def test_aprovar_pendente_atualiza_notifica_e_audita(self):
        dto = self._seed(ALVO_ID, STATUS_PENDENTE, nome="Joana Pendente")
        self._abrir_usuario("Solicitações pendentes", "Joana")

        with self.assertLogs("robo.auditoria", level="INFO") as registro:
            self._clicar("Aprovar solicitação")

        atual = self._usuario(ALVO_ID)
        self.assertEqual(atual.status, STATUS_APROVADO)
        self.assertTrue(atual.ativo)
        self.assertEqual(permissoes.obter_papel(ALVO_ID), "user")

        # Interface atualizada: volta a lista, com aviso e sem a pessoa.
        texto, markup = self._tela()
        self.assertIn("Joana Pendente — acesso aprovado", texto)
        self.assertNotIn("Joana", " ".join(r for r, _ in self._botoes(markup)))

        # Usuario afetado notificado com a mensagem do fluxo de cadastro.
        self.assertEqual(
            self._textos_para(ALVO_ID), [self.cadastro.TEXTO_APROVADO]
        )
        # Auditoria no mecanismo existente.
        trilha = "\n".join(registro.output)
        self.assertIn("AUDITORIA_CADASTRO", trilha)
        self.assertIn(f"autor={ADMIN_ID}", trilha)
        self.assertIn(f"solicitacao={dto.id}", trilha)
        self.assertIn("acao=central_aprovar", trilha)
        self.assertIn("resultado=aplicada", trilha)
        self.assertIn("status_anterior=pendente", trilha)

    def test_aprovar_pendente_nao_exige_confirmacao(self):
        self._seed(ALVO_ID, STATUS_PENDENTE, nome="Joana Pendente")
        self._abrir_usuario("Solicitações pendentes", "Joana")
        self.assertTrue(self._dado_do_botao("Aprovar solicitação").startswith("adm_do_"))

    def test_reconsiderar_rejeicao_exige_confirmacao(self):
        self._seed(ALVO_ID, STATUS_REJEITADO, nome="Rita Rejeitada")
        self._abrir_usuario("Usuários rejeitados", "Rita")
        self.assertTrue(self._dado_do_botao("reconsiderar").startswith("adm_conf_"))

        self._clicar("reconsiderar")
        self.assertIn("CONFIRMAÇÃO", self._tela()[0])
        self.assertEqual(self._usuario(ALVO_ID).status, STATUS_REJEITADO)

        self._clicar("Sim, aprovar")
        self.assertEqual(self._usuario(ALVO_ID).status, STATUS_APROVADO)
        self.assertEqual(self._textos_para(ALVO_ID), [self.cadastro.TEXTO_APROVADO])


class TestRejeicao(_BaseCentral):
    def test_rejeicao_exige_confirmacao_e_so_aplica_ao_confirmar(self):
        dto = self._seed(ALVO_ID, STATUS_PENDENTE, nome="Pedro Pendente")
        self._abrir_usuario("Solicitações pendentes", "Pedro")

        self.assertTrue(self._dado_do_botao("Rejeitar").startswith("adm_conf_"))
        self._clicar("Rejeitar")

        texto, _m = self._tela()
        self.assertIn("CONFIRMAÇÃO", texto)
        self.assertIn("Pedro Pendente", texto)
        self.assertEqual(self._usuario(ALVO_ID).status, STATUS_PENDENTE)
        self.assertEqual(self._textos_para(ALVO_ID), [])

        with self.assertLogs("robo.auditoria", level="INFO") as registro:
            self._clicar("Sim, rejeitar")

        atual = self._usuario(ALVO_ID)
        self.assertEqual(atual.status, STATUS_REJEITADO)
        self.assertFalse(atual.ativo)
        self.assertEqual(self._textos_para(ALVO_ID), [self.cadastro.TEXTO_REJEITADO])
        trilha = "\n".join(registro.output)
        self.assertIn("acao=central_rejeitar", trilha)
        self.assertIn(f"solicitacao={dto.id}", trilha)
        self.assertIn("status_anterior=pendente", trilha)
        self.assertIn("Pedro Pendente — solicitação rejeitada", self._tela()[0])

    def test_cancelar_a_confirmacao_nao_altera_nada(self):
        self._seed(ALVO_ID, STATUS_PENDENTE, nome="Pedro Pendente")
        self._abrir_usuario("Solicitações pendentes", "Pedro")
        self._clicar("Rejeitar")
        self._clicar("Cancelar")

        self.assertIn("DADOS CADASTRAIS", self._tela()[0])
        self.assertEqual(self._usuario(ALVO_ID).status, STATUS_PENDENTE)
        self.assertEqual(self._textos_para(ALVO_ID), [])

    def test_rejeitar_nao_e_oferecido_fora_de_pendente(self):
        self._seed(1001, STATUS_APROVADO, nome="Ana Aprovada")
        self._seed(1002, STATUS_SUSPENSO, nome="Sara Suspensa")
        self._abrir_usuario("Usuários aprovados", "Ana")
        self.assertFalse(self._tem_botao("Rejeitar"))
        self._abrir_usuario("Usuários suspensos", "Sara")
        self.assertFalse(self._tem_botao("Rejeitar"))


class TestSuspensaoEReativacao(_BaseCentral):
    def test_suspensao_com_confirmacao_revoga_o_acesso(self):
        dto = self._seed(ALVO_ID, STATUS_APROVADO, nome="Ana Aprovada")
        self.assertEqual(permissoes.obter_papel(ALVO_ID), "user")
        self._abrir_usuario("Usuários aprovados", "Ana")

        self.assertTrue(self._dado_do_botao("Suspender").startswith("adm_conf_"))
        self._clicar("Suspender")
        self.assertIn("CONFIRMAÇÃO", self._tela()[0])
        self.assertEqual(self._usuario(ALVO_ID).status, STATUS_APROVADO)

        with self.assertLogs("robo.auditoria", level="INFO") as registro:
            self._clicar("Sim, suspender")

        atual = self._usuario(ALVO_ID)
        self.assertEqual(atual.status, STATUS_SUSPENSO)
        self.assertFalse(atual.ativo)
        # O acesso e revogado de fato (autorizacao do bot).
        self.assertIsNone(permissoes.obter_papel(ALVO_ID))
        ok, _op = permissoes.verificar_update(_update_mensagem("/relatorios", ALVO_ID))
        self.assertFalse(ok)
        self.assertEqual(self._textos_para(ALVO_ID), [self.cadastro.TEXTO_SUSPENSO])
        trilha = "\n".join(registro.output)
        self.assertIn("acao=central_suspender", trilha)
        self.assertIn(f"solicitacao={dto.id}", trilha)
        self.assertIn("status_anterior=aprovado", trilha)

    def test_suspensao_cancelada_nao_altera_nada(self):
        self._seed(ALVO_ID, STATUS_APROVADO, nome="Ana Aprovada")
        self._abrir_usuario("Usuários aprovados", "Ana")
        self._clicar("Suspender")
        self._clicar("Cancelar")
        self.assertEqual(self._usuario(ALVO_ID).status, STATUS_APROVADO)
        self.assertEqual(self._textos_para(ALVO_ID), [])

    def test_reativacao_com_confirmacao_restaura_o_acesso(self):
        dto = self._seed(ALVO_ID, STATUS_SUSPENSO, nome="Sara Suspensa")
        self.assertIsNone(permissoes.obter_papel(ALVO_ID))
        self._abrir_usuario("Usuários suspensos", "Sara")

        self.assertTrue(self._dado_do_botao("Reativar").startswith("adm_conf_"))
        self._clicar("Reativar")
        self.assertIn("CONFIRMAÇÃO", self._tela()[0])
        self.assertEqual(self._usuario(ALVO_ID).status, STATUS_SUSPENSO)
        self.assertEqual(self._textos_para(ALVO_ID), [])

        with self.assertLogs("robo.auditoria", level="INFO") as registro:
            self._clicar("Sim, reativar")

        atual = self._usuario(ALVO_ID)
        self.assertEqual(atual.status, STATUS_APROVADO)
        self.assertTrue(atual.ativo)
        self.assertEqual(permissoes.obter_papel(ALVO_ID), "user")
        self.assertEqual(self._textos_para(ALVO_ID), [self.cadastro.TEXTO_REATIVADO])
        trilha = "\n".join(registro.output)
        self.assertIn("acao=central_reativar", trilha)
        self.assertIn(f"solicitacao={dto.id}", trilha)
        self.assertIn("status_anterior=suspenso", trilha)

    def test_reativar_nao_e_oferecido_fora_de_suspenso(self):
        self._seed(1001, STATUS_PENDENTE, nome="Pedro Pendente")
        self._seed(1002, STATUS_APROVADO, nome="Ana Aprovada")
        self._seed(1003, STATUS_REJEITADO, nome="Rita Rejeitada")
        for area, nome in (
            ("Solicitações pendentes", "Pedro"),
            ("Usuários aprovados", "Ana"),
            ("Usuários rejeitados", "Rita"),
        ):
            self._abrir_usuario(area, nome)
            self.assertFalse(self._tem_botao("Reativar"), area)

    def test_ciclo_completo_preserva_o_registro(self):
        dto = self._seed(ALVO_ID, STATUS_PENDENTE, nome="Ciclo Completo")
        antes = self._total_linhas()
        self._abrir_usuario("Solicitações pendentes", "Ciclo")
        self._clicar("Aprovar solicitação")
        self._clicar("Voltar")
        self._clicar("Usuários aprovados")
        self._clicar("Ciclo")
        self._clicar("Suspender")
        self._clicar("Sim, suspender")
        self._clicar("Voltar")
        self._clicar("Usuários suspensos")
        self._clicar("Ciclo")
        self._clicar("Reativar")
        self._clicar("Sim, reativar")

        final = self._usuario(ALVO_ID)
        self.assertEqual(final.id, dto.id)
        self.assertEqual(final.status, STATUS_APROVADO)
        self.assertEqual(final.nome, "Ciclo Completo")
        self.assertEqual(final.email, "fulano@exemplo.com")
        self.assertEqual(self._total_linhas(), antes)
        self.assertEqual(
            self._textos_para(ALVO_ID),
            [
                self.cadastro.TEXTO_APROVADO,
                self.cadastro.TEXTO_SUSPENSO,
                self.cadastro.TEXTO_REATIVADO,
            ],
        )


class TestRevalidacaoDeEstado(_BaseCentral):
    def test_confirmacao_nunca_altera_o_estado(self):
        casos = [
            (STATUS_PENDENTE, "rejeitar", "pend", 7001),
            (STATUS_APROVADO, "suspender", "aprov", 7002),
            (STATUS_SUSPENSO, "reativar", "susp", 7003),
            (STATUS_REJEITADO, "aprovar", "rej", 7004),
        ]
        for status, acao, area, tg_id in casos:
            with self.subTest(acao=acao):
                dto = self._seed(tg_id, status, nome=f"Alvo {acao}")
                self._cb(f"adm_conf_{acao}_{dto.id}_{area}_0")
                self.assertIn("CONFIRMAÇÃO", self._tela()[0])
                self.assertEqual(
                    RepositorioUsuarios().obter_por_id(dto.id).status, status
                )
        self.assertEqual(self.enviados, [])

    def test_botao_antigo_nao_executa_acao_incompativel_com_o_estado(self):
        pendente = self._seed(1001, STATUS_PENDENTE, nome="P")
        aprovado = self._seed(1002, STATUS_APROVADO, nome="A")
        suspenso = self._seed(1003, STATUS_SUSPENSO, nome="S")
        rejeitado = self._seed(1004, STATUS_REJEITADO, nome="R")
        incompativeis = [
            ("suspender", pendente, STATUS_PENDENTE),
            ("reativar", pendente, STATUS_PENDENTE),
            ("rejeitar", aprovado, STATUS_APROVADO),
            ("reativar", aprovado, STATUS_APROVADO),
            ("aprovar", suspenso, STATUS_SUSPENSO),
            ("rejeitar", suspenso, STATUS_SUSPENSO),
            ("suspender", rejeitado, STATUS_REJEITADO),
            ("reativar", rejeitado, STATUS_REJEITADO),
            ("rejeitar", rejeitado, STATUS_REJEITADO),
        ]
        alvo_da_acao = {
            "aprovar": STATUS_APROVADO,
            "rejeitar": STATUS_REJEITADO,
            "suspender": STATUS_SUSPENSO,
            "reativar": STATUS_APROVADO,
        }
        for acao, dto, esperado in incompativeis:
            for verbo in ("conf", "do"):
                with self.subTest(acao=acao, verbo=verbo, status=esperado):
                    self.respostas.clear()
                    self._cb(f"adm_{verbo}_{acao}_{dto.id}_pend_0")
                    # Em nenhum caso o estado muda.
                    self.assertEqual(
                        RepositorioUsuarios().obter_por_id(dto.id).status, esperado
                    )
                    if verbo == "do" and esperado == alvo_da_acao[acao]:
                        # Ja esta no estado-alvo: idempotente (sem notificar).
                        esperado_toast = "Já constava"
                    else:
                        esperado_toast = "não permite"
                    self.assertTrue(
                        any(esperado_toast in (t or "") for t in self._toasts()),
                        (esperado_toast, self._toasts()),
                    )
        self.assertEqual(self.enviados, [], "nada pode ser notificado")

    def test_estado_muda_entre_confirmacao_e_execucao(self):
        dto = self._seed(ALVO_ID, STATUS_PENDENTE, nome="Pedro Pendente")
        self._abrir_usuario("Solicitações pendentes", "Pedro")
        self._clicar("Rejeitar")  # tela de confirmacao
        botao_sim = self._dado_do_botao("Sim, rejeitar")

        RepositorioUsuarios().aprovar(dto.id)  # outro caminho aprovou no meio

        with self.assertLogs("robo.auditoria", level="INFO") as registro:
            self._cb(botao_sim)

        self.assertEqual(self._usuario(ALVO_ID).status, STATUS_APROVADO)
        self.assertEqual(self._textos_para(ALVO_ID), [])
        self.assertTrue(any("não permite" in (t or "") for t in self._toasts()))
        trilha = "\n".join(registro.output)
        self.assertIn("resultado=estado_invalido", trilha)
        self.assertIn("status_anterior=aprovado", trilha)

    def test_condicao_de_corrida_e_barrada_na_gravacao(self):
        """A leitura mostra um estado velho, mas o banco ja mudou."""
        dto = self._seed(ALVO_ID, STATUS_REJEITADO, nome="Rita Rejeitada")

        class _LeituraDefasada(RepositorioUsuarios):
            def obter_por_id(self, usuario_id):
                visto = super().obter_por_id(usuario_id)
                visto.status = STATUS_APROVADO  # tela antiga
                return visto

        original = self.central.RepositorioUsuarios
        self.central.RepositorioUsuarios = _LeituraDefasada
        try:
            self._cb(f"adm_do_suspender_{dto.id}_aprov_0")
        finally:
            self.central.RepositorioUsuarios = original

        self.assertEqual(self._usuario(ALVO_ID).status, STATUS_REJEITADO)
        self.assertFalse(self._usuario(ALVO_ID).ativo)
        self.assertEqual(self._textos_para(ALVO_ID), [])
        self.assertTrue(any("não permite" in (t or "") for t in self._toasts()))

    def test_clique_repetido_e_idempotente_e_notifica_uma_vez(self):
        dto = self._seed(ALVO_ID, STATUS_APROVADO, nome="Ana Aprovada")
        dado = f"adm_do_suspender_{dto.id}_aprov_0"
        self._cb(dado)
        with self.assertLogs("robo.auditoria", level="INFO") as registro:
            self._cb(dado)

        self.assertEqual(self._usuario(ALVO_ID).status, STATUS_SUSPENSO)
        self.assertEqual(self._textos_para(ALVO_ID), [self.cadastro.TEXTO_SUSPENSO])
        self.assertIn("resultado=ja_constava", "\n".join(registro.output))
        self.assertTrue(any("Já constava" in (t or "") for t in self._toasts()))

    def test_botao_antigo_do_cartao_de_solicitacao_nao_reativa_suspenso(self):
        """Fluxo ``cad_*``: um cartao antigo nao pode contornar a Central."""
        dto = self._seed(ALVO_ID, STATUS_SUSPENSO, nome="Sara Suspensa")
        self.enviados.clear()
        self.respostas.clear()
        self._cb(f"cad_aprovar_{dto.id}")
        self.assertEqual(self._usuario(ALVO_ID).status, STATUS_SUSPENSO)
        self.assertEqual(self._textos_para(ALVO_ID), [])
        self.assertTrue(any("não permite" in (t or "") for t in self._toasts()))

    def test_botao_antigo_do_cartao_nao_rejeita_usuario_aprovado(self):
        dto = self._seed(ALVO_ID, STATUS_APROVADO, nome="Ana Aprovada")
        self._cb(f"cad_rejeitar_{dto.id}")
        self.assertEqual(self._usuario(ALVO_ID).status, STATUS_APROVADO)
        self.assertEqual(self._textos_para(ALVO_ID), [])

    def test_cartao_de_solicitacao_pendente_continua_funcionando(self):
        dto = self._seed(ALVO_ID, STATUS_PENDENTE, nome="Pedro Pendente")
        self._cb(f"cad_aprovar_{dto.id}")
        self.assertEqual(self._usuario(ALVO_ID).status, STATUS_APROVADO)
        self.assertEqual(self._textos_para(ALVO_ID), [self.cadastro.TEXTO_APROVADO])

    def test_repositorio_pre_condicao_de_origem(self):
        dto = self._seed(ALVO_ID, STATUS_PENDENTE)
        repo = RepositorioUsuarios()

        bloqueado, mudou = repo.definir_status(
            dto.id, STATUS_SUSPENSO, origens_permitidas={STATUS_APROVADO}
        )
        self.assertFalse(mudou)
        self.assertEqual(bloqueado.status, STATUS_PENDENTE)
        self.assertEqual(repo.obter_por_id(dto.id).status, STATUS_PENDENTE)

        permitido, mudou = repo.definir_status(
            dto.id, STATUS_APROVADO, origens_permitidas={STATUS_PENDENTE}
        )
        self.assertTrue(mudou)
        self.assertEqual(permitido.status, STATUS_APROVADO)
        self.assertTrue(permitido.ativo)

        # Sem o argumento, o comportamento anterior e preservado.
        legado, mudou = repo.definir_status(dto.id, STATUS_SUSPENSO)
        self.assertTrue(mudou)
        self.assertEqual(legado.status, STATUS_SUSPENSO)
        self.assertFalse(legado.ativo)


class TestContasSomenteLeitura(_BaseCentral):
    def test_conta_definida_em_config_nao_pode_ser_alterada_pela_central(self):
        # Ex.: o usuario comum de config tem linha no banco como "pendente"
        # (valor padrao da migracao). Alterar o banco nao revogaria o acesso.
        dto = self._seed(USER_ID, STATUS_PENDENTE, nome="Usuario Config")
        self._abrir_usuario("Solicitações pendentes", "Usuario Config")

        texto, markup = self._tela()
        self.assertIn(self.central.TEXTO_ACESSO_FIXO, texto)
        self.assertFalse(self._tem_botao("Aprovar"))
        self.assertFalse(self._tem_botao("Rejeitar"))
        self.assertTrue(
            any("🔒" in r for r, _ in self._botoes(self._ultima_lista_markup()))
        )

        for verbo in ("conf", "do"):
            for acao in ("aprovar", "rejeitar"):
                self.respostas.clear()
                with self.assertLogs("robo.auditoria", level="INFO") as registro:
                    self._cb(f"adm_{verbo}_{acao}_{dto.id}_pend_0")
                self.assertIn("resultado=bloqueado", "\n".join(registro.output))
                self.assertIn(self.central.TEXTO_ACESSO_FIXO, self._toasts())
        self.assertEqual(self._usuario(USER_ID).status, STATUS_PENDENTE)
        self.assertEqual(self._textos_para(USER_ID), [])

    def _ultima_lista_markup(self):
        for texto, markup in reversed(self.telas):
            if "Toque em uma pessoa" in texto:
                return markup
        self.fail("nenhuma lista exibida")

    def test_o_proprio_administrador_nao_pode_se_suspender(self):
        self._seed(ADMIN_DB_ID, STATUS_APROVADO, nome="Admin Banco", papel="admin")
        dto = self._usuario(ADMIN_DB_ID)
        self._msg("/controles", ADMIN_DB_ID)
        self._clicar("Usuarios", ADMIN_DB_ID)
        self._clicar("Usuários aprovados", ADMIN_DB_ID)
        self._clicar("Admin Banco", ADMIN_DB_ID)

        texto, _m = self._tela()
        self.assertIn(self.central.TEXTO_PROPRIA_CONTA, texto)
        self.assertFalse(self._tem_botao("Suspender"))

        self._cb(f"adm_do_suspender_{dto.id}_aprov_0", ADMIN_DB_ID)
        self.assertEqual(self._usuario(ADMIN_DB_ID).status, STATUS_APROVADO)
        self.assertIn(self.central.TEXTO_PROPRIA_CONTA, self._toasts())

    def test_admin_principal_pode_suspender_outro_admin_do_banco(self):
        dto = self._seed(ADMIN_DB_ID, STATUS_APROVADO, nome="Admin Banco", papel="admin")
        self.assertEqual(permissoes.obter_papel(ADMIN_DB_ID), "admin")
        self._cb(f"adm_do_suspender_{dto.id}_aprov_0")
        self.assertEqual(self._usuario(ADMIN_DB_ID).status, STATUS_SUSPENSO)
        self.assertIsNone(permissoes.obter_papel(ADMIN_DB_ID))
        self.respostas.clear()
        self._cb("adm_home", ADMIN_DB_ID)
        self.assertEqual(self.genericos, [])
        self.assertIn(TEXTO_ACESSO_NEGADO, self._toasts())


class TestFalhasECallbacksMalformados(_BaseCentral):
    def test_falha_de_banco_na_listagem_e_tratada(self):
        def _quebrado():
            raise RuntimeError("banco indisponivel")

        repo_mod.obter_session_factory = _quebrado
        self._msg("/controles")
        self._cb("adm_usuarios")
        self.assertTrue(
            any(self.central.TEXTO_ERRO_BANCO == t for (_c, t, _k) in self.enviados)
            or any(
                self.central.TEXTO_ERRO_BANCO == t for (_c, _m, t, _k) in self.editados
            )
            or self.central.TEXTO_ERRO_BANCO in self._toasts()
        )
        self._cb("adm_area_pend_0")
        self.assertIn(self.central.TEXTO_ERRO_BANCO, self._toasts())

    def test_falha_ao_gravar_nao_altera_estado_nem_notifica_e_audita(self):
        dto = self._seed(ALVO_ID, STATUS_APROVADO, nome="Ana Aprovada")
        original = RepositorioUsuarios.definir_status

        def _falha(self, *a, **k):
            raise RuntimeError("falha ao gravar")

        RepositorioUsuarios.definir_status = _falha
        try:
            with self.assertLogs("robo.auditoria", level="INFO") as registro:
                self._cb(f"adm_do_suspender_{dto.id}_aprov_0")
        finally:
            RepositorioUsuarios.definir_status = original

        self.assertEqual(self._usuario(ALVO_ID).status, STATUS_APROVADO)
        self.assertEqual(self._textos_para(ALVO_ID), [])
        self.assertIn("resultado=falha_banco", "\n".join(registro.output))
        self.assertIn(self.central.TEXTO_ERRO_BANCO, self._toasts())

    def test_falha_no_envio_da_notificacao_nao_desfaz_a_decisao(self):
        dto = self._seed(ALVO_ID, STATUS_APROVADO, nome="Ana Aprovada")
        enviar_original = self.bot.send_message

        def _falha_envio(chat_id, text, **k):
            if int(chat_id) == ALVO_ID:
                raise RuntimeError("usuario bloqueou o bot")
            return enviar_original(chat_id, text, **k)

        self.bot.send_message = _falha_envio
        with self.assertLogs("robo.auditoria", level="INFO") as registro:
            self._cb(f"adm_do_suspender_{dto.id}_aprov_0")

        self.assertEqual(self._usuario(ALVO_ID).status, STATUS_SUSPENSO)
        self.assertIn("resultado=aplicada", "\n".join(registro.output))

    def test_callbacks_malformados_sao_ignorados_com_seguranca(self):
        dto = self._seed(ALVO_ID, STATUS_PENDENTE, nome="Pedro Pendente")
        malformados = [
            "adm_",
            "adm_x",
            "adm_area_zzz_0",
            "adm_area_pend_abc",
            "adm_area_pend_-1",
            "adm_area_pend",
            "adm_ver_abc_pend_0",
            "adm_ver_99999999999999999999_pend_0",
            "adm_do_aprovar_0_pend_0",
            "adm_do_aprovar_-1_pend_0",
            f"adm_do_hack_{dto.id}_pend_0",
            f"adm_do_aprovar_{dto.id}_pend",
            f"adm_do_aprovar_{dto.id}_pend_0_extra",
            f"adm_conf_excluir_{dto.id}_pend_0",
            f"adm_do_excluir_{dto.id}_pend_0",
            f"adm_do_aprovar_{dto.id}_zzz_0",
            f"adm_do_aprovar_{dto.id}_pend_99999999",
        ]
        for dado in malformados:
            with self.subTest(dado=dado):
                self.respostas.clear()
                self._cb(dado)
                self.assertEqual(len(self.respostas), 1)
                self.assertEqual(self._usuario(ALVO_ID).status, STATUS_PENDENTE)
        self.assertEqual(self.enviados, [])

    def test_parsers_do_callback_data_rejeitam_valores_fora_do_intervalo(self):
        c = self.central
        for invalido in ("0", "-1", "abc", "", None, "1.5", "99999999999999999999"):
            self.assertIsNone(c._id_usuario(invalido), invalido)
        self.assertEqual(c._id_usuario("7"), 7)
        self.assertEqual(c._id_usuario(str(2_147_483_647)), 2_147_483_647)
        self.assertIsNone(c._id_usuario(str(2_147_483_648)))
        for invalido in ("-1", "abc", "", None, "10001"):
            self.assertIsNone(c._num_pagina(invalido), invalido)
        self.assertEqual(c._num_pagina("0"), 0)
        self.assertEqual(c._num_pagina("10000"), 10000)

    def test_usuario_inexistente_e_informado(self):
        self._seed(ALVO_ID, STATUS_PENDENTE)
        self._cb("adm_ver_999999_pend_0")
        self.assertIn(self.central.TEXTO_USUARIO_INEXISTENTE, self._toasts())
        self._cb("adm_do_aprovar_999999_pend_0")
        self.assertIn(self.central.TEXTO_USUARIO_INEXISTENTE, self._toasts())

    def test_cada_callback_e_respondido_exatamente_uma_vez(self):
        self._seed(ALVO_ID, STATUS_PENDENTE, nome="Pedro Pendente")
        self._seed(OUTRO_ID, STATUS_APROVADO, nome="Ana Aprovada")
        self._msg("/controles")
        passos = [
            "Usuarios",
            "Solicitações pendentes",
            "Pedro",
            "Atualizar dados",
            "Rejeitar",
            "Cancelar",
            "Aprovar solicitação",
            "Voltar",
            "Usuários aprovados",
            "Ana",
            "Suspender",
            "Sim, suspender",
        ]
        for passo in passos:
            antes = len(self.respostas)
            self._clicar(passo)
            self.assertEqual(len(self.respostas) - antes, 1, passo)


class TestNotificacaoEPreservacao(_BaseCentral):
    def test_mensagem_ao_usuario_nao_expoe_informacao_administrativa(self):
        a = self._seed(1001, STATUS_PENDENTE, nome="Pedro Pendente", email="p@x.com")
        b = self._seed(1002, STATUS_APROVADO, nome="Ana Aprovada", email="a@x.com")
        c = self._seed(1003, STATUS_SUSPENSO, nome="Sara Suspensa", email="s@x.com")
        self._cb(f"adm_do_aprovar_{a.id}_pend_0")
        self._cb(f"adm_do_suspender_{b.id}_aprov_0")
        self._cb(f"adm_do_reativar_{c.id}_susp_0")

        enviados_aos_usuarios = [
            (cid, t, k) for (cid, t, k) in self.enviados if cid != ADMIN_ID
        ]
        self.assertEqual(len(enviados_aos_usuarios), 3)
        permitidos = {
            self.cadastro.TEXTO_APROVADO,
            self.cadastro.TEXTO_SUSPENSO,
            self.cadastro.TEXTO_REATIVADO,
        }
        for _cid, texto, kwargs in enviados_aos_usuarios:
            self.assertIn(texto, permitidos)
            self.assertNotIn(str(ADMIN_ID), texto)
            self.assertNotIn("Central", texto)
            self.assertNotIn("auditoria", texto.lower())
            self.assertNotIn("@x.com", texto)
            reply = kwargs.get("reply_markup")
            self.assertIsNone(reply, "sem botoes administrativos para o usuario")

    def test_nao_existe_exclusao_de_usuarios(self):
        self.assertEqual(
            set(self.central.ACOES),
            {"aprovar", "rejeitar", "suspender", "reativar"},
        )
        for objeto in (self.central, RepositorioUsuarios):
            for nome in dir(objeto):
                self.assertFalse(
                    any(p in nome.lower() for p in ("excluir", "deletar", "remover", "delete")),
                    nome,
                )

        antes = [
            self._seed(1001, STATUS_PENDENTE, nome="A"),
            self._seed(1002, STATUS_APROVADO, nome="B"),
            self._seed(1003, STATUS_REJEITADO, nome="C"),
            self._seed(1004, STATUS_SUSPENSO, nome="D"),
        ]
        total = self._total_linhas()
        self._cb(f"adm_do_rejeitar_{antes[0].id}_pend_0")
        self._cb(f"adm_do_suspender_{antes[1].id}_aprov_0")
        self._cb(f"adm_do_aprovar_{antes[2].id}_rej_0")
        self._cb(f"adm_do_reativar_{antes[3].id}_susp_0")
        self.assertEqual(self._total_linhas(), total)


class TestAtalhoDeTrocas(unittest.TestCase):
    """A Central oferece o atalho para decidir solicitacoes de troca."""

    def test_markup_home_inclui_solicitacoes_de_troca(self):
        import bot.central_controles as central

        markup = central._markup_home(
            {area: 0 for area in getattr(central, "AREAS", {})}
        )
        callbacks = [b.callback_data for linha in markup.keyboard for b in linha]
        self.assertIn("trocaadm_home", callbacks)
        self.assertIn("adm_home", callbacks)

    def test_markup_hub_tem_tres_areas(self):
        import bot.central_controles as central

        markup = central._markup_hub()
        callbacks = [b.callback_data for linha in markup.keyboard for b in linha]
        self.assertEqual(
            callbacks,
            ["adm_usuarios", "adm_notificacoes", "adm_revisoes", "voltar_menu"],
        )
        rotulos = [b.text for linha in markup.keyboard for b in linha]
        self.assertTrue(all(r.strip() and not r[0].isalnum() for r in rotulos))

    def test_notificacoes_oferece_recorte_por_pessoa_e_por_ativos(self):
        import bot.central_controles as central

        markup = central._markup_menu_notificacoes()
        callbacks = [b.callback_data for linha in markup.keyboard for b in linha]
        rotulos = [b.text for linha in markup.keyboard for b in linha]
        self.assertIn("adm_npessoas_0", callbacks)
        self.assertIn("adm_nativos", callbacks)
        self.assertIn("👤 Por pessoa", rotulos)
        self.assertIn("🏢 Por FIIs/acoes favoritados", rotulos)
        self.assertTrue(all(r.strip() and not r[0].isalnum() for r in rotulos))


if __name__ == "__main__":
    unittest.main()
