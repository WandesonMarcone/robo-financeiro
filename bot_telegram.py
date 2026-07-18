import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import io
import json
import requests
import os
import re
import time
import config
import threading
import pytz # Para lidar com o fuso horário do Brasil
from sqlalchemy import text # IMPORTANTE: Permite rodar comandos SQL brutos no banco
from flask import Flask, request
from sqlalchemy import func, create_engine
from sqlalchemy.orm import sessionmaker


from services.planilhas import buscar_dados_planilha_com_cache
from services.orquestrador import varredura_diaria
from services.planilhas import buscar_ativo_na_planilha
from services.logo_service import obter_link_logo
from bot.loader import bot
import bot.comandos
import bot.callbacks_revisao


# Importações internas dos seus próprios módulos
from atualizador_documentos import rotina_de_atualizacao_em_massa
from modules.utils import conectar_gspread
from pipeline_dados import coletor_cvm
from modules import module_cvm
from modules import module_ia
from config import MAPA_ISCAS_MASTER, TIPOS_DOC
from modules import module_macro
from modules.GoogleDriveManager import GoogleDriveManager
from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos, DadosFinanceirosAcoes
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from pipeline_dados.coletor_cvm import AcoesCVMReader

# Importe o SessionDB do local onde você o definiu originalmente
from atualizador_documentos import SessionDB  
from datetime import datetime

# ==========================================
# ⚙️ CONFIGURAÇÕES INICIAIS E BANCO DE DADOS
# ==========================================
# Instancia o gerenciador que fará a ponte com o Google Drive
drive_manager = GoogleDriveManager()

# Pega o link do banco de dados das variáveis de ambiente do Render (ou usa SQLite local como fallback)
url_banco = os.environ.get('DATABASE_URL', 'sqlite:///pipeline_dados/banco_institucional.db')

# Corrige o prefixo caso o Render mande postgres:// em vez de postgresql:// (Exigência do SQLAlchemy)
if url_banco.startswith("postgres://"):
    url_banco = url_banco.replace("postgres://", "postgresql://", 1)

# Cria o 'motor' de conexão com o banco de dados
engine = create_engine(url_banco)

# Cria a fábrica de sessões (usada para abrir e fechar conversas com o banco)
SessionDB = sessionmaker(bind=engine)

from pipeline_dados.banco_dados import Base # Importe a sua Base declarativa

# Garante que as tabelas sejam criadas na nuvem se não existirem no primeiro deploy
Base.metadata.create_all(engine)
print("✅ Banco de dados verificado e tabelas criadas com sucesso!")

# Verifica se a chave de IA está configurada corretamente no servidor
print(f"DEBUG: Groq Key encontrada: {'SIM' if os.environ.get('GROQ_API_KEY') else 'NÃO'}")

# Inicializa o robô do Telegram (threaded=False evita conflitos com o Flask no Render)
bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN, threaded=False)

# Inicializa o servidor Web Flask (Necessário para manter o bot online no Render via Webhook)
app = Flask(__name__)

# ==========================================
# 🌐 ROTAS DO SERVIDOR WEB (WEBHOOK TELEGRAM)
# ==========================================
# Esta rota recebe as mensagens do Telegram em tempo real e entrega para o bot processar
@app.route('/' + config.TELEGRAM_BOT_TOKEN, methods=['POST'])
def webhook_handler():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "OK", 200
    return "Erro", 403

# Rota raiz de status para o Render saber que a aplicação não "morreu"
@app.route('/')
def index():
    return "Bot Institucional Ativo e Operante!", 200

# ==========================================
# 🛠️ COMANDOS DE MANUTENÇÃO E DEBUG DO BANCO
# ==========================================

@bot.message_handler(commands=['debug_ativo'])
def debug_ativo(message):
    ticker = "PETR4" 
    session = SessionDB()
    try:
        # 1. Verifica se o Ativo existe
        ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()
        if not ativo:
            bot.send_message(message.chat.id, f"❌ O ativo {ticker} nem sequer existe na tabela 'Ativos'.")
            return
        
        # 2. Verifica se existem registros financeiros usando a classe importada corretamente
        qtd = session.query(DadosFinanceirosAcoes).filter(DadosFinanceirosAcoes.ativo_id == ativo.id).count()
        
        # 3. Pega a última data salva
        ultima_data = session.query(func.max(DadosFinanceirosAcoes.data_referencia)).filter(DadosFinanceirosAcoes.ativo_id == ativo.id).scalar()
        
        bot.send_message(message.chat.id, f"🔍 Diagnóstico para {ticker}:\n\n✅ Ativo ID: {ativo.id}\n📊 Registros financeiros encontrados: {qtd}\n📅 Última data salva: {ultima_data}")
        
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Erro no debug: {e}")
    finally:
        session.close()



# ==========================================
# ROTINA DIÁRIA AUTOMÁTICA (O Despertador Mestre de Documentos)
# ==========================================
def varredura_diaria():
    """Função que o agendador chama todos os dias às 08h00 para buscar PDFs"""
    bot.send_message(config.TELEGRAM_CHAT_ID, "⚙️ *Bom dia! Iniciando a varredura automática de documentos...*", parse_mode="Markdown")
    
    # ------------------------------------------
    # 1. ETAPA FIIs (Fnet / B3)
    # ------------------------------------------
    try:
        bot.send_message(config.TELEGRAM_CHAT_ID, "🏢 Buscando novos Relatórios de FIIs na B3...")
        
        # Chama o nosso Maestro que lê a planilha e baixa tudo!
        qtd_fiis_salvos = rotina_de_atualizacao_em_massa()
        
        bot.send_message(config.TELEGRAM_CHAT_ID, f"✅ B3 finalizada! {qtd_fiis_salvos} novos documentos de FIIs salvos no Google Drive.")
    except Exception as e:
        bot.send_message(config.TELEGRAM_CHAT_ID, f"❌ Erro na varredura da B3: {e}")

    # ------------------------------------------
    # 2. ETAPA AÇÕES (Documentos CVM)
    # ------------------------------------------
    try:
        bot.send_message(config.TELEGRAM_CHAT_ID, "📈 Iniciando coleta de documentos e balanços de Ações na CVM...")
        
        # Aqui chamamos o coletor CORRETO (o arquivista de PDFs)
        # Substitua 'rodar_coleta' pelo nome exato da função que dispara o seu coletor_cvm
        coletor_cvm.rodar_coleta() 
        
        bot.send_message(config.TELEGRAM_CHAT_ID, "✅ CVM finalizada com sucesso! Novos PDFs de ações salvos.")
    except Exception as e:
        bot.send_message(config.TELEGRAM_CHAT_ID, f"❌ Erro na varredura de documentos da CVM: {e}")
        
    # Encerramento
    bot.send_message(config.TELEGRAM_CHAT_ID, "🏁 *Todas as rotinas finalizadas! O cofre de documentos está 100% atualizado para hoje.*", parse_mode="Markdown")

# ==========================================
# LIGANDO O AGENDADOR DE TAREFAS
# ==========================================
fuso_horario = pytz.timezone('America/Sao_Paulo')
scheduler = BackgroundScheduler(timezone=fuso_horario)

# Agenda a função unificada de documentos
scheduler.add_job(varredura_diaria, CronTrigger(day_of_week='mon-fri', hour=8, minute=0))

# Se você quiser adicionar o agendamento do module_cvm (para rodar 4x ao dia), 
# você pode fazer isso criando uma nova função e um novo 'scheduler.add_job' aqui no futuro!

scheduler.start()

# ==========================================
# INICIALIZAÇÃO DO SERVIDOR WEBHOOK (RENDER)
# ==========================================

# 1. Remove qualquer "polling" ou webhook antigo que tenha ficado preso no Telegram
bot.remove_webhook()
time.sleep(1)

# 2. Configura a nova URL do Render (A casa nova!)
nova_url_render = "https://robo-fii-v2.onrender.com/" + config.TELEGRAM_BOT_TOKEN
bot.set_webhook(url=nova_url_render)
# ANTIGA URL "robo-financeiro-7wkd.onrender.com"
print(f"✅ Webhook configurado com sucesso para: {nova_url_render[:35]}...")

# 3. Inicia o servidor Flask (Se for rodar direto, o Gunicorn assume se estiver no Render)
if __name__ == "__main__":
    porta = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=porta)
