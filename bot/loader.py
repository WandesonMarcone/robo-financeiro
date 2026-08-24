import logging

import telebot
import config

logger = logging.getLogger(__name__)


class _BotNoop:
    """Substituto do bot quando TELEGRAM_BOT_TOKEN não está definido.

    Mantém o restante do sistema (app.py, main.py, orquestrador, handlers)
    importável e executável sem Telegram: nenhuma mensagem é enviada, nenhum
    webhook é montado e os decoradores de handlers viram no-ops seguros.
    Registra TELEGRAM = SKIPPED para diagnóstico.
    """

    def __init__(self):
        self._avisou_skipped = False

    def _log_skipped(self, *args, **kwargs):
        if not self._avisou_skipped:
            logger.warning("[Telegram] TELEGRAM = SKIPPED (TELEGRAM_BOT_TOKEN ausente ou inválido)")
            self._avisou_skipped = True
        return None

    def callback_query_handler(self, *args, **kwargs):
        def decorator(func):
            return func
        return decorator

    def message_handler(self, *args, **kwargs):
        def decorator(func):
            return func
        return decorator

    def send_message(self, *args, **kwargs):
        return self._log_skipped()

    def reply_to(self, *args, **kwargs):
        return self._log_skipped()

    def edit_message_text(self, *args, **kwargs):
        return self._log_skipped()

    def answer_callback_query(self, *args, **kwargs):
        return self._log_skipped()

    def send_document(self, *args, **kwargs):
        return self._log_skipped()

    def process_new_updates(self, *args, **kwargs):
        return None

    def remove_webhook(self, *args, **kwargs):
        return None

    def set_webhook(self, *args, **kwargs):
        return None


# O objeto 'bot' nasce aqui e será importado pelos outros módulos.
# Sem token, usamos um substituto inerte para não derrubar o sistema.
if config.TELEGRAM_BOT_TOKEN:
    bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN, threaded=False)
else:
    bot = _BotNoop()


def enviar_mensagem(chat_id, texto, **kwargs):
    """Envia mensagem via Telegram de forma segura.

    Sem token ou sem chat_id configurado, registra TELEGRAM = SKIPPED e não
    envia nada, permitindo que o pipeline (Sheets -> PostgreSQL) continue
    funcionando. Com a configuração correta, preserva o comportamento atual.
    """
    if not config.TELEGRAM_BOT_TOKEN:
        logger.warning("[Telegram] TELEGRAM = SKIPPED (TELEGRAM_BOT_TOKEN ausente ou inválido)")
        return None
    if not chat_id:
        logger.warning("[Telegram] TELEGRAM = SKIPPED (TELEGRAM_CHAT_ID ausente)")
        return None
    try:
        return bot.send_message(chat_id, texto, **kwargs)
    except Exception as e:
        logger.warning("[Telegram] Erro ao enviar mensagem: %s", e)
        return None
