"""Funções auxiliares do bot do Telegram.

Este módulo deve permanecer leve (sem importar o pipeline, o banco ou serviços
externos) para que a lógica de autorização, descrição de updates e tratamento de
falhas seja testável de forma isolada.
"""

import logging

import telebot

import config

logger = logging.getLogger("robo.telegram")

TEXTO_CALLBACK_DESCONHECIDO = (
    "⚠️ Este botão não é mais válido. Envie /menu para recomeçar."
)
TEXTO_ACESSO_NEGADO = (
    "⛔ Você não tem permissão para executar esta operação."
)
TEXTO_FALHA_COMANDO = (
    "❌ Não foi possível concluir o comando. Tente novamente ou envie /menu."
)
TEXTO_FALHA_CALLBACK = (
    "⚠️ Erro ao processar este botão. Envie /menu para recomeçar."
)


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
