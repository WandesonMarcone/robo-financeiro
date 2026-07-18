import os
import time
import pytz
from flask import Flask, request
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import create_engine

# 1. Configurações Globais
import config

# 2. O Loader (Coração do bot - NÃO instanciar o bot novamente!)
from bot.loader import bot

# 3. Registrando os Comandos e Menus (Essencial para o bot "ouvir" o Telegram)
import bot.comandos
import bot.callbacks_revisao
import bot.callbacks_menus

# 4. Serviços (Orquestrador)
from services.orquestrador import varredura_diaria

# 5. Banco de Dados (Garantir a criação das tabelas)
from pipeline_dados.banco_dados import Base

# ==========================================
# ⚙️ CONFIGURAÇÃO INICIAL DO BANCO
# ==========================================
url_banco = os.environ.get('DATABASE_URL', 'sqlite:///pipeline_dados/banco_institucional.db')

if url_banco.startswith("postgres://"):
    url_banco = url_banco.replace("postgres://", "postgresql://", 1)

engine = create_engine(url_banco)
Base.metadata.create_all(engine)
print("✅ Banco de dados verificado e tabelas criadas com sucesso!")
print(f"DEBUG: Groq Key encontrada: {'SIM' if os.environ.get('GROQ_API_KEY') else 'NÃO'}")

# ==========================================
# 🌐 SERVIDOR WEB E WEBHOOK (RENDER)
# ==========================================
app = Flask(__name__)

@app.route('/' + config.TELEGRAM_BOT_TOKEN, methods=['POST'])
def webhook_handler():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "OK", 200
    return "Erro", 403

@app.route('/')
def index():
    return "Bot Institucional Ativo e Operante!", 200

# ==========================================
# ⏰ AGENDADOR DE TAREFAS (DESPERTADOR)
# ==========================================
fuso_horario = pytz.timezone('America/Sao_Paulo')
scheduler = BackgroundScheduler(timezone=fuso_horario)

# Agenda a varredura (que agora está protegida no services/orquestrador.py)
scheduler.add_job(varredura_diaria, CronTrigger(day_of_week='mon-fri', hour=8, minute=0))
scheduler.start()

# ==========================================
# 🚀 INICIALIZAÇÃO
# ==========================================
bot.remove_webhook()
time.sleep(1)

nova_url_render = "https://robo-fii-v2.onrender.com/" + config.TELEGRAM_BOT_TOKEN
bot.set_webhook(url=nova_url_render)
print(f"✅ Webhook configurado com sucesso para: {nova_url_render[:35]}...")

if __name__ == "__main__":
    porta = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=porta)
