import telebot

TOKEN = "7777811765:AAEk3XQibBBYSFKRfQLzOWs_KpGOcPFR274"
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "✅ O Bot está vivo e funcional!")

print("Bot a rodar em modo teste (polling)...")
bot.polling()
