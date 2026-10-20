"""Leitura de ``alertas_eventos`` pelos favoritos (somente consulta).

Cobre o repositorio (``pipeline_dados.repositorio_alertas``), o texto do
botao ``meus_alertas`` (``bot.menu_principal.texto_meus_alertas``) e o
fluxo do callback correspondente, sempre com SQLite em memoria isolado e
sem conexao ao Neon, Telegram real ou GHA.

Nenhum teste grava via writer de producao: as linhas de evento sao inseridas
direto no banco de teste. ``notificacoes`` e ``preferencias_usuarios`` nao
sao mapeadas nem consultadas.
"""

import inspect
import os
import sys
import unittest
from datetime import datetime
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, func  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import config  # noqa: E402
import pipeline_dados.repositorio_alertas as ra  # noqa: E402
import pipeline_dados.repositorio_favoritos as rf  # noqa: E402
import pipeline_dados.repositorio_usuarios as ru  # noqa: E402
from bot import callbacks_menus, menu_principal  # noqa: E402
from bot.telegram_utils import TEXTO_ACESSO_NEGADO  # noqa: E402
from pipeline_dados.banco_dados import Ativo, Base, TipoAtivo  # noqa: E402
from pipeline_dados.modelos_alertas import AlertaEvento, BaseAlertas  # noqa: E402
from pipeline_dados.modelos_ativos import BaseAcompanhados  # noqa: E402
from pipeline_dados.modelos_usuarios import (  # noqa: E402
    STATUS_APROVADO,
    STATUS_PENDENTE,
    STATUS_REJEITADO,
    STATUS_SUSPENSO,
    BaseUsuarios,
    Usuario,
)
from pipeline_dados.repositorio_alertas import RepositorioAlertas  # noqa: E402
from pipeline_dados.repositorio_favoritos import RepositorioFavoritos  # noqa: E402

ADMIN_ID = 8867098987
USER_A_ID = 5336458734
USER_B_ID = 222222222
DESCONHECIDO_ID = 777777777
TERMOS_ENTREGA = (
    "telegram_enviado",
    "entregue",
    "notificação entregue",
    "notificacao entregue",
    "falha de entrega",
    "mensagem enviada",
)
TERMOS_MERCADO_AUSENTE = (
    "não houve movimentação",
    "nao houve movimentacao",
    "nenhuma condição de mercado",
    "nenhuma condicao de mercado",
)


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
        BaseAlertas.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self._ra_original = ra.obter_session_factory
        self._rf_original = rf.obter_session_factory
        self._ru_original = ru.obter_session_factory
        ra.obter_session_factory = lambda: self.Session
        rf.obter_session_factory = lambda: self.Session
        ru.obter_session_factory = lambda: self.Session

    def _encerrar_banco(self):
        ra.obter_session_factory = self._ra_original
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

    def _criar_usuario(
        self, telegram_id=111, status=STATUS_APROVADO, papel="user", ativo=None
    ):
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

    def _inserir_evento(
        self,
        ativo_id,
        indicador,
        data_evento,
        tipo_alerta="QUALIDADE",
        tipo_ativo="FII",
        regra="VALOR_ZERO_SUSPEITO",
        motivo="indicador zerado",
        severidade="WARNING",
        valor_anterior=None,
        valor_atual=None,
        telegram_enviado=False,
    ):
        sessao = self.Session()
        try:
            evento = AlertaEvento(
                tipo_alerta=tipo_alerta,
                tipo_ativo=tipo_ativo,
                ativo_id=ativo_id,
                indicador=indicador,
                valor_anterior=valor_anterior,
                valor_atual=valor_atual,
                regra=regra,
                motivo=motivo,
                severidade=severidade,
                data_evento=data_evento,
                telegram_enviado=telegram_enviado,
            )
            sessao.add(evento)
            sessao.commit()
            sessao.refresh(evento)
            return evento.id
        finally:
            sessao.close()

    def _contar_usuarios(self):
        sessao = self.Session()
        try:
            return sessao.query(func.count(Usuario.id)).scalar()
        finally:
            sessao.close()


class _FromUser:
    def __init__(self, user_id, first_name="Teste"):
        self.id = user_id
        self.first_name = first_name
        self.last_name = None
        self.username = None
        self.is_bot = False


class _Chat:
    def __init__(self, chat_id):
        self.id = chat_id
        self.type = "private"


class _Mensagem:
    def __init__(self, chat_id, message_id=10):
        self.message_id = message_id
        self.chat = _Chat(chat_id)
        self.text = "menu"


class _Call:
    def __init__(self, user_id, data="meus_alertas", message_id=10):
        self.id = "cb-%s" % user_id
        self.data = data
        self.from_user = _FromUser(user_id)
        self.message = _Mensagem(user_id, message_id)


class _BotCaptura:
    def __init__(self):
        self.respostas = []
        self.editados = []
        self.enviados = []

    def answer_callback_query(self, cid, text=None, **kwargs):
        self.respostas.append((cid, text))

    def edit_message_text(self, texto, chat_id, message_id, **kwargs):
        self.editados.append((chat_id, message_id, texto, kwargs))

    def send_message(self, chat_id, texto, **kwargs):
        self.enviados.append((chat_id, texto, kwargs))


class TestRepositorioAlertas(_BaseBanco, unittest.TestCase):
    def setUp(self):
        self._preparar_banco()
        self.user1 = self._criar_usuario(111)
        self.user2 = self._criar_usuario(222)
        self.ativo_fii = self._criar_ativo("MXRF11", "fii")
        self.ativo_acao = self._criar_ativo("PETR4", "acao")
        self.repo = RepositorioAlertas()
        self.fav = RepositorioFavoritos()

    def tearDown(self):
        self._encerrar_banco()

    def test_lista_vazia_nao_consulta_o_banco(self):
        ra.obter_session_factory = lambda: (_ for _ in ()).throw(
            AssertionError("nao deveria consultar")
        )
        try:
            self.assertEqual(self.repo.listar_por_ativos([]), [])
            self.assertEqual(self.repo.listar_por_ativos(None), [])
            self.assertEqual(self.repo.listar_por_ativos(["x", None]), [])
        finally:
            ra.obter_session_factory = lambda: self.Session

    def test_sem_eventos_devolve_lista_vazia(self):
        self.assertEqual(self.repo.listar_por_ativos([self.ativo_fii]), [])

    def test_lista_apenas_os_ativos_informados(self):
        self._inserir_evento(
            self.ativo_fii, "pvp", datetime(2026, 10, 19, 10, 0)
        )
        self._inserir_evento(
            self.ativo_acao, "pl", datetime(2026, 10, 19, 11, 0)
        )
        eventos = self.repo.listar_por_ativos([self.ativo_fii])
        self.assertEqual([e.ticker for e in eventos], ["MXRF11"])
        self.assertEqual(eventos[0].indicador, "pvp")
        self.assertNotIn("PETR4", [e.ticker for e in eventos])

    def test_ordena_do_mais_recente(self):
        self._inserir_evento(
            self.ativo_fii, "dy", datetime(2026, 10, 18, 8, 0)
        )
        self._inserir_evento(
            self.ativo_fii, "pvp", datetime(2026, 10, 19, 18, 0)
        )
        eventos = self.repo.listar_por_ativos([self.ativo_fii])
        self.assertEqual([e.indicador for e in eventos], ["pvp", "dy"])

    def test_respeita_limite(self):
        for hora in range(3):
            self._inserir_evento(
                self.ativo_fii,
                f"ind{hora}",
                datetime(2026, 10, 19, hora, 0),
            )
        eventos = self.repo.listar_por_ativos([self.ativo_fii], limite=2)
        self.assertEqual(len(eventos), 2)
        self.assertEqual(eventos[0].indicador, "ind2")

    def test_preserva_valores_nulos_sem_inventar_zero(self):
        self._inserir_evento(
            self.ativo_fii,
            "pvp",
            datetime(2026, 10, 19, 12, 0),
            valor_atual=Decimal("1.25"),
            valor_anterior=None,
        )
        evento = self.repo.listar_por_ativos([self.ativo_fii])[0]
        self.assertEqual(evento.valor_atual, Decimal("1.25"))
        self.assertIsNone(evento.valor_anterior)
        self.assertFalse(evento.telegram_enviado)

    def test_isolamento_por_favoritos_de_usuarios(self):
        self.fav.adicionar(self.user1, "MXRF11")
        self.fav.adicionar(self.user2, "PETR4")
        self._inserir_evento(
            self.ativo_fii, "pvp", datetime(2026, 10, 19, 10, 0)
        )
        self._inserir_evento(
            self.ativo_acao, "pl", datetime(2026, 10, 19, 11, 0)
        )
        ids_user1 = [f.ativo_id for f in self.fav.listar(self.user1)]
        ids_user2 = [f.ativo_id for f in self.fav.listar(self.user2)]
        self.assertEqual(
            [e.ticker for e in self.repo.listar_por_ativos(ids_user1)],
            ["MXRF11"],
        )
        self.assertEqual(
            [e.ticker for e in self.repo.listar_por_ativos(ids_user2)],
            ["PETR4"],
        )


class TestTextoMeusAlertas(_BaseBanco, unittest.TestCase):
    def setUp(self):
        self._preparar_banco()
        self.user1 = self._criar_usuario(111)
        self.ativo_fii = self._criar_ativo("MXRF11", "fii")
        self.ativo_acao = self._criar_ativo("PETR4", "acao")
        self.fav = RepositorioFavoritos()

    def tearDown(self):
        self._encerrar_banco()

    def test_sem_favoritos_nao_consulta_alertas(self):
        ra.obter_session_factory = lambda: (_ for _ in ()).throw(
            AssertionError("nao deveria consultar alertas")
        )
        try:
            texto = menu_principal.texto_meus_alertas(self.user1)
        finally:
            ra.obter_session_factory = lambda: self.Session
        self.assertEqual(texto, menu_principal.TEXTO_ATIVOS_VAZIOS)

    def test_favoritos_sem_eventos(self):
        self.fav.adicionar(self.user1, "MXRF11")
        texto = menu_principal.texto_meus_alertas(self.user1)
        self.assertEqual(texto, menu_principal.TEXTO_ALERTAS_VAZIOS)

    def test_lista_eventos_dos_favoritos(self):
        self.fav.adicionar(self.user1, "MXRF11")
        self._inserir_evento(
            self.ativo_fii,
            "pvp",
            datetime(2026, 10, 19, 18, 5),
            tipo_alerta="CRITICO",
            regra="FORA_FAIXA_CRITICA",
            motivo="pvp acima da faixa",
            severidade="CRITICO",
            valor_atual=Decimal("1.25000000"),
            valor_anterior=Decimal("0.98000000"),
        )
        self._inserir_evento(
            self.ativo_acao,
            "pl",
            datetime(2026, 10, 19, 19, 0),
            tipo_ativo="ACAO",
        )
        texto = menu_principal.texto_meus_alertas(self.user1)
        self.assertIn("MXRF11", texto)
        self.assertIn("pvp", texto)
        self.assertIn("FORA\\_FAIXA\\_CRITICA", texto)
        self.assertIn("pvp acima da faixa", texto)
        self.assertIn("atual 1.25", texto)
        self.assertIn("anterior 0.98", texto)
        self.assertNotIn("PETR4", texto)
        self.assertNotIn("telegram_enviado", texto)

    def test_nao_mostra_valor_ausente_como_zero(self):
        self.fav.adicionar(self.user1, "MXRF11")
        self._inserir_evento(
            self.ativo_fii,
            "dy",
            datetime(2026, 10, 19, 9, 0),
            valor_atual=None,
            valor_anterior=None,
        )
        texto = menu_principal.texto_meus_alertas(self.user1)
        self.assertIn("MXRF11", texto)
        self.assertNotIn("atual 0", texto)
        self.assertNotIn("anterior 0", texto)

    def test_falha_de_banco_devolve_texto_seguro(self):
        def _explodir():
            raise RuntimeError("banco indisponivel")

        rf.obter_session_factory = _explodir
        try:
            texto = menu_principal.texto_meus_alertas(self.user1)
        finally:
            rf.obter_session_factory = lambda: self.Session
        self.assertEqual(texto, menu_principal.TEXTO_ERRO_BANCO)

    def test_falha_ao_ler_eventos_devolve_texto_seguro(self):
        self.fav.adicionar(self.user1, "MXRF11")

        def _explodir():
            raise RuntimeError("banco indisponivel")

        ra.obter_session_factory = _explodir
        try:
            texto = menu_principal.texto_meus_alertas(self.user1)
        finally:
            ra.obter_session_factory = lambda: self.Session
        self.assertEqual(texto, menu_principal.TEXTO_ERRO_BANCO)


class TestCallbackMeusAlertas(_BaseBanco, unittest.TestCase):
    """Ponto 1: fluxo do botao meus_alertas sem Telegram real."""

    def setUp(self):
        self._preparar_banco()
        self._backup = config.USUARIOS_AUTORIZADOS
        config.USUARIOS_AUTORIZADOS = {
            str(ADMIN_ID): config.PAPEL_ADMIN,
            str(USER_A_ID): config.PAPEL_USUARIO,
            str(USER_B_ID): config.PAPEL_USUARIO,
        }
        self.user_a = self._criar_usuario(USER_A_ID, STATUS_APROVADO)
        self.user_b = self._criar_usuario(USER_B_ID, STATUS_APROVADO)
        self.ativo_fii = self._criar_ativo("MXRF11", "fii")
        self.ativo_acao = self._criar_ativo("PETR4", "acao")
        self.fav = RepositorioFavoritos()
        self.captura = _BotCaptura()
        self._bot_anterior = menu_principal._bot
        menu_principal._bot = lambda: self.captura

    def tearDown(self):
        menu_principal._bot = self._bot_anterior
        config.USUARIOS_AUTORIZADOS = self._backup
        self._encerrar_banco()

    def _textos_editados(self):
        return [texto for (_cid, _mid, texto, _k) in self.captura.editados]

    def _respostas(self):
        return [texto for (_cid, texto) in self.captura.respostas]

    def test_autorizado_com_favoritos_e_eventos(self):
        self.fav.adicionar(self.user_a, "MXRF11")
        self._inserir_evento(
            self.ativo_fii,
            "pvp",
            datetime(2026, 10, 19, 18, 5),
            regra="FORA_FAIXA_CRITICA",
            motivo="pvp acima da faixa",
            severidade="CRITICO",
        )
        self._inserir_evento(
            self.ativo_acao, "pl", datetime(2026, 10, 19, 19, 0), tipo_ativo="ACAO"
        )
        callbacks_menus.callback_meus_alertas(_Call(USER_A_ID))
        self.assertEqual(self._respostas(), [None])
        self.assertEqual(len(self.captura.editados), 1)
        self.assertEqual(self.captura.enviados, [])
        texto = self._textos_editados()[0]
        self.assertIn("MXRF11", texto)
        self.assertIn("pvp acima da faixa", texto)
        self.assertNotIn("PETR4", texto)
        chat_id, message_id, _texto, kwargs = self.captura.editados[0]
        self.assertEqual((chat_id, message_id), (USER_A_ID, 10))
        self.assertEqual(kwargs.get("parse_mode"), "Markdown")

    def test_autorizado_com_favoritos_sem_eventos(self):
        self.fav.adicionar(self.user_a, "MXRF11")
        callbacks_menus.callback_meus_alertas(_Call(USER_A_ID))
        self.assertEqual(self._respostas(), [None])
        self.assertEqual(self._textos_editados(), [menu_principal.TEXTO_ALERTAS_VAZIOS])
        self.assertEqual(self.captura.enviados, [])

    def test_autorizado_sem_favoritos(self):
        callbacks_menus.callback_meus_alertas(_Call(USER_A_ID))
        self.assertEqual(self._respostas(), [None])
        self.assertEqual(self._textos_editados(), [menu_principal.TEXTO_ATIVOS_VAZIOS])
        self.assertEqual(self.captura.enviados, [])

    def test_falha_ao_consultar_favoritos(self):
        def _explodir():
            raise RuntimeError("banco indisponivel")

        rf.obter_session_factory = _explodir
        try:
            callbacks_menus.callback_meus_alertas(_Call(USER_A_ID))
        finally:
            rf.obter_session_factory = lambda: self.Session
        self.assertEqual(self._respostas(), [None])
        self.assertEqual(self._textos_editados(), [menu_principal.TEXTO_ERRO_BANCO])
        self.assertNotIn("Traceback", self._textos_editados()[0])
        self.assertEqual(self.captura.enviados, [])

    def test_falha_ao_consultar_eventos(self):
        self.fav.adicionar(self.user_a, "MXRF11")

        def _explodir():
            raise RuntimeError("banco indisponivel")

        ra.obter_session_factory = _explodir
        try:
            callbacks_menus.callback_meus_alertas(_Call(USER_A_ID))
        finally:
            ra.obter_session_factory = lambda: self.Session
        self.assertEqual(self._respostas(), [None])
        self.assertEqual(self._textos_editados(), [menu_principal.TEXTO_ERRO_BANCO])
        self.assertEqual(self.captura.enviados, [])

    def test_usuario_nao_autorizado(self):
        callbacks_menus.callback_meus_alertas(_Call(DESCONHECIDO_ID))
        self.assertEqual(self._respostas(), [TEXTO_ACESSO_NEGADO])
        self.assertEqual(self.captura.editados, [])
        self.assertEqual(self.captura.enviados, [])

    def test_conta_pendente_nao_lista_eventos(self):
        self._criar_usuario(333333333, STATUS_PENDENTE, ativo=False)
        config.USUARIOS_AUTORIZADOS[str(333333333)] = config.PAPEL_USUARIO
        self._inserir_evento(
            self.ativo_fii, "pvp", datetime(2026, 10, 19, 10, 0)
        )
        callbacks_menus.callback_meus_alertas(_Call(333333333))
        self.assertEqual(self._respostas(), [menu_principal.TEXTO_SEM_CONTA])
        self.assertEqual(self.captura.editados, [])
        self.assertEqual(self.captura.enviados, [])

    def test_conta_rejeitada_nao_lista_eventos(self):
        self._criar_usuario(444444444, STATUS_REJEITADO, ativo=False)
        config.USUARIOS_AUTORIZADOS[str(444444444)] = config.PAPEL_USUARIO
        callbacks_menus.callback_meus_alertas(_Call(444444444))
        self.assertEqual(self._respostas(), [menu_principal.TEXTO_SEM_CONTA])
        self.assertEqual(self.captura.editados, [])

    def test_conta_suspensa_nao_lista_eventos(self):
        self._criar_usuario(555555555, STATUS_SUSPENSO, ativo=False)
        config.USUARIOS_AUTORIZADOS[str(555555555)] = config.PAPEL_USUARIO
        callbacks_menus.callback_meus_alertas(_Call(555555555))
        self.assertEqual(self._respostas(), [menu_principal.TEXTO_SEM_CONTA])
        self.assertEqual(self.captura.editados, [])


class TestIsolamentoInterfaceAlertas(_BaseBanco, unittest.TestCase):
    """Ponto 2: isolamento A/B na montagem e no callback."""

    def setUp(self):
        self._preparar_banco()
        self._backup = config.USUARIOS_AUTORIZADOS
        config.USUARIOS_AUTORIZADOS = {
            str(USER_A_ID): config.PAPEL_USUARIO,
            str(USER_B_ID): config.PAPEL_USUARIO,
        }
        self.user_a = self._criar_usuario(USER_A_ID, STATUS_APROVADO)
        self.user_b = self._criar_usuario(USER_B_ID, STATUS_APROVADO)
        self.ativo_fii = self._criar_ativo("MXRF11", "fii")
        self.ativo_acao = self._criar_ativo("PETR4", "acao")
        self.fav = RepositorioFavoritos()
        self.fav.adicionar(self.user_a, "MXRF11")
        self.fav.adicionar(self.user_b, "PETR4")
        self._inserir_evento(
            self.ativo_fii, "pvp", datetime(2026, 10, 19, 10, 0), motivo="evento MXRF11"
        )
        self._inserir_evento(
            self.ativo_acao,
            "pl",
            datetime(2026, 10, 19, 11, 0),
            tipo_ativo="ACAO",
            motivo="evento PETR4",
        )
        self.captura = _BotCaptura()
        self._bot_anterior = menu_principal._bot
        menu_principal._bot = lambda: self.captura

    def tearDown(self):
        menu_principal._bot = self._bot_anterior
        config.USUARIOS_AUTORIZADOS = self._backup
        self._encerrar_banco()

    def test_texto_isola_eventos_por_favoritos(self):
        texto_a = menu_principal.texto_meus_alertas(self.user_a)
        texto_b = menu_principal.texto_meus_alertas(self.user_b)
        self.assertIn("MXRF11", texto_a)
        self.assertIn("evento MXRF11", texto_a)
        self.assertNotIn("PETR4", texto_a)
        self.assertNotIn("evento PETR4", texto_a)
        self.assertIn("PETR4", texto_b)
        self.assertIn("evento PETR4", texto_b)
        self.assertNotIn("MXRF11", texto_b)
        self.assertNotIn("evento MXRF11", texto_b)

    def test_callback_isola_eventos_por_usuario_autenticado(self):
        callbacks_menus.callback_meus_alertas(_Call(USER_A_ID))
        callbacks_menus.callback_meus_alertas(_Call(USER_B_ID))
        texto_a, texto_b = (
            self.captura.editados[0][2],
            self.captura.editados[1][2],
        )
        self.assertIn("MXRF11", texto_a)
        self.assertNotIn("PETR4", texto_a)
        self.assertIn("PETR4", texto_b)
        self.assertNotIn("MXRF11", texto_b)

    def test_callback_data_forjado_nao_consulta_outro_usuario(self):
        call = _Call(USER_A_ID, data="meus_alertas_%s" % self.user_b)
        callbacks_menus.callback_meus_alertas(call)
        self.assertEqual(len(self.captura.editados), 1)
        texto = self.captura.editados[0][2]
        self.assertIn("MXRF11", texto)
        self.assertNotIn("PETR4", texto)

    def test_falha_nao_devolve_eventos_globais(self):
        def _explodir():
            raise RuntimeError("banco indisponivel")

        ra.obter_session_factory = _explodir
        try:
            callbacks_menus.callback_meus_alertas(_Call(USER_A_ID))
        finally:
            ra.obter_session_factory = lambda: self.Session
        texto = self.captura.editados[0][2]
        self.assertEqual(texto, menu_principal.TEXTO_ERRO_BANCO)
        self.assertNotIn("MXRF11", texto)
        self.assertNotIn("PETR4", texto)


class TestAdminSemContaPersistida(_BaseBanco, unittest.TestCase):
    """Ponto 3: administrador autorizado sem registro usavel na Central."""

    def setUp(self):
        self._preparar_banco()
        self._backup = config.USUARIOS_AUTORIZADOS
        config.USUARIOS_AUTORIZADOS = {str(ADMIN_ID): config.PAPEL_ADMIN}
        self.ativo_fii = self._criar_ativo("MXRF11", "fii")
        self._inserir_evento(
            self.ativo_fii, "pvp", datetime(2026, 10, 19, 10, 0)
        )
        self.captura = _BotCaptura()
        self._bot_anterior = menu_principal._bot
        menu_principal._bot = lambda: self.captura

    def tearDown(self):
        menu_principal._bot = self._bot_anterior
        config.USUARIOS_AUTORIZADOS = self._backup
        self._encerrar_banco()

    def test_admin_sem_cadastro_e_autorizado_mas_nao_ve_eventos_globais(self):
        antes = self._contar_usuarios()
        telegram_id, papel, dto, erro = menu_principal.usuario_autorizado(
            _Call(ADMIN_ID)
        )
        self.assertIsNone(erro)
        self.assertEqual(telegram_id, ADMIN_ID)
        self.assertEqual(papel, config.PAPEL_ADMIN)
        self.assertIsNone(dto)
        callbacks_menus.callback_meus_alertas(_Call(ADMIN_ID))
        self.assertEqual(self.captura.respostas, [("cb-%s" % ADMIN_ID, menu_principal.TEXTO_SEM_CONTA)])
        self.assertEqual(len(self.captura.editados), 1)
        texto = self.captura.editados[0][2]
        self.assertEqual(texto, menu_principal.TEXTO_SEM_CONTA)
        self.assertNotIn("MXRF11", texto)
        self.assertEqual(self._contar_usuarios(), antes)


class TestEventoNaoEEntrega(_BaseBanco, unittest.TestCase):
    """Ponto 4: alertas_eventos e fato, nao fila de entrega."""

    def setUp(self):
        self._preparar_banco()
        self.user1 = self._criar_usuario(USER_A_ID, STATUS_APROVADO)
        self.ativo_fii = self._criar_ativo("MXRF11", "fii")
        self.fav = RepositorioFavoritos()
        self.fav.adicionar(self.user1, "MXRF11")

    def tearDown(self):
        self._encerrar_banco()

    def test_telegram_enviado_true_nao_afirma_entrega_ao_usuario(self):
        self._inserir_evento(
            self.ativo_fii,
            "pvp",
            datetime(2026, 10, 19, 10, 0),
            telegram_enviado=True,
            motivo="evento persistido",
        )
        texto = menu_principal.texto_meus_alertas(self.user1)
        self.assertIn("MXRF11", texto)
        self.assertIn("evento persistido", texto)
        lower = texto.lower()
        for termo in TERMOS_ENTREGA:
            self.assertNotIn(termo, lower)

    def test_telegram_enviado_false_nao_afirma_falha_de_entrega(self):
        self._inserir_evento(
            self.ativo_fii,
            "pvp",
            datetime(2026, 10, 19, 10, 0),
            telegram_enviado=False,
            motivo="evento persistido",
        )
        texto = menu_principal.texto_meus_alertas(self.user1)
        self.assertIn("MXRF11", texto)
        lower = texto.lower()
        for termo in TERMOS_ENTREGA:
            self.assertNotIn(termo, lower)

    def test_ausencia_de_eventos_nao_afirma_ausencia_de_mercado(self):
        texto = menu_principal.texto_meus_alertas(self.user1)
        self.assertEqual(texto, menu_principal.TEXTO_ALERTAS_VAZIOS)
        lower = texto.lower()
        for termo in TERMOS_MERCADO_AUSENTE:
            self.assertNotIn(termo, lower)

    def test_nulo_continua_desconhecido(self):
        self._inserir_evento(
            self.ativo_fii,
            "dy",
            datetime(2026, 10, 19, 9, 0),
            valor_atual=None,
            valor_anterior=None,
        )
        texto = menu_principal.texto_meus_alertas(self.user1)
        self.assertIn("MXRF11", texto)
        self.assertNotIn("atual 0", texto)
        self.assertNotIn("anterior 0", texto)

    def test_central_nao_consulta_notificacoes_nem_preferencias(self):
        fontes = (
            inspect.getsource(RepositorioAlertas.listar_por_ativos),
            inspect.getsource(callbacks_menus.callback_meus_alertas),
        )
        conjunto = "\n".join(fontes)
        self.assertNotIn("notificacoes", conjunto)
        self.assertNotIn("preferencias_usuarios", conjunto)
        corpo = inspect.getsource(menu_principal.texto_meus_alertas)
        self.assertIn("RepositorioFavoritos", corpo)
        self.assertIn("RepositorioAlertas", corpo)
        self.assertNotIn("preferencias_usuarios", corpo)
        self.assertNotIn("RepositorioNotificacoes", conjunto)


if __name__ == "__main__":
    unittest.main()
