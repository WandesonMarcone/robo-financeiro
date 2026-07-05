import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import gspread
import os
import json
import traceback
from flask import Flask, request

# --- CONFIGURAÇÕES ---
TELEGRAM_BOT_TOKEN = "7777811765:AAEk3XQibBBYSFKRfQLzOWs_KpGOcPFR274"
SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk'

# ⚠️ O SEGREDO ESTÁ AQUI: threaded=False obriga o bot a mostrar os erros na tela!
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN, threaded=False)
app = Flask(__name__)

def conectar_planilha():
    google_creds = os.environ.get('GOOGLE_CREDS')
    if google_creds:
        creds_dict = json.loads(google_creds)
        gc = gspread.service_account_from_dict(creds_dict)
    else:
        gc = gspread.service_account(filename='credenciais.json')
    return gc.open_by_url(SPREADSHEET_URL)

# --- MENU PRINCIPAL ---
@bot.message_handler(commands=['start', 'menu'])
def enviar_menu(message):
    print("▶️ Função enviar_menu ACIONADA pelo código!") # Rastreador
    try:
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("💼 Minha Carteira", callback_data="menu_carteira"))
        markup.row(InlineKeyboardButton("🏢 FIIs", callback_data="menu_fiis"),
                   InlineKeyboardButton("📈 Ações", callback_data="menu_acoes"))
        markup.row(InlineKeyboardButton("🌍 Macroeconomia", callback_data="menu_macro"))
        
        bot.send_message(message.chat.id, "🤖 *Terminal Financeiro* 🤖\nSelecione um módulo para consultar:", reply_markup=markup, parse_mode="Markdown")
        print("✅ Menu enviado para o Telegram com sucesso!")
    except Exception as e:
        print(f"❌ ERRO AO ENVIAR MENU: {e}")
        traceback.print_exc()

# --- NAVEGAÇÃO DE FIIs ---
@bot.callback_query_handler(func=lambda call: call.data == "menu_fiis")
def submenu_fiis(call):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("🧱 Tijolo", callback_data="fii_tipo_Tijolo"),
               InlineKeyboardButton("📄 Papel", callback_data="fii_tipo_Papel"))
    markup.row(InlineKeyboardButton("🧩 Híbrido / FOF", callback_data="fii_tipo_Híbrido"))
    markup.row(InlineKeyboardButton("🔙 Voltar", callback_data="voltar_menu"))
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="🏢 *Selecione a categoria de FIIs:*", reply_markup=markup, parse_mode="Markdown")

# --- LISTAR ATIVOS ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("fii_tipo_"))
def listar_fiis(call):
    tipo_escolhido = call.data.split("_")[2]
    bot.answer_callback_query(call.id, f"Buscando fundos de {tipo_escolhido}...")
    try:
        planilha = conectar_planilha()
        aba_fiis = planilha.worksheet("BD_FIIs")
        dados = aba_fiis.get_all_values()
        
        markup = InlineKeyboardMarkup()
        encontrou = False
        
        for row in dados[1:]:
            if len(row) > 2 and tipo_escolhido in str(row[1]):
                ticker = row[0].strip()
                markup.row(InlineKeyboardButton(f"📊 {ticker}", callback_data=f"detalhe_{ticker}"))
                encontrou = True
                
        markup.row(InlineKeyboardButton("🔙 Voltar", callback_data="menu_fiis"))
        texto = f"FIIs da categoria *{tipo_escolhido}* na sua carteira:" if encontrou else f"Nenhum FII de *{tipo_escolhido}* encontrado na planilha."
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=texto, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Erro ao ler planilha: {e}")

# --- EXIBIR DADOS DO ATIVO ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("detalhe_"))
def detalhe_ativo(call):
    ticker = call.data.split("_")[1]
    bot.answer_callback_query(call.id, f"Carregando {ticker}...")
    try:
        planilha = conectar_planilha()
        aba_fiis = planilha.worksheet("BD_FIIs")
        dados = aba_fiis.get_all_values()
        
        linha_ativo = next((row for row in dados if row[0] == ticker), None)
        
        if linha_ativo:
            tipo = linha_ativo[1]
            setor = linha_ativo[2]
            preco = linha_ativo[3]
            pvp = linha_ativo[5]
            dy = str(float(linha_ativo[6]) * 100) + "%" if linha_ativo[6].replace('.', '').isnumeric() else linha_ativo[6]
            vacancia = str(float(linha_ativo[7]) * 100) + "%" if linha_ativo[7].replace('.', '').isnumeric() else linha_ativo[7]
            
            texto = f"📌 *{ticker}* ({tipo} - {setor})\n\n💵 *Preço:* R$ {preco}\n⚖️ *P/VP:* {pvp}\n💰 *DY (12m):* {dy}\n🏢 *Vacância:* {vacancia}\n\n_As análises de Fatos Relevantes e Valuation estarão disponíveis nas próximas etapas._"
            
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("📰 Fatos Relevantes", callback_data=f"fatos_{ticker}"), InlineKeyboardButton("🧮 Valuation", callback_data=f"val_{ticker}"))
            markup.row(InlineKeyboardButton("🔙 Voltar", callback_data="menu_fiis"))
            
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=texto, reply_markup=markup, parse_mode="Markdown")
        else:
            bot.send_message(call.message.chat.id, f"Dados de {ticker} não encontrados.")
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Erro: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "voltar_menu")
def voltar_menu_principal(call):
    enviar_menu(call.message)

# --- NAVEGAÇÃO DE AÇÕES ---
@bot.callback_query_handler(func=lambda call: call.data == "menu_acoes")
def submenu_acoes(call):
    bot.answer_callback_query(call.id, "Carregando Ações...")
    try:
        planilha = conectar_planilha()
        aba_acoes = planilha.worksheet("BD_Acoes")
        dados = aba_acoes.get_all_values()
        
        markup = InlineKeyboardMarkup()
        encontrou = False
        
        # Pula o cabeçalho e cria um botão para cada ação da planilha
        for row in dados[1:]:
            if row and row[0].strip():
                ticker = row[0].strip()
                markup.row(InlineKeyboardButton(f"📈 {ticker}", callback_data=f"acao_{ticker}"))
                encontrou = True
                
        markup.row(InlineKeyboardButton("🔙 Voltar", callback_data="voltar_menu"))
        
        texto = "📈 *Ações na sua Carteira:*" if encontrou else "Nenhuma ação encontrada na planilha."
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=texto, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Erro ao ler planilha de Ações: {e}")

# --- DETALHE DA AÇÃO (Com placeholder para Valuation/Payout de 5 anos) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("acao_"))
def detalhe_acao(call):
    ticker = call.data.split("_")[1]
    bot.answer_callback_query(call.id, f"Analisando {ticker}...")
    
    # Aqui, futuramente, entrará o yfinance para calcular o Payout e Lucro de 5 anos ao vivo
    texto = f"📌 *{ticker}*\n\n"
    texto += "⏳ _Calculando histórico de 5 anos e Payout dinâmico... (Módulo em construção)_\n"
    
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("📰 Resumo IA (Fatos)", callback_data=f"ia_{ticker}"))
    markup.row(InlineKeyboardButton("🧮 Valuation Projetivo", callback_data=f"val_{ticker}"))
    markup.row(InlineKeyboardButton("🔙 Voltar", callback_data="menu_acoes"))
    
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=texto, reply_markup=markup, parse_mode="Markdown")

# --- O CÉREBRO DA IA EM AÇÃO (Fatos Relevantes) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("fatos_") or call.data.startswith("ia_"))
def chamar_ia(call):
    ticker = call.data.split("_")[1]
    # O bot avisa que está "Digitando..." para você saber que a IA está pensando
    bot.answer_callback_query(call.id, f"IA lendo dados de {ticker}... Isso leva uns 3 segundos.")
    
    # Chama o nosso novo módulo
    analise = module_ia.analisar_fatos_com_ia(ticker)
    
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("🔙 Voltar", callback_data="voltar_menu"))
    
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"🧠 *Análise Gemini - {ticker}*\n\n{analise}", reply_markup=markup, parse_mode="Markdown")

# --- MENU MINHA CARTEIRA ---
@bot.callback_query_handler(func=lambda call: call.data == "menu_carteira")
def submenu_carteira(call):
    bot.answer_callback_query(call.id, "Buscando consolidação...")
    
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("🔙 Voltar", callback_data="voltar_menu"))
    
    texto = "💼 *Minha Carteira*\n\n_Módulo de consolidação em construção. Requer a aba 'BD_Carteira' com histórico de aportes para cálculo de rentabilidade real._"
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=texto, reply_markup=markup, parse_mode="Markdown")

# ==========================================
# MOTOR DO SERVIDOR WEB (FLASK) 
# ==========================================
@app.route(f'/{TELEGRAM_BOT_TOKEN}', methods=['POST'])
def webhook():
    try:
        json_string = request.get_data().decode('utf-8')
        print(f"📩 SINAL RECEBIDO: {json_string}") 
        
        update = telebot.types.Update.de_json(json_string)
        
        # O threaded=False fará o erro explodir aqui caso exista
        bot.process_new_updates([update])
        
        return "OK", 200
    except Exception as e:
        print(f"❌ ERRO FATAL NO WEBHOOK: {e}")
        traceback.print_exc()
        return "Erro", 500