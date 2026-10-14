import telebot
import config


class BotAutorizado(telebot.TeleBot):
    """Bot que descarta atualizações (mensagens e callbacks) de chats não autorizados."""

    def _chat_autorizado(self, update):
        if update.message:
            chat_id = update.message.chat.id
        elif update.callback_query and update.callback_query.message:
            chat_id = update.callback_query.message.chat.id
        else:
            return True
        return str(chat_id) in config.CHATS_AUTORIZADOS

    def process_new_updates(self, updates):
        autorizados = [u for u in updates if self._chat_autorizado(u)]
        return super().process_new_updates(autorizados)


# O objeto 'bot' nasce aqui e será importado pelos outros módulos
bot = BotAutorizado(config.TELEGRAM_BOT_TOKEN, threaded=False)
