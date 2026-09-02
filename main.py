import logging
import os
import sqlite3

import config

logger = logging.getLogger(__name__)

def garantir_banco_atualizado():
    # Migração legada exclusiva do SQLite local (banco de desenvolvimento).
    # Só tem efeito quando a conexão ativa é o SQLite padrão, ou seja, quando
    # DATABASE_URL não foi definida. Em produção (PostgreSQL/Neon) a coluna já
    # faz parte do modelo ORM e não existe arquivo SQLite operacional.
    url = config.obter_database_url()
    if not url.startswith("sqlite:///"):
        logger.info("Conexão ativa não é SQLite local; migração legada ignorada.")
        return

    db_path = url.replace("sqlite:///", "", 1)

    # Se o banco existe, verificamos a coluna
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            # Tenta adicionar a coluna. Se ela já existir, o SQLite ignora o erro silenciosamente
            cursor.execute("ALTER TABLE documentos_qualitativos ADD COLUMN status_processamento VARCHAR")
            conn.commit()
            conn.close()
            print("✅ Banco atualizado com sucesso na inicialização!")
        except Exception:
            # Se der erro (provavelmente porque a coluna já existe), apenas continuamos
            print("ℹ️ Verificação do banco concluída.")

# CHAME ESSA FUNÇÃO ANTES DE INICIAR O BOT
garantir_banco_atualizado()

# ... resto do seu código (bot.polling, etc) ...


import time

import pytz
import telebot
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import Flask, request

from bot.loader import bot as tele_bot

# 1. Configurações Globais

# Logging estruturado + validação de configuração no startup
config.configurar_logging()
problemas, avisos = config.verificar_configuracao()
for aviso in avisos:
    logger.warning("Configuração incompleta: %s", aviso)
for problema in problemas:
    logger.error("Configuração ausente (obrigatória): %s", problema)

# 2. O Loader (Coração do bot - NÃO instanciar o bot novamente!)
import bot.callbacks_menus  # noqa: F401 (registra handlers por efeito colateral)
import bot.callbacks_revisao
import bot.comandos
import bot.confirmacoes  # Confirmação explícita de operações destrutivas
import bot.handlers

# ==========================================
# ⚙️ CONFIGURAÇÃO INICIAL DO BANCO
# ==========================================
# Engine único e centralizado (Fase 2): o create_engine vive em
# atualizador_documentos.py com pool settings; aqui apenas reutilizamos o
# mesmo engine para criar as tabelas, sem duplicar a configuração da conexão.
from atualizador_documentos import engine
from bot.loader import bot  # noqa: F401 (garante que o bot do loader é usado, sem nova instância)

# 5. Banco de Dados (Garantir a criação das tabelas)
from pipeline_dados.banco_dados import Base

# 4. Serviços (Orquestrador)
from services.orquestrador import varredura_diaria

# 4.1 Seed do SUPERADMIN (Fase 5, Etapa 5): roda após a criação das tabelas.
from services.seed import garantir_superadmin_inicial

Base.metadata.create_all(engine)
logger.info("Banco de dados verificado e tabelas criadas com sucesso.")
logger.info("Groq Key presente: %s", "SIM" if os.environ.get('GROQ_API_KEY') else "NÃO")

# ==========================================
# 🚀 SEED DO PRIMEIRO SUPERADMIN (FASE 5)
# ==========================================
# Idempotente: cria/eleva o administrador de referência (PRIMEIRO_ADMIN_TELEGRAM_ID
# ou TELEGRAM_CHAT_ID legado) sem duplicar usuários e sem sobrescrever dados.
# Qualquer falha é apenas registrada — nunca derruba o bot/webhook/agendador.
try:
    _resultado_seed = garantir_superadmin_inicial()
    logger.info("Seed do SUPERADMIN: status=%s", _resultado_seed.get("status"))
except Exception as e:  # pragma: no cover - defesa extra (o seed nunca lança)
    logger.error("Seed do SUPERADMIN falhou (não bloqueia o bot): %s", e)

# ==========================================
# 🌐 SERVIDOR WEB E WEBHOOK (RENDER)
# ==========================================
app = Flask(__name__)

# ==========================================
# 🌐 API HTTP /api/v1 (Fase 5, Etapa 10)
# ==========================================
# Integração aditiva: respeita API_ENABLED. Desabilitada (padrão) -> nenhuma
# rota/handler é registrado e o comportamento legado permanece intacto.
from api import integrar_api

if config.API_ENABLED:
    integrar_api(app)
    logger.info("API HTTP /api/v1 habilitada.")
else:
    logger.info("API HTTP /api/v1 desabilitada (API_ENABLED).")

# A rota do webhook só existe quando TELEGRAM_BOT_TOKEN está definido.
# Sem token, não registramos a rota (evita rota inválida '/' + None).
if config.TELEGRAM_BOT_TOKEN:
    @app.route('/' + config.TELEGRAM_BOT_TOKEN, methods=['POST'])
    def webhook_handler():
        if request.headers.get('content-type') == 'application/json':
            json_string = request.get_data().decode('utf-8')
            update = telebot.types.Update.de_json(json_string)

            # CORREÇÃO: Usamos tele_bot para processar as mensagens, e não a pasta 'bot'
            tele_bot.process_new_updates([update])

            return "OK", 200
        return "Erro", 403
else:
    logger.warning("[Telegram] TELEGRAM = SKIPPED: webhook não registrado (TELEGRAM_BOT_TOKEN ausente).")


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
# 🚀 INICIALIZAÇÃO DO WEBHOOK (CORRIGIDO)
# ==========================================

if config.TELEGRAM_BOT_TOKEN:
    tele_bot.remove_webhook()
    time.sleep(1)
    nova_url_render = config.WEBHOOK_URL_BASE + "/" + config.TELEGRAM_BOT_TOKEN
    tele_bot.set_webhook(url=nova_url_render)
    logger.info("Webhook configurado para o endpoint do bot (URL truncada por segurança).")
else:
    logger.warning("[Telegram] TELEGRAM = SKIPPED: webhook não registrado (TELEGRAM_BOT_TOKEN ausente).")

if __name__ == "__main__":
    porta = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=porta)
