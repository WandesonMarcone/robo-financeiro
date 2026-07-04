import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import gspread
import os
import json

# --- CONFIGURAÇÕES ---
TELEGRAM_BOT_TOKEN = "7777811765:AAEk3XQibBBYSFKRfQLzOWs_KpGOcPFR274"
SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk'

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

def conectar_planilha():
    """Conecta ao Sheets lendo os Secrets da Nuvem ou arquivo local."""
    google_creds = os.environ.get('GOOGLE_CREDS')
    
    if google_creds:
        # Modo Nuvem (Quando estiver no Render ou GitHub)
        creds_dict = json.loads(google_creds)
        gc = gspread.service_account_from_dict(creds_dict)
    else:
        # Modo Computador Local (Caso você teste no seu PC)
        gc = gspread.service_account(filename='credenciais.json')
        
    return gc.open_by_url(SPREADSHEET_URL)

# --- 1. MENU PRINCIPAL ---
@bot.message_handler(commands=['start', 'menu'])
def enviar_menu(message):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("💼 Minha Carteira", callback_data="menu_carteira"))
    markup.row(InlineKeyboardButton("🏢 FIIs", callback_data="menu_fiis"),
               InlineKeyboardButton("📈 Ações", callback_data="menu_acoes"))
    markup.row(InlineKeyboardButton("🌍 Macroeconomia", callback_data="menu_macro"))
    
    bot.send_message(message.chat.id, "🤖 *Terminal Financeiro* 🤖\nSelecione um módulo para consultar:", reply_markup=markup, parse_mode="Markdown")

# --- 2. NAVEGAÇÃO DE FIIs ---
@bot.callback_query_handler(func=lambda call: call.data == "menu_fiis")
def submenu_fiis(call):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("🧱 Tijolo", callback_data="fii_tipo_Tijolo"),
               InlineKeyboardButton("📄 Papel", callback_data="fii_tipo_Papel"))
    markup.row(InlineKeyboardButton("🧩 Híbrido / FOF", callback_data="fii_tipo_Híbrido"))
    markup.row(InlineKeyboardButton("🔙 Voltar", callback_data="voltar_menu"))
    
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                          text="🏢 *Selecione a categoria de FIIs:*", reply_markup=markup, parse_mode="Markdown")

# --- 3. LISTAR ATIVOS DA CATEGORIA ---
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
        
        # Filtra a planilha procurando FIIs que batem com o tipo escolhido
        for row in dados[1:]:
            if len(row) > 2 and tipo_escolhido in str(row[1]):
                ticker = row[0].strip()
                markup.row(InlineKeyboardButton(f"📊 {ticker}", callback_data=f"detalhe_{ticker}"))
                encontrou = True
                
        markup.row(InlineKeyboardButton("🔙 Voltar", callback_data="menu_fiis"))
        
        texto = f"FIIs da categoria *{tipo_escolhido}* na sua carteira:" if encontrou else f"Nenhum FII de *{tipo_escolhido}* encontrado na planilha."
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                              text=texto, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Erro ao ler planilha: {e}")

# --- 4. EXIBIR DADOS DO ATIVO ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("detalhe_"))
def detalhe_ativo(call):
    ticker = call.data.split("_")[1]
    bot.answer_callback_query(call.id, f"Carregando {ticker}...")
    
    try:
        planilha = conectar_planilha()
        aba_fiis = planilha.worksheet("BD_FIIs")
        dados = aba_fiis.get_all_values()
        
        # Procura a linha exata do Ticker
        linha_ativo = next((row for row in dados if row[0] == ticker), None)
        
        if linha_ativo:
            tipo = linha_ativo[1]
            setor = linha_ativo[2]
            preco = linha_ativo[3]
            pvp = linha_ativo[5]
            dy = str(float(linha_ativo[6]) * 100) + "%" if linha_ativo[6].replace('.', '').isnumeric() else linha_ativo[6]
            vacancia = str(float(linha_ativo[7]) * 100) + "%" if linha_ativo[7].replace('.', '').isnumeric() else linha_ativo[7]
            
            texto = f"📌 *{ticker}* ({tipo} - {setor})\n\n"
            texto += f"💵 *Preço:* R$ {preco}\n"
            texto += f"⚖️ *P/VP:* {pvp}\n"
            texto += f"💰 *DY (12m):* {dy}\n"
            texto += f"🏢 *Vacância:* {vacancia}\n\n"
            texto += "_As análises de Fatos Relevantes e Valuation estarão disponíveis nas próximas etapas._"
            
            # Botões de Ação Futuros (Ainda sem função, apenas visuais)
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("📰 Fatos Relevantes", callback_data=f"fatos_{ticker}"),
                       InlineKeyboardButton("🧮 Valuation", callback_data=f"val_{ticker}"))
            markup.row(InlineKeyboardButton("🔙 Voltar", callback_data="menu_fiis"))
            
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                                  text=texto, reply_markup=markup, parse_mode="Markdown")
        else:
            bot.send_message(call.message.chat.id, f"Dados de {ticker} não encontrados.")
            
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Erro: {e}")

# --- BOTÕES DE VOLTAR ---
@bot.callback_query_handler(func=lambda call: call.data == "voltar_menu")
def voltar_menu_principal(call):
    enviar_menu(call.message)

# Mantém o bot acordado escutando o Telegram
print("🤖 Bot interativo iniciado! Aguardando comandos no Telegram...")
bot.polling()