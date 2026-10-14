"""Funções auxiliares do bot do Telegram.

Este módulo deve permanecer leve (sem importar o pipeline, o banco ou serviços
externos) para que a lógica de autorização, descrição de updates e tratamento de
falhas seja testável de forma isolada.
"""

import functools
import logging

import telebot

import config

logger = logging.getLogger("robo.telegram")

TEXTO_CALLBACK_DESCONHECIDO = (
    "⚠️ Este botão não é mais válido. Envie /menu para recomeçar."
)
TEXTO_FALHA_COMANDO = (
    "❌ Não foi possível concluir o comando. Tente novamente ou envie /menu."
)
TEXTO_FALHA_CALLBACK = (
    "⚠️ Erro ao processar este botão. Envie /menu para recomeçar."
)
TEXTO_ACESSO_NEGADO = (
    "⛔ Você não tem permissão para executar esta ação."
)
TEXTO_ACESSO_NEGADO_ADMIN = (
    "⛔ Esta ação é restrita ao administrador."
)

# Papéis (reaproveita a definição central em config).
PAPEL_ADMIN = config.PAPEL_ADMIN
PAPEL_USER = config.PAPEL_USER

# Hierarquia de papéis: quanto maior, mais permissões.
HIERARQUIA_PAPEIS = {PAPEL_USER: 1, PAPEL_ADMIN: 2}


def id_usuario_do_update(update):
    """Extrai o Telegram ID do usuário de um update (mensagem ou callback).

    Prefere ``from_user.id`` (autenticado pelo Telegram) e usa o id do chat
    apenas como fallback. Retorna None quando não há identificação.
    """
    if update is None:
        return None

    message = getattr(update, "message", None)
    if message is not None:
        from_user = getattr(message, "from_user", None)
        if from_user is not None and getattr(from_user, "id", None) is not None:
            return str(from_user.id)
        chat = getattr(message, "chat", None)
        if chat is not None and getattr(chat, "id", None) is not None:
            return str(chat.id)
        return None

    callback = getattr(update, "callback_query", None)
    if callback is not None:
        from_user = getattr(callback, "from_user", None)
        if from_user is not None and getattr(from_user, "id", None) is not None:
            return str(from_user.id)
        if callback.message is not None:
            return str(callback.message.chat.id)

    return None


def papel_do_update(update, papeis=None):
    """Retorna o papel do usuário do update, ou None se não autorizado."""
    mapa = config.PAPEIS_USUARIOS if papeis is None else papeis
    id_usuario = id_usuario_do_update(update)
    if id_usuario is None:
        return None
    return mapa.get(id_usuario)


def papel_suficiente(papel, papel_minimo):
    """Indica se ``papel`` atende (ou supera) ``papel_minimo``."""
    return HIERARQUIA_PAPEIS.get(papel, 0) >= HIERARQUIA_PAPEIS.get(papel_minimo, 99)


def usuario_autorizado(update, papeis=None):
    """Retorna True apenas para usuários com papel conhecido (admin ou user)."""
    return papel_suficiente(papel_do_update(update, papeis=papeis), PAPEL_USER)


def negar_acesso(bot_api, update, papel_minimo=None, logger=logger):
    """Registra e responde uma tentativa de acesso negada sem expor detalhes."""
    texto = (
        TEXTO_ACESSO_NEGADO_ADMIN
        if papel_minimo == PAPEL_ADMIN
        else TEXTO_ACESSO_NEGADO
    )
    logger.warning(
        "TELEGRAM - acesso negado (papel_minimo=%s): %s",
        papel_minimo,
        descrever_update(update),
    )
    if bot_api is None or update is None:
        return False

    try:
        callback = getattr(update, "callback_query", None)
        if callback is not None:
            bot_api.answer_callback_query(callback.id, text=texto, show_alert=True)
            return True
        message = getattr(update, "message", None)
        if message is not None:
            bot_api.send_message(message.chat.id, texto)
            return True
    except Exception:
        logger.debug("TELEGRAM - falha ao responder acesso negado", exc_info=True)
    return False


def requer_papel(bot_api, papel_minimo):
    """Decorator que só executa o handler se o usuário tiver o papel mínimo.

    Aplica-se a handlers de mensagem e de callback. Em caso de negação, registra
    a tentativa e responde ao usuário sem produzir nenhum efeito colateral.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            update = args[0] if args else (kwargs.get("message") or kwargs.get("call"))
            papel = papel_do_update(update)
            if papel_suficiente(papel, papel_minimo):
                return func(*args, **kwargs)
            negar_acesso(bot_api, update, papel_minimo=papel_minimo)
            return None

        wrapper.__papel_minimo__ = papel_minimo
        return wrapper

    return decorator



def chat_id_do_update(update):
    """Extrai o chat_id de um update de mensagem ou de callback (ou None)."""
    if update is None:
        return None

    message = getattr(update, "message", None)
    if message is not None:
        return message.chat.id

    callback = getattr(update, "callback_query", None)
    if callback is not None and callback.message is not None:
        return callback.message.chat.id

    return None


def chat_autorizado(update, chats_autorizados=None):
    """Retorna True se o update vier de um chat autorizado.

    Updates sem mensagem/callback (outros tipos) continuam sendo aceitos, para
    preservar o comportamento original. A lista autorizada vem de
    ``config.CHATS_AUTORIZADOS`` e não deve ser alterada aqui.
    """
    ids = config.CHATS_AUTORIZADOS if chats_autorizados is None else chats_autorizados
    chat_id = chat_id_do_update(update)
    if chat_id is None:
        return True
    return str(chat_id) in ids


def descrever_update(update):
    """Gera uma descrição curta e sem dados sensíveis, para logs verificáveis."""
    if update is None:
        return "desconhecido"

    message = getattr(update, "message", None)
    if message is not None:
        texto = getattr(message, "text", None)
        if texto:
            trecho = texto.strip().splitlines()[0][:80]
            return f"message chat_id={message.chat.id} text={trecho!r}"
        return (
            f"message chat_id={message.chat.id} "
            f"tipo={getattr(message, 'content_type', 'nao-texto')}"
        )

    callback = getattr(update, "callback_query", None)
    if callback is not None:
        chat_id = callback.message.chat.id if callback.message is not None else None
        return f"callback chat_id={chat_id} data={getattr(callback, 'data', None)!r}"

    return f"tipo={getattr(update, 'content_type', 'desconhecido')}"


def responder_callback_desconhecido(bot_api, callback_query_id, logger=logger):
    """Responde a um callback que não corresponde a nenhum fluxo conhecido."""
    try:
        bot_api.answer_callback_query(
            callback_query_id,
            text=TEXTO_CALLBACK_DESCONHECIDO,
        )
        return True
    except Exception:
        logger.debug(
            "TELEGRAM - falha ao responder callback desconhecido %s",
            callback_query_id,
            exc_info=True,
        )
        return False


class NotificadorDeFalhas(telebot.ExceptionHandler):
    """Torna visíveis as falhas dos handlers e evita respostas ausentes.

    Configurado em ``bot.loader``. O telebot captura internamente as exceções
    lançadas pelos handlers e, sem um ``exception_handler``, apenas as descarta
    (gerando falha silenciosa). Aqui registramos a falha com traceback e
    avisamos o usuário que originou a atualização.
    """

    def __init__(self):
        super().__init__()
        self.bot = None

    def handle(self, exception):
        update = getattr(self.bot, "_update_em_processamento", None) if self.bot else None
        logger.exception(
            "TELEGRAM - falha ao executar handler para %s: %s",
            descrever_update(update),
            exception,
        )
        if self.bot is not None:
            self.bot._falha_no_update = exception
        self._avisar_usuario(update)
        return True

    def _avisar_usuario(self, update):
        if self.bot is None or update is None:
            return
        try:
            message = getattr(update, "message", None)
            callback = getattr(update, "callback_query", None)
            if message is not None:
                self.bot.send_message(message.chat.id, TEXTO_FALHA_COMANDO)
            elif callback is not None:
                self.bot.answer_callback_query(callback.id, text=TEXTO_FALHA_CALLBACK)
        except Exception:
            logger.debug(
                "TELEGRAM - não foi possível avisar o usuário sobre a falha",
                exc_info=True,
            )
