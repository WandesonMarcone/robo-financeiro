"""Testes do painel inicial personalizado (menu principal por usuario).

Cobrem a montagem pura do painel (``bot.telegram_utils.montar_painel_inicial``),
a resolucao de identidade/favoritos (``bot.menu_principal``) e o roteamento de
``/start`` e ``/menu``. Nenhuma conexao real e aberta: as tabelas ``usuarios``,
``ativos`` e ``ativos_acompanhados`` sao criadas num SQLite em memoria isolado e
as fabricas de sessao sao injetadas por monkeypatch; o bot e substituido por um
fake.

Cenarios exigidos pelo projeto:

* dois usuarios autorizados, com favoritos diferentes, veem apenas os proprios;
* usuario sem favoritos recebe o estado vazio (sem inventar ativos);
* administrador recebe o atalho da Central de Controles e seus proprios favoritos;
* usuario nao autorizado e contas pendente/rejeitada/suspensa nao veem o painel
  restrito;
* ``/start`` e ``/menu`` continuam funcionando;
* o painel nao duplica mensagens quando atualizado por callback.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import telebot  # noqa: E402
import telebot.util  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import config  # noqa: E402
import pipeline_dados.repositorio_favoritos as rf  # noqa: E402
import pipeline_dados.repositorio_usuarios as ru  # noqa: E402
from bot import menu_principal, permissoes  # noqa: E402
from bot import telegram_utils  # noqa: E402
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

ADMIN_ID = 8867098987
USER1_ID = 5336458734
USER2_ID = 222222222
PENDENTE_ID = 333333333
REJEITADO_ID = 444444444
SUSPENSO_ID = 555555555
CONF_PENDENTE_ID = 666666666


def _callbacks(markup):
    return [
        botao.callback_data
        for linha in markup.keyboard
        for botao in linha
        if botao.callback_data
    ]


def _textos(markup):
    return [botao.text for linha in markup.keyboard for botao in linha]


class _FromUser:
    """Objeto minimo compativel com ``getattr`` usado em telegram_utils."""

    def __init__(self, user_id, first_name=None, last_name=None, username=None):
        self.id = user_id
        self.first_name = first_name
        self.last_name = last_name
        self.username = username


class _Chat:
    def __init__(self, chat_id):
        self.id = chat_id


class _Mensagem:
    def __init__(self, texto, from_user):
        self.text = texto
        self.from_user = from_user
        self.chat = _Chat(from_user.id)


class _UpdateMensagem:
    def __init__(self, message):
        self.message = message
        self.callback_query = None


def _update_mensagem(texto, user_id, first_name="Teste"):
    mensagem = _Mensagem(texto, _FromUser(user_id, first_name=first_name))
    return _UpdateMensagem(mensagem)


# ---------------------------------------------------------------------------
# Montagem pura do painel
# ---------------------------------------------------------------------------


class TestMontarPainelInicial(unittest.TestCase):
    def test_saudacao_usa_o_nome_informado(self):
        texto, _markup = telegram_utils.montar_painel_inicial("Fulano de Tal")
        self.assertIn("Olá, Fulano de Tal.", texto)
        self.assertIn("Aqui está seu painel de investimentos.", texto)

    def test_nome_ausente_usa_fallback_seguro(self):
        texto, _markup = telegram_utils.montar_painel_inicial(None)
        self.assertIn(telegram_utils.NOME_PADRAO, texto)

    def test_nome_com_markdown_e_escapado(self):
        texto, _markup = telegram_utils.montar_painel_inicial("joao_silva*")
        self.assertIn("joao\\_silva\\*", texto)
        self.assertNotIn("Olá, joao_silva*", texto)

    def test_favoritos_separados_por_tipo(self):
        texto, _markup = telegram_utils.montar_painel_inicial(
            "Ana", favoritos_fii=["MXRF11"], favoritos_acao=["PETR4"]
        )
        self.assertIn("🏢 *Fundos Imobiliários*", texto)
        self.assertIn("📈 *Ações*", texto)
        self.assertIn("MXRF11", texto)
        self.assertIn("PETR4", texto)

    def test_sem_favoritos_mostra_estado_vazio(self):
        texto, _markup = telegram_utils.montar_painel_inicial("Ana")
        self.assertIn(telegram_utils.TEXTO_SEM_FAVORITOS, texto)
        self.assertNotIn("MXRF11", texto)

    def test_categoria_vazia_isolada(self):
        texto, _markup = telegram_utils.montar_painel_inicial(
            "Ana", favoritos_fii=["MXRF11"]
        )
        # Uma categoria preenchida e a outra vazia: apenas a vazia recebe o rotulo.
        self.assertEqual(texto.count(telegram_utils.TEXTO_CATEGORIA_VAZIA), 1)
        self.assertNotIn(telegram_utils.TEXTO_SEM_FAVORITOS, texto)

    def test_botoes_de_favoritos_abrem_o_painel_do_ativo(self):
        _texto, markup = telegram_utils.montar_painel_inicial(
            "Ana", favoritos_fii=["MXRF11"], favoritos_acao=["PETR4"]
        )
        callbacks = _callbacks(markup)
        self.assertIn("painel_MXRF11_fii", callbacks)
        self.assertIn("painel_PETR4_acao", callbacks)

    def test_atalhos_reais_do_menu_principal(self):
        _texto, markup = telegram_utils.montar_painel_inicial("Ana")
        callbacks = _callbacks(markup)
        self.assertIn(telegram_utils.TITULO_PAINEL, _texto)
        for esperado in (
            "novos_documentos",
            "minha_carteira",
            "meus_alertas",
            "gerenciar_favoritos",
            "minha_conta",
            "menu_ajuda",
        ):
            self.assertIn(esperado, callbacks)
        # Consulta geral de indicadores e exclusiva do administrador.
        self.assertNotIn("consultar_indicadores", callbacks)

    def test_layout_do_menu_principal_conforme_especificacao(self):
        def rotulos(markup):
            return [[b.text for b in linha] for linha in markup.keyboard]

        fixo = [
            ["📊 Minha carteira"],
            ["📄 Novos documentos", "🔔 Alertas"],
            ["⭐ Gerenciar favoritos"],
            ["👤 Minha conta", "ℹ️ Ajuda"],
        ]
        admin_esperado = [
            ["⚙️ Central de Controles"],
            ["📈 Consultar indicadores"],
            ["📊 Minha carteira"],
            ["📄 Novos documentos"],
            ["👤 Minha conta", "ℹ️ Ajuda"],
        ]
        _t, comum = telegram_utils.montar_painel_inicial("Ana")
        _t, admin = telegram_utils.montar_painel_inicial("Ana", incluir_admin=True)
        self.assertEqual(rotulos(comum)[-4:], fixo)
        self.assertEqual(rotulos(admin), admin_esperado)
        # O administrador não recebe o fluxo de seleção de favoritos do
        # cadastro/uso comum.
        callbacks_admin = _callbacks(admin)
        self.assertNotIn("gerenciar_favoritos", callbacks_admin)
        self.assertNotIn("meus_alertas", callbacks_admin)

    def test_indicadores_gerais_e_central_so_para_admin(self):
        _t, comum = telegram_utils.montar_painel_inicial("Ana")
        _t, admin = telegram_utils.montar_painel_inicial("Ana", incluir_admin=True)
        for restrito in ("consultar_indicadores", "adm_home"):
            self.assertNotIn(restrito, _callbacks(comum))
            self.assertIn(restrito, _callbacks(admin))

    def test_menu_basico_do_usuario_comum_nao_expoe_modulos_gerais(self):
        comum = _callbacks(telegram_utils.construir_menu_inicial(incluir_admin=False))
        admin = _callbacks(telegram_utils.construir_menu_inicial(incluir_admin=True))
        for geral in ("menu_fiis", "menu_acoes"):
            self.assertNotIn(geral, comum)
            self.assertIn(geral, admin)

    def test_botao_admin_apenas_quando_solicitado(self):
        _texto, sem_admin = telegram_utils.montar_painel_inicial("Ana")
        _texto, com_admin = telegram_utils.montar_painel_inicial(
            "Ana", incluir_admin=True
        )
        self.assertNotIn("adm_home", _callbacks(sem_admin))
        self.assertIn("adm_home", _callbacks(com_admin))

    def test_favoritos_aceitam_dto_e_string_com_deduplicacao(self):
        class _DTO:
            def __init__(self, ticker):
                self.ticker = ticker

        texto, markup = telegram_utils.montar_painel_inicial(
            "Ana", favoritos_fii=[_DTO("mxrf11"), "MXRF11", None]
        )
        self.assertIn("MXRF11", texto)
        # Apenas um botao para o mesmo ativo, mesmo recebendo DTO, string e None.
        self.assertEqual(_callbacks(markup).count("painel_MXRF11_fii"), 1)

    def test_saudacao_correta_disponivel_na_mensagem_de_boas_vindas(self):
        texto, _ = telegram_utils.montar_painel_inicial("Maria Silva")
        self.assertTrue(texto.startswith(telegram_utils.TITULO_PAINEL))


class TestNomeDeExibicaoDoTelegram(unittest.TestCase):
    def test_usa_nome_e_sobrenome(self):
        autor = _FromUser(1, first_name=" Joao ", last_name=" Silva ")
        self.assertEqual(telegram_utils.nome_de_exibicao_do_telegram(autor), "Joao Silva")

    def test_usa_username_quando_sem_nome(self):
        autor = _FromUser(1, username="joaozinho")
        self.assertEqual(
            telegram_utils.nome_de_exibicao_do_telegram(autor), "@joaozinho"
        )

    def test_sem_dados_retorna_none(self):
        self.assertIsNone(telegram_utils.nome_de_exibicao_do_telegram(_FromUser(1)))
        self.assertIsNone(telegram_utils.nome_de_exibicao_do_telegram(None))


# ---------------------------------------------------------------------------
# Integracao com banco (identidade, favoritos e autorizacao)
# ---------------------------------------------------------------------------


class _BaseBanco:
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

    def _criar_usuario(self, telegram_id, status, papel="user", ativo=None, nome=None):
        sessao = self.Session()
        try:
            if ativo is None:
                ativo = status == STATUS_APROVADO
            usuario = Usuario(
                nome=nome,
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

    def _semear(self, usuario_id, ticker):
        RepositorioFavoritos().adicionar(usuario_id, ticker)


class TestPainelPersonalizado(_BaseBanco, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._backup = {
            "USUARIOS_AUTORIZADOS": config.USUARIOS_AUTORIZADOS,
            "CHATS_AUTORIZADOS": config.CHATS_AUTORIZADOS,
        }
        # Admin e user1 reconhecidos por config; user2 apenas pelo banco.
        config.USUARIOS_AUTORIZADOS = {
            str(ADMIN_ID): config.PAPEL_ADMIN,
            str(USER1_ID): config.PAPEL_USUARIO,
            str(CONF_PENDENTE_ID): config.PAPEL_USUARIO,
        }

    @classmethod
    def tearDownClass(cls):
        for chave, valor in cls._backup.items():
            setattr(config, chave, valor)

    def setUp(self):
        self._preparar_banco()
        self.at1 = self._criar_usuario(USER1_ID, STATUS_APROVADO, nome="Usuario Um")
        self.at2 = self._criar_usuario(USER2_ID, STATUS_APROVADO, nome="Usuario Dois")
        self.admin = self._criar_usuario(
            ADMIN_ID, STATUS_PENDENTE, papel=config.PAPEL_ADMIN, ativo=False,
            nome="Administrador",
        )
        self._criar_ativo("MXRF11", "fii")
        self._criar_ativo("HGLG11", "fii")
        self._criar_ativo("PETR4", "acao")
        self._criar_ativo("VALE3", "acao")

    def tearDown(self):
        self._encerrar_banco()

    # -- Dois usuarios com favoritos diferentes ---------------------------

    def test_cada_usuario_ve_apenas_seus_favoritos(self):
        self._semear(self.at1, "MXRF11")
        self._semear(self.at1, "PETR4")
        self._semear(self.at2, "HGLG11")

        texto1, markup1 = menu_principal.montar_painel(USER1_ID)
        texto2, markup2 = menu_principal.montar_painel(USER2_ID)

        self.assertIn("MXRF11", texto1)
        self.assertIn("PETR4", texto1)
        self.assertNotIn("HGLG11", texto1)

        self.assertIn("HGLG11", texto2)
        self.assertNotIn("MXRF11", texto2)
        self.assertNotIn("PETR4", texto2)

        self.assertIn("painel_MXRF11_fii", _callbacks(markup1))
        self.assertIn("painel_PETR4_acao", _callbacks(markup1))
        self.assertIn("painel_HGLG11_fii", _callbacks(markup2))
        self.assertNotIn("painel_MXRF11_fii", _callbacks(markup2))

    def test_usuario_sem_favoritos_recebe_estado_vazio(self):
        texto, _markup = menu_principal.montar_painel(USER1_ID)
        self.assertIn(telegram_utils.TEXTO_SEM_FAVORITOS, texto)
        self.assertNotIn("painel_MXRF11_fii", _callbacks(_markup))

    def test_administrador_ve_atalho_e_favoritos_proprios(self):
        self._semear(self.admin, "VALE3")
        texto, markup = menu_principal.montar_painel(
            ADMIN_ID, _FromUser(ADMIN_ID, first_name="Admin")
        )
        callbacks = _callbacks(markup)
        self.assertIn("adm_home", callbacks)
        self.assertIn("VALE3", texto)
        self.assertNotIn("MXRF11", texto)

    # -- Saudacao ----------------------------------------------------------

    def test_saudacao_usa_nome_completo_do_cadastro(self):
        texto, _markup = menu_principal.montar_painel(
            USER1_ID, _FromUser(USER1_ID, first_name="Telegram")
        )
        self.assertIn("Olá, Usuario Um.", texto)
        self.assertNotIn("Telegram", texto)

    def test_saudacao_usa_nome_do_telegram_quando_cadastro_sem_nome(self):
        outro = self._criar_usuario(999999999, STATUS_APROVADO, nome=None)
        texto, _markup = menu_principal.montar_painel(
            999999999,
            _FromUser(999999999, first_name="Carla", last_name="Souza"),
        )
        self.assertIn("Olá, Carla Souza.", texto)
        self.assertIsNotNone(outro)

    # -- Favoritos: falha segura ------------------------------------------

    def test_falha_ao_carregar_favoritos_nao_quebra_o_painel(self):
        def _explodir():
            raise RuntimeError("banco indisponivel")

        rf.obter_session_factory = _explodir
        try:
            texto, markup = menu_principal.montar_painel(USER1_ID)
        finally:
            rf.obter_session_factory = lambda: self.Session
        self.assertIn(telegram_utils.TEXTO_SEM_FAVORITOS, texto)
        self.assertIn("novos_documentos", _callbacks(markup))
        self.assertIn("gerenciar_favoritos", _callbacks(markup))

    # -- Resolucao de identidade / autorizacao ----------------------------

    def test_usuario_autorizado_com_conta_aprovada(self):
        telegram_id, papel, dto, erro = menu_principal.usuario_autorizado(
            _Mensagem("/menu", _FromUser(USER2_ID))
        )
        self.assertIsNone(erro)
        self.assertEqual(telegram_id, USER2_ID)
        self.assertEqual(papel, config.PAPEL_USUARIO)
        self.assertIsNotNone(dto)

    def test_usuario_nao_autorizado_e_bloqueado(self):
        usuario, papel, dto, erro = menu_principal.usuario_autorizado(
            _Mensagem("/menu", _FromUser(777777777))
        )
        self.assertIsNone(usuario)
        self.assertIsNone(papel)
        self.assertIsNone(dto)
        self.assertEqual(erro, telegram_utils.TEXTO_ACESSO_NEGADO)

    def test_conta_pendente_bloqueada(self):
        self._criar_usuario(PENDENTE_ID, STATUS_PENDENTE)
        usuario, _papel, _dto, erro = menu_principal.usuario_autorizado(
            _Mensagem("/menu", _FromUser(PENDENTE_ID))
        )
        self.assertIsNone(usuario)
        self.assertIsNotNone(erro)

    def test_conta_rejeitada_bloqueada(self):
        self._criar_usuario(REJEITADO_ID, STATUS_REJEITADO)
        usuario, _papel, _dto, erro = menu_principal.usuario_autorizado(
            _Mensagem("/menu", _FromUser(REJEITADO_ID))
        )
        self.assertIsNone(usuario)
        self.assertIsNotNone(erro)

    def test_conta_suspensa_bloqueada(self):
        self._criar_usuario(SUSPENSO_ID, STATUS_SUSPENSO)
        usuario, _papel, _dto, erro = menu_principal.usuario_autorizado(
            _Mensagem("/menu", _FromUser(SUSPENSO_ID))
        )
        self.assertIsNone(usuario)
        self.assertIsNotNone(erro)

    def test_usuario_de_config_com_cadastro_pendente_recebe_aviso_conta(self):
        # Papel resolvido por config, mas cadastro no banco nao aprovado: o
        # usuario e barrado com o aviso de conta (nao com "sem permissao").
        self._criar_usuario(CONF_PENDENTE_ID, STATUS_PENDENTE)
        usuario, _papel, _dto, erro = menu_principal.usuario_autorizado(
            _Mensagem("/menu", _FromUser(CONF_PENDENTE_ID))
        )
        self.assertIsNone(usuario)
        self.assertEqual(erro, menu_principal.TEXTO_SEM_CONTA)

    def test_administrador_autorizado_mesmo_com_cadastro_pendente(self):
        # O admin e reconhecido pela config; o cadastro no banco esta pendente e
        # isso nao bloqueia o acesso administrativo (ver bot.favoritos).
        telegram_id, papel, dto, erro = menu_principal.usuario_autorizado(
            _Mensagem("/menu", _FromUser(ADMIN_ID))
        )
        self.assertIsNone(erro)
        self.assertEqual(telegram_id, ADMIN_ID)
        self.assertEqual(papel, config.PAPEL_ADMIN)
        self.assertIsNotNone(dto)
        self.assertFalse(dto.esta_aprovado())

    # -- Envio / edicao (sem duplicar mensagens) --------------------------

    def _com_bot_fake(self, enviados, editados=None):
        """Troca ``menu_principal._bot`` por um fake durante o bloco."""
        import contextlib

        @contextlib.contextmanager
        def _ctx():
            anterior = menu_principal._bot
            menu_principal._bot = lambda: _BotFake(enviados, editados)
            try:
                yield
            finally:
                menu_principal._bot = anterior

        return _ctx()

    def test_enviar_painel_envia_uma_mensagem(self):
        enviados = []
        with self._com_bot_fake(enviados):
            menu_principal.enviar_painel(
                USER1_ID, USER1_ID, _FromUser(USER1_ID, first_name="U1")
            )
        self.assertEqual(len(enviados), 1)
        self.assertIn("Olá, Usuario Um.", enviados[0][1])

    def test_editar_painel_edita_sem_enviar_nova_mensagem(self):
        enviados = []
        editados = []
        with self._com_bot_fake(enviados, editados):
            menu_principal.editar_painel(
                USER1_ID, 42, USER1_ID, _FromUser(USER1_ID, first_name="U1")
            )
        self.assertEqual(enviados, [])
        self.assertEqual(len(editados), 1)
        self.assertEqual(editados[0][:2], (USER1_ID, 42))


class _BotFake:
    def __init__(self, enviados, editados=None):
        self.enviados = enviados
        self.editados = editados if editados is not None else []

    def send_message(self, chat_id, texto, **kwargs):
        self.enviados.append((chat_id, texto, kwargs))

    def edit_message_text(self, texto, chat_id, message_id, **kwargs):
        self.editados.append((chat_id, message_id, texto, kwargs))

    def answer_callback_query(self, *args, **kwargs):
        return None


# ---------------------------------------------------------------------------
# Comandos /start e /menu
# ---------------------------------------------------------------------------


class TestComandosStartMenu(_BaseBanco, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._backup = {
            "USUARIOS_AUTORIZADOS": config.USUARIOS_AUTORIZADOS,
            "CHATS_AUTORIZADOS": config.CHATS_AUTORIZADOS,
            "TELEGRAM_BOT_TOKEN": getattr(config, "TELEGRAM_BOT_TOKEN", None),
        }
        config.USUARIOS_AUTORIZADOS = {
            str(ADMIN_ID): config.PAPEL_ADMIN,
            str(USER1_ID): config.PAPEL_USUARIO,
        }
        config.CHATS_AUTORIZADOS = [str(ADMIN_ID), str(USER1_ID)]
        telebot.util.validate_token = lambda *args, **kwargs: None
        config.TELEGRAM_BOT_TOKEN = "123456:FAKE-TOKEN-MENU-TESTE"
        # Importa o modulo de cadastro (registra os handlers de /start) e cria o
        # bot real (sem rede) para poder interceptar os envios de status.
        import bot.cadastro as cadastro

        cls.cadastro = cadastro
        cls.cadastro.bot.inicializar()

    @classmethod
    def tearDownClass(cls):
        for chave, valor in cls._backup.items():
            setattr(config, chave, valor)

    def setUp(self):
        self._preparar_banco()
        self.at1 = self._criar_usuario(USER1_ID, STATUS_APROVADO, nome="Usuario Um")
        self._criar_ativo("MXRF11", "fii")
        self.enviados = []
        self._painel_bot_anterior = menu_principal._bot
        menu_principal._bot = lambda: _BotFake(self.enviados)
        self._cadastro_send_anterior = self.cadastro.bot.send_message
        self.cadastro.bot.send_message = (
            lambda chat_id, texto, **kwargs: self.enviados.append(
                (chat_id, texto, kwargs)
            )
        )

    def tearDown(self):
        menu_principal._bot = self._painel_bot_anterior
        self.cadastro.bot.send_message = self._cadastro_send_anterior
        self._encerrar_banco()

    def test_menu_autorizado_e_permitido(self):
        permitido, operacao = permissoes.verificar_update(
            _update_mensagem("/menu", USER1_ID)
        )
        self.assertTrue(permitido)
        self.assertEqual(operacao, "comando:/menu")

    def test_menu_negado_para_desconhecido(self):
        permitido, _operacao = permissoes.verificar_update(
            _update_mensagem("/menu", 777777777)
        )
        self.assertFalse(permitido)

    def test_start_e_entrada_publica(self):
        permitido, operacao = permissoes.verificar_update(
            _update_mensagem("/start", 777777777)
        )
        self.assertTrue(permitido)
        self.assertEqual(operacao, "comando:/start")

    def test_start_de_usuario_autorizado_envia_painel(self):
        self._semear(self.at1, "MXRF11")
        autor = _FromUser(USER1_ID, first_name="U1")
        self.cadastro.iniciar_cadastro(_Mensagem("/start", autor))
        self.assertEqual(len(self.enviados), 1)
        texto = self.enviados[0][1]
        self.assertIn("Olá, Usuario Um.", texto)
        self.assertIn("Aqui está seu painel de investimentos.", texto)
        self.assertIn("MXRF11", texto)

    def test_start_do_admin_abre_painel_administrativo_sem_cadastro(self):
        autor = _FromUser(ADMIN_ID, first_name="Admin")
        self.cadastro.iniciar_cadastro(_Mensagem("/start", autor))
        self.assertEqual(len(self.enviados), 1)
        texto = self.enviados[0][1]
        self.assertIn("Painel administrativo", texto)
        self.assertNotIn("Cadastro de acesso", texto)
        callbacks = _callbacks(self.enviados[0][2]["reply_markup"])
        self.assertIn("adm_home", callbacks)
        self.assertNotIn("gerenciar_favoritos", callbacks)

    def test_start_de_conta_pendente_nao_mostra_painel(self):
        self._criar_usuario(PENDENTE_ID, STATUS_PENDENTE)
        autor = _FromUser(PENDENTE_ID, first_name="Pendente")
        self.cadastro.iniciar_cadastro(_Mensagem("/start", autor))
        self.assertEqual(len(self.enviados), 1)
        texto = self.enviados[0][1]
        self.assertNotIn("painel de investimentos", texto)
        self.assertEqual(texto, self.cadastro.TEXTO_PENDENTE)

    def test_comando_menu_envia_o_painel_personalizado(self):
        import bot.comandos as comandos

        self._semear(self.at1, "MXRF11")
        autor = _FromUser(USER1_ID, first_name="U1")
        comandos.enviar_menu(_Mensagem("/menu", autor))
        self.assertTrue(self.enviados)
        texto = self.enviados[-1][1]
        self.assertIn("Olá, Usuario Um.", texto)
        self.assertIn("Aqui está seu painel de investimentos.", texto)
        self.assertIn("MXRF11", texto)


if __name__ == "__main__":
    unittest.main()
