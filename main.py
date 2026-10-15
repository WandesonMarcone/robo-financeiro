import logging
import os
import time

import pytz
import telebot
from flask import Flask, request
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# 1. Configurações Globais
import config

# 2. O Loader (Coração do bot - NÃO instanciar o bot novamente!)
from bot.loader import bot, bot as tele_bot

# 3. Registrando os Comandos e Menus (Essencial para o bot "ouvir" o Telegram)
# Ordem importante: bot.cadastro e bot.favoritos sao registrados ANTES de
# bot.callbacks_menus. O telebot executa apenas o primeiro handler de callback
# cujo filtro casa, e bot.callbacks_menus registra um handler generico
# (func=lambda call: True). Registrar os modulos de fluxo especifico primeiro
# garante que seus callbacks (cad_*, favoritos_*, favadd_*, favnew_*, favrem_*)
# sejam tratados por eles, e nao engolidos pelo handler generico.
import bot.cadastro
import bot.favoritos
import bot.comandos
import bot.handlers
import bot.callbacks_revisao
import bot.callbacks_menus

# 4. Serviços (Orquestrador)
from services.orquestrador import varredura_diaria

# 5. Banco de Dados (conexão centralizada e normalizada)
from pipeline_dados.banco_dados import Base
from pipeline_dados.conexao import obter_engine

logger = logging.getLogger("robo.main")

URL_WEBHOOK_PADRAO = "https://robo-fii-v2.onrender.com"

# ==========================================
# 🌐 SERVIDOR WEB E WEBHOOK (RENDER)
# ==========================================
app = Flask(__name__)


@app.route('/' + (config.TELEGRAM_BOT_TOKEN or ""), methods=['POST'])
def webhook_handler():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)

        chat_id = None
        if update.message:
            chat_id = update.message.chat.id
        elif update.callback_query and update.callback_query.message:
            chat_id = update.callback_query.message.chat.id
        if chat_id is not None:
            logger.info("TELEGRAM DIAGNOSTICO - chat_id recebido: %s", chat_id)

        # CORREÇÃO: Usamos tele_bot para processar as mensagens, e não a pasta 'bot'
        tele_bot.process_new_updates([update])

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


def _flag_ativa(nome):
    return str(os.environ.get(nome, "")).strip().lower() in {"1", "true", "yes", "on"}


def criar_tabelas_se_solicitado():
    """Cria as tabelas dos modelos SOMENTE se explicitamente solicitado.

    Decisão (correção de inicialização): a aplicação NÃO executa
    ``Base.metadata.create_all`` automaticamente. O banco Neon já possui as
    tabelas (inclusive tabelas que não são representadas pelos modelos) e a
    criação de schema no boot poderia alterar um banco de produção. A criação
    permanece disponível de forma opt-in (``CRIAR_TABELAS=1``) para ambientes de
    desenvolvimento limpos.
    """
    if not _flag_ativa("CRIAR_TABELAS"):
        logger.info(
            "Criacao automatica de tabelas desativada "
            "(defina CRIAR_TABELAS=1 para habilitar em desenvolvimento)."
        )
        return
    engine = obter_engine()
    Base.metadata.create_all(engine)
    logger.info("Tabelas verificadas/criadas a pedido (CRIAR_TABELAS=1).")


def configurar_webhook():
    """Registra o webhook do Telegram. O token nunca é exposto em log."""
    base = (os.environ.get("WEBHOOK_BASE_URL") or URL_WEBHOOK_PADRAO).rstrip("/")
    nova_url = f"{base}/{config.TELEGRAM_BOT_TOKEN}"
    tele_bot.remove_webhook()
    time.sleep(1)
    tele_bot.set_webhook(url=nova_url)
    logger.info("Webhook configurado para %s/<token oculto>", base)


def iniciar_agendador():
    """Registra e inicia a varredura diária."""
    scheduler.add_job(
        varredura_diaria, CronTrigger(day_of_week='mon-fri', hour=8, minute=0)
    )
    scheduler.start()


def inicializar_aplicacao():
    """Efeitos colaterais de produção (chamados explicitamente no boot)."""
    criar_tabelas_se_solicitado()
    iniciar_agendador()
    configurar_webhook()


def main():
    inicializar_aplicacao()
    porta = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=porta)


# Compatibilidade: servidores WSGI (ex.: gunicorn main:app) podem optar por
# reproduzir o boot completo definindo ROBO_INICIAR_NO_IMPORT=1. Por padrão a
# importação não agenda jobs nem mexe no webhook/banco, para não afetar testes.
if _flag_ativa("ROBO_INICIAR_NO_IMPORT"):
    inicializar_aplicacao()


if __name__ == "__main__":
    main()
