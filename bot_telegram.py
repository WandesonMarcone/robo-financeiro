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

# ==========================

# ==========================================
# 📊 COMANDOS DE PLANILHA DO GOOGLE
# ==========================================

# Permite adicionar um novo ativo direto na sua planilha do Drive via Telegram
@bot.message_handler(commands=['adicionar'])
def comando_adicionar(message):
    try:
        # Separa o comando da palavra. Ex: ["/adicionar", "BBAS3"]
        partes = message.text.split()
        if len(partes) < 2:
            bot.reply_to(message, "⚠️ Uso correto: `/adicionar TICKER` (ex: /adicionar BBAS3)", parse_mode="Markdown")
            return

        ticker = partes[1].strip().upper()
        bot.reply_to(message, f"A procurar {ticker} e a injetar na Planilha do Google...")

        # Conecta no Google Sheets
        planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
        
        # Inteligência simples: Se terminar em 11 é FII, se não é Ação.
        is_fii = True if ticker.endswith('11') else False
        nome_aba = "BD_FIIs" if is_fii else "BD_Acoes"
        aba = planilha.worksheet(nome_aba)

        # Encontra a última linha vazia da aba escolhida
        dados = aba.get_all_values()
        proxima_linha = len(dados) + 1
        
        # Insere o dado na planilha oficial
        aba.update(f'A{proxima_linha}', [[ticker]])

        bot.send_message(message.chat.id, f"✅ *{ticker}* adicionado com sucesso na aba `{nome_aba}`!", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Erro ao adicionar ativo: {e}")

# ==========================================
# ⚙️ COMANDOS DE MONITORAMENTO E STATUS
# ==========================================

# Comando /reciclar: Reativa documentos que foram descartados incorretamente no passado
@bot.message_handler(commands=['reciclar_rejeitados'])
def comando_reciclar_rejeitados(message):
    bot.send_message(message.chat.id, "♻️ Buscando documentos rejeitados no banco...")
    session = SessionDB()
    try:
        # Muda o status de rejeitado para pendente para uma nova tentativa de IA
        rejeitados = session.query(DocumentosQualitativos).filter(
            DocumentosQualitativos.status_processamento == 'REJEITADO_DUPLO_FATOR'
        ).all()

        contador = 0
        for doc in rejeitados:
            doc.status_processamento = 'PENDENTE' 
            contador += 1

        session.commit()
        bot.send_message(message.chat.id, f"✅ {contador} documentos foram devolvidos para a fila!")
    finally:
        session.close()

# ==========================================
# COMANDO SECRETO PARA TESTAR A VARREDURA
# ==========================================
@bot.message_handler(commands=['forcar_varredura'])
def acionar_varredura_manual(message):
    # 1. Responde instantaneamente para o Telegram e pro Render não darem Timeout
    bot.reply_to(message, "⚙️ *Iniciando varredura na B3 em segundo plano...*\nIsso pode levar alguns minutos. Pode continuar usando o bot normalmente, eu te aviso quando terminar!", parse_mode="Markdown")
    
    # 2. Cria a função pesada isolada
    def tarefa_pesada_background():
        try:
            from atualizador_documentos import rotina_de_atualizacao_em_massa
            relatorios_baixados = rotina_de_atualizacao_em_massa()
            
            # Quando terminar, envia uma nova mensagem avisando
            bot.send_message(message.chat.id, f"✅ *Varredura Concluída!*\n\n📥 Documentos inéditos salvos no Drive: **{relatorios_baixados}**", parse_mode="Markdown")
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ *Erro na varredura:* {e}", parse_mode="Markdown")

    # 3. Dá a ordem para o Python rodar isso em uma trilha separada (Thread)
    thread = threading.Thread(target=tarefa_pesada_background)
    thread.start()

# ----------FORÇAR CVM------------
@bot.message_handler(commands=['forcar_cvm'])
def rodar_cvm(message):
    bot.send_message(message.chat.id, "⏳ Iniciando download de balanços da CVM. Isso pode demorar alguns minutos...")
    try:
        from coletor_cvm import AcoesCVMReader
        session = SessionDB()
        coletor = AcoesCVMReader(session)
        
        # Você pode mudar o ano aqui futuramente ou deixar dinâmico
        coletor.atualizar_acoes(2026) 
        
        session.close()
        bot.send_message(message.chat.id, "✅ Coleta CVM concluída! Balanços salvos no banco de dados.")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Erro na CVM: {str(e)}")

# ==========================================
# O NOVO MOTOR DE DASHBOARD (Arquitetura)
# ==========================================

def gerar_painel_ativo(ticker, tipo, chat_id, message_id=None):
    """Gera a mensagem principal com os botões interativos e dados em tempo real"""
    is_fii = (tipo == 'fii')
    icone = "🏢 Fundo" if is_fii else "📈 Ação"
    voltar_cmd = "menu_fiis" if is_fii else "menu_acoes"

    # 1. Puxar as Logos e Dados Reais da Planilha
    url_logo = obter_link_logo(ticker, tipo, driver_manager)
    indicadores = buscar_dados_planilha(ticker, is_fii)

    # Tratamento de erro caso o ativo não esteja na planilha
    if not indicadores:
        msg_erro = f"❌ Erro: Não encontrei dados para **{ticker}** na planilha."
        if message_id:
            bot.edit_message_text(msg_erro, chat_id, message_id, parse_mode="Markdown")
        else:
            bot.send_message(chat_id, msg_erro, parse_mode="Markdown")
        return

    # 2. Resumo da IA (Placeholder - futuramente puxar de module_ia)
    resumo_ia = f"Ativo monitorado do setor {indicadores.get('setor', 'Geral')}. Focado na geração de valor no mercado brasileiro."

    # 3. Montar a tela exata da sua arquitetura
    # O [\u200c] é o link invisível para renderizar a logo no topo
    link_invisivel = f"[\u200c]({url_logo})" if url_logo else ""

    # Formatação condicional baseada no tipo de ativo
    if is_fii:
        texto = (
            f"{link_invisivel}{icone}: **{ticker}**\n"
            f"📝 **Resumo:** _{resumo_ia}_\n\n"
            f"💰 **Preço:** R$ {indicadores.get('preco', 'N/A')}\n"
            f"💸 **Dividend Yield:** {indicadores.get('dy', 'N/A')}\n"
            f"⚖️ **P/VP:** {indicadores.get('pvp', 'N/A')}\n"
            f"💵 **VPA:** {indicadores.get('vpa', 'N/A')}"
        )
    else:
        texto = (
            f"{link_invisivel}{icone}: **{ticker}**\n"
            f"📝 **Resumo:** _{resumo_ia}_\n\n"
            f"💰 **Preço:** R$ {indicadores.get('preco', 'N/A')}\n"
            f"💸 **Dividend Yield:** {indicadores.get('dy', 'N/A')}\n"
            f"📊 **P/L:** {indicadores.get('pl', 'N/A')} | ⚖️ **P/VP:** {indicadores.get('pvp', 'N/A')}\n"
            f"📈 **ROE:** {indicadores.get('roe', 'N/A')}"
        )

    # 4. Criar os Botões (Submenus)
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📎 Dados Importantes", callback_data=f"dados_{ticker}_{tipo}"),
        InlineKeyboardButton("📑 Documentos", callback_data=f"docs_{ticker}_{tipo}")
    )
    markup.add(InlineKeyboardButton("⚠️ Análise de IA", callback_data=f"ia_{ticker}_{tipo}"))
    markup.add(InlineKeyboardButton(f"🔙 Voltar aos {icone.split()[1]}s", callback_data=voltar_cmd))

    # 5. Enviar ou Editar
    if message_id:
        bot.edit_message_text(texto, chat_id, message_id, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=False)
    else:
        bot.send_message(chat_id, texto, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=False)

def converter_numero(valor_string):
    """Limpa textos como 'R$ 1.050,50' ou '8,5%' da planilha e transforma em número puro"""
    try:
        texto = str(valor_string).replace('R$', '').replace('%', '').strip()
        if not texto or texto == '-': return 0.0
        if ',' in texto and '.' in texto:
            texto = texto.replace('.', '')
        texto = texto.replace(',', '.')
        return float(texto)
    except:
        return 0.0

def buscar_oportunidades(tipo):
    """Vasculha a planilha usando regras fixas hardcoded"""
    is_fii = (tipo == 'fii')
    nome_aba = "BD_FIIs" if is_fii else "BD_Acoes"

    # 🚨 REGRAS FIXAS DEFINIDAS AQUI 🚨
    FILTROS_FIXOS = {
        "fii": {"pvp_min": 0.50, "pvp_max": 1.15, "dy_min": 0.08},
        "acao": {"pl_min": 2.0, "pl_max": 15.0, "pvp_min": 0.50, "pvp_max": 2.50, "dy_min": 0.06, "roe_min": 0.10}
    }
    
    filtro_atual = FILTROS_FIXOS[tipo]

    try:
        planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
        aba = planilha.worksheet(nome_aba)
        matriz = aba.get_all_values()

        oportunidades = []

        for linha in matriz[1:]:
            try:
                ticker = linha[0].strip()
                if not ticker: continue

                if is_fii:
                    pvp = converter_numero(linha[5])
                    dy = converter_numero(linha[6])

                    dy_min = filtro_atual['dy_min']
                    if dy_min < 1 and dy >= 1: dy_min *= 100 

                    if (filtro_atual['pvp_min'] <= pvp <= filtro_atual['pvp_max']) and (dy >= dy_min):
                        oportunidades.append(ticker)
                else:
                    dy = converter_numero(linha[3])
                    pl = converter_numero(linha[5])
                    pvp = converter_numero(linha[6])
                    roe = converter_numero(linha[19])

                    dy_min = filtro_atual['dy_min']
                    if dy_min < 1 and dy >= 1: dy_min *= 100
                    roe_min = filtro_atual['roe_min']
                    if roe_min < 1 and roe >= 1: roe_min *= 100

                    if (filtro_atual['pl_min'] <= pl <= filtro_atual['pl_max']) and \
                       (filtro_atual['pvp_min'] <= pvp <= filtro_atual['pvp_max']) and \
                       (dy >= dy_min) and (roe >= roe_min):
                        oportunidades.append(ticker)

            except IndexError:
                pass 

        return oportunidades
    except Exception as e:
        print(f"Erro no filtro de oportunidades: {e}")
        return []

# ==========================================
# 🧭 MENUS DE NAVEGAÇÃO E INTERFACE (UI)
# ==========================================
# Ponto de partida do Bot
@bot.message_handler(commands=['menu', 'start'])
def enviar_menu(message):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("🏢 FIIs (Imobiliários)", callback_data="menu_fiis"),
               InlineKeyboardButton("📈 Ações (Empresas)", callback_data="menu_acoes"))
    markup.row(InlineKeyboardButton("🌍 Visão Macro & Notícias", callback_data="menu_macro"))
    markup.row(InlineKeyboardButton("ℹ️ Ajuda / Sobre", callback_data="menu_ajuda"))
    bot.send_message(message.chat.id, "🤖 *Terminal Institucional* 🤖\nSelecione o módulo de análise abaixo:", reply_markup=markup, parse_mode="Markdown")

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
