"""Camada de identidade do bot (Etapa 10.2).

Resolve Telegram -> Usuario existente, classifica o fluxo
(PUBLICO / USUARIO / OPERACIONAL) e bloqueia comandos/callbacks abaixo do
mínimo. Não cria usuário, não cria sessão e não lê Sheets.
"""
import logging

from bot.loader import bot
from services import telegram

logger = logging.getLogger(__name__)

FLUXO_PUBLICO = telegram.FLUXO_PUBLICO
FLUXO_USUARIO = telegram.FLUXO_USUARIO
FLUXO_OPERACIONAL = telegram.FLUXO_OPERACIONAL

CALLBACKS_PUBLICOS = frozenset({"voltar_menu", "menu_ajuda", "ajuda_comandos", "ajuda_roadmap"})

# Handlers dedicados (handlers.py / callbacks_revisao.py / confirmacoes.py).
# O catch-all de menus não pode interceptá-los (FIFO do pyTelegramBotAPI).
_CALLBACKS_DEDICADOS = frozenset({
    "ajuda_roadmap",
    "ajuda_comandos",
    "ver_raiox_docs",
    "reset_confirmar",
    "reset_cancelar",
})
_PREFIXOS_DEDICADOS = (
    "tipo_fii_",
    "setor_fii_",
    "setor_acao_",
    "ia_",
    "ajuda_cvm_",
    "rev_",
)


def callback_pertence_ao_menu(call):
    """True só para callbacks sem handler dedicado (catch-all de menus)."""
    dados = getattr(call, "data", None) or ""
    if dados in _CALLBACKS_DEDICADOS:
        return False
    if dados.startswith(_PREFIXOS_DEDICADOS):
        return False
    return True

_MSG_VINCULO_OK = "Telegram vinculado à sua conta. Envie /menu para continuar."
_MSG_VINCULO_FALHA = (
    "Não foi possível vincular. Envie /start com um token de sessão válido."
)
_MSG_PUBLICO = (
    "Conta não vinculada. Para receber alertas e consultar dados da sua conta, "
    "envie /start TOKEN (token da sessão web/API). "
    "Ajuda: /menu."
)
_MSG_USUARIO = "Conta vinculada. Use /menu para navegar. Alertas seguem suas preferências."
_MSG_OPERACIONAL = (
    "*Terminal Institucional*\nSelecione o módulo de análise abaixo:"
)
_MSG_NEGADO_USUARIO = (
    "Comando disponível após vincular sua conta. Envie /start TOKEN."
)
_MSG_NEGADO_OPERACIONAL = "Acesso negado."


def telegram_id(evento):
    """``from_user.id`` de message ou callback; ``None`` se ausente."""
    origem = getattr(evento, "from_user", None)
    return getattr(origem, "id", None)


def chat_id(evento):
    """Chat id de message ou callback.message."""
    chat = getattr(evento, "chat", None)
    if chat is not None:
        return getattr(chat, "id", None)
    mensagem = getattr(evento, "message", None)
    if mensagem is not None:
        return getattr(getattr(mensagem, "chat", None), "id", None)
    return None


def fluxo_evento(evento, session=None):
    """``(fluxo, usuario)`` do Telegram que originou message/callback."""
    return telegram.fluxo_do_telegram(telegram_id(evento), session=session)


def _negar_mensagem(message, texto):
    try:
        bot.reply_to(message, texto)
    except Exception as e:
        logger.warning("Falha ao negar comando Telegram: %s", type(e).__name__)


def _negar_callback(call, texto):
    try:
        bot.answer_callback_query(call.id, texto, show_alert=True)
    except Exception as e:
        logger.warning("Falha ao negar callback Telegram: %s", type(e).__name__)


def exigir_fluxo_mensagem(message, fluxo_minimo, session=None):
    """True se a mensagem atende o fluxo mínimo; senão responde e retorna False."""
    tg_id = telegram_id(message)
    if telegram.comando_permitido(tg_id, fluxo_minimo, session=session):
        return True
    if fluxo_minimo == FLUXO_OPERACIONAL:
        _negar_mensagem(message, _MSG_NEGADO_OPERACIONAL)
    else:
        _negar_mensagem(message, _MSG_NEGADO_USUARIO)
    logger.warning(
        "Acesso Telegram negado: telegram_id=%s fluxo_minimo=%s",
        tg_id,
        fluxo_minimo,
    )
    return False


def exigir_fluxo_callback(call, fluxo_minimo, session=None):
    """True se o callback atende o fluxo mínimo; senão alerta e retorna False."""
    dados = getattr(call, "data", None) or ""
    if fluxo_minimo != FLUXO_PUBLICO and dados in CALLBACKS_PUBLICOS:
        return True
    tg_id = telegram_id(call)
    if telegram.comando_permitido(tg_id, fluxo_minimo, session=session):
        return True
    if fluxo_minimo == FLUXO_OPERACIONAL:
        _negar_callback(call, _MSG_NEGADO_OPERACIONAL)
    else:
        _negar_callback(call, _MSG_NEGADO_USUARIO)
    logger.warning(
        "Callback Telegram negado: telegram_id=%s fluxo_minimo=%s",
        tg_id,
        fluxo_minimo,
    )
    return False


def processar_start(message, session=None):
    """Vincula via payload de sessão (se houver) e devolve o fluxo atual.

    Retorna ``(fluxo, usuario, texto_resposta, vinculo_ok)``.
    ``vinculo_ok`` é True/False/None (None = sem tentativa de vínculo).
    """
    tg_id = telegram_id(message)
    payload = telegram.payload_comando_start(getattr(message, "text", "") or "")
    vinculo_ok = None
    if payload:
        usuario = telegram.vincular_telegram_por_sessao(
            payload,
            tg_id,
            telegram_chat_id=chat_id(message),
            session=session,
        )
        vinculo_ok = usuario is not None
    fluxo, usuario = telegram.fluxo_do_telegram(tg_id, session=session)
    if vinculo_ok is True:
        texto = _MSG_VINCULO_OK
    elif vinculo_ok is False:
        texto = _MSG_VINCULO_FALHA
    elif fluxo == FLUXO_OPERACIONAL:
        texto = _MSG_OPERACIONAL
    elif fluxo == FLUXO_USUARIO:
        texto = _MSG_USUARIO
    else:
        texto = _MSG_PUBLICO
    return fluxo, usuario, texto, vinculo_ok


def markup_inicio(fluxo):
    """Teclado inicial: mercado só para USUARIO/OPERACIONAL; ajuda para todos."""
    from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

    markup = InlineKeyboardMarkup()
    if fluxo in (FLUXO_USUARIO, FLUXO_OPERACIONAL):
        markup.row(
            InlineKeyboardButton("FIIs (Imobiliarios)", callback_data="menu_fiis"),
            InlineKeyboardButton("Acoes (Empresas)", callback_data="menu_acoes"),
        )
        markup.row(
            InlineKeyboardButton("Visao Macro e Noticias", callback_data="menu_macro")
        )
    markup.row(InlineKeyboardButton("Ajuda / Sobre", callback_data="menu_ajuda"))
    return markup
