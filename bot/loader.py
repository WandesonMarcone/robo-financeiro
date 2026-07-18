import telebot
import config

# O objeto 'bot' nasce aqui e será importado pelos outros módulos
bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN, threaded=False)

