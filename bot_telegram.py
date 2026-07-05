import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import gspread
import os
import json
import traceback
import yfinance as yf
from datetime import datetime
from flask import Flask, request

# --- IMPORTAÇÃO DOS SEUS CÉREBROS ---
import module_ia  # 💡 Corrigido: Agora a IA não vai dar erro de NameError

# --- CONFIGURAÇÕES ---
TELEGRAM_BOT_TOKEN = "7777811765:AAEk3XQibBBYSFKRfQLzOWs_KpGOcPFR274"
SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk'

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

# --- 1. MENU PRINCIPAL ---
@bot.message_handler(commands=['start', 'menu'])
def enviar_menu(message):
    try:
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("💼 Minha Carteira", callback_data="menu_carteira"))
        markup.row(InlineKeyboardButton("🏢 FIIs", callback_data="menu_fiis"),
                   InlineKeyboardButton("📈 Ações", callback_data="menu_acoes"))
        markup.row(InlineKeyboardButton("🌍 Macroeconomia", callback_data="menu_macro"))

        bot.send_message(message.chat.id, "🤖 *Terminal Financeiro* 🤖\nSelecione um módulo para consultar:", reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        traceback.print_exc()

# --- 2. SUBMENU FIIs ---
@bot.callback_query_handler(func=lambda call: call.data == "menu_fiis")
def submenu_fiis(call):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("🧱 Tijolo", callback_data="fii_tipo_Tijolo"),
               InlineKeyboardButton("📄 Papel", callback_data="fii_tipo_Papel"))
    markup.row(InlineKeyboardButton("🧩 Híbrido / FOF", callback_data="fii_tipo_Híbrido"))
    markup.row(InlineKeyboardButton("🔙 Voltar", callback_data="voltar_menu"))
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="🏢 *Selecione a categoria de FIIs:*", reply_markup=markup, parse_mode="Markdown")

# --- 3. LISTAR FIIs DA PLANILHA ---
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

# --- 4. EXIBIR DADOS DO FII ---
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
            
            # Formatação defensiva caso a planilha ainda não tenha sido atualizada pelo main.py
            dy = f"{float(linha_ativo[6])*100:.2f}%" if (len(linha_ativo) > 6 and linha_ativo[6].replace('.', '').isnumeric()) else "Aguardando atualização..."
            vacancia = f"{float(linha_ativo[7])*100:.2f}%" if (len(linha_ativo) > 7 and linha_ativo[7].replace('.', '').isnumeric()) else "0.00%"

            texto = f"📌 *{ticker}* ({tipo} - {setor})\n\n💵 *Preço Atual:* R$ {preco}\n⚖️ *P/VP:* {pvp}\n💰 *DY (12m):* {dy}\n🏢 *Vacância Média:* {vacancia}\n\n_Dados extraídos diretamente da infraestrutura do seu Banco de Dados._"

            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("📰 Resumo IA (Fatos)", callback_data=f"ia_{ticker}"))
            markup.row(InlineKeyboardButton("🔙 Voltar", callback_data="menu_fiis"))

            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=texto, reply_markup=markup, parse_mode="Markdown")
        else:
            bot.send_message(call.message.chat.id, f"Dados de {ticker} não encontrados.")
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Erro: {e}")

# --- 5. NAVEGAÇÃO DE AÇÕES ---
@bot.callback_query_handler(func=lambda call: call.data == "menu_acoes")
def submenu_acoes(call):
    bot.answer_callback_query(call.id, "Carregando Ações...")
    try:
        planilha = conectar_planilha()
        aba_acoes = planilha.worksheet("BD_Acoes")
        dados = aba_acoes.get_all_values()

        markup = InlineKeyboardMarkup()
        encontrou = False

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

# --- 6. VISUALIZAR DETALHE DA AÇÃO (Cálculo em Tempo Real de 5 anos via yfinance) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("acao_"))
def detalhe_acao(call):
    ticker = call.data.split("_")[1]
    bot.answer_callback_query(call.id, f"Analisando histórico de {ticker}...")
    try:
        # Busca dados ao vivo da B3 via yfinance
        asset = yf.Ticker(f"{ticker}.SA")
        info = asset.info
        
        preco_atual = info.get('currentPrice') or info.get('regularMarketPrice') or 0
        lpa = info.get('trailingEps') or 1.0 # Evita divisão por zero
        
        # Coleta de dividendos dos últimos 5 anos
        historico_divs = asset.dividends
        ano_atual = datetime.now().year
        divs_ultimos_5_anos = 0
        
        if not historico_divs.empty:
            divs_filtrados = historico_divs[historico_divs.index.year >= (ano_atual - 5)]
            divs_ultimos_5_anos = divs_filtrados.sum() / 5 if not divs_filtrados.empty else 0

        payout_sugerido = (divs_ultimos_5_anos / lpa) * 100 if lpa > 0 else 50.0
        if payout_sugerido > 100 or payout_sugerido < 0: payout_sugerido = 50.0 # Trava de segurança para distorções

        texto = f"📌 *ANÁLISE ESTRUTURAL: {ticker}*\n\n"
        texto += f"💵 *Preço de Balcão:* R$ {preco_atual:.2f}\n"
        texto += f"📈 *Lucro Por Ação (LPA Atual):* R$ {lpa:.2f}\n"
        texto += f"📊 *Média de Dividendos (Últimos 5 anos):* R$ {divs_ultimos_5_anos:.2f}/ano\n"
        texto += f"🎯 *Payout Histórico Sugerido:* {payout_sugerido:.1f}%\n\n"
        texto += "_O motor matemático calculou estes dados diretamente do balcão da B3 para evitar atrasos._"

        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("📰 Resumo IA (Fatos)", callback_data=f"ia_{ticker}"))
        markup.row(InlineKeyboardButton("🧮 Valuation de Bazin", callback_data=f"val_{ticker}_{payout_sugerido:.1f}"))
        markup.row(InlineKeyboardButton("🔙 Voltar", callback_data="menu_acoes"))

        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=texto, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Erro ao processar dados de {ticker}: {e}")

# --- 7. MOTOR MATEMÁTICO: VALUATION DE BAZIN INTERATIVO (Muda o Payout nos botões!) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("val_"))
def valuation_bazin(call):
    partes = call.data.split("_")
    ticker = partes[1]
    payout_simulado = float(partes[2])
    
    bot.answer_callback_query(call.id, f"Simulando Payout em {payout_simulado:.1f}%...")
    
    try:
        asset = yf.Ticker(f"{ticker}.SA")
        lpa = asset.info.get('trailingEps') or 1.0
        preco_atual = asset.info.get('currentPrice') or asset.info.get('regularMarketPrice') or 0
        
        # Regra de Três Projetiva: Novo dividendo com base no Payout escolhido
        dividendo_projetado = lpa * (payout_simulado / 100)
        
        # Fórmula de Bazin: Preço Justo = Dividendo / Taxa Mínima de Expectativa (6%)
        preco_justo_bazin = dividendo_projetado / 0.06
        margem_seguranca = ((preco_justo_bazin - preco_atual) / preco_justo_bazin) * 100 if preco_justo_bazin > 0 else 0

        texto = f"🧮 *VALUATION PROJETIVO (MÉTODO BAZIN): {ticker}*\n\n"
        texto += f"📊 *Payout Simulado:* {payout_simulado:.1f}%\n"
        texto += f"💸 *Dividendo Projetado:* R$ {dividendo_projetado:.2f}\n"
        texto += f"🏛️ *Taxa de Desconto Estipulada:* 6.0% (Padrão Bazin)\n\n"
        texto += f"💎 *PREÇO JUSTO CALCULADO:* R$ {preco_justo_bazin:.2f}\n"
        texto += f"💵 *Preço Atual de Mercado:* R$ {preco_atual:.2f}\n"
        
        if margem_seguranca > 0:
            texto += f"🟢 *Margem de Segurança:* +{margem_seguranca:.1f}% (Ativo com Desconto)"
        else:
            texto += f"🔴 *Margem de Segurança:* {margem_seguranca:.1f}% (Ativo acima do preço justo)"

        # Botões de simulação instantânea! Refazem a conta sem recarregar o bot
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("📊 Simular 40%", callback_data=f"val_{ticker}_40.0"),
                   InlineKeyboardButton("📊 Simular 60%", callback_data=f"val_{ticker}_60.0"))
        markup.row(InlineKeyboardButton("📊 Simular 80%", callback_data=f"val_{ticker}_80.0"))
        markup.row(InlineKeyboardButton("🔙 Voltar para a Ação", callback_data=f"acao_{ticker}"))

        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=texto, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Erro no cálculo de Valuation: {e}")

# --- 8. CHAMA O CÉREBRO DA IA (Fatos Relevantes) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("ia_"))
def chamar_ia(call):
    ticker = call.data.split("_")[1]
    bot.answer_callback_query(call.id, f"O Gemini está analisando {ticker}...")
    
    analise = module_ia.analisar_fatos_com_ia(ticker)
    
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="voltar_menu"))
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"🧠 *Análise Gemini - {ticker}*\n\n{analise}", reply_markup=markup, parse_mode="Markdown")

# --- 9. MENU MINHA CARTEIRA ---
@bot.callback_query_handler(func=lambda call: call.data == "menu_carteira")
def submenu_carteira(call):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("🔙 Voltar", callback_data="voltar_menu"))
    texto = "💼 *Minha Carteira*\n\n_Módulo de consolidação em construção. Próximo passo: integrar a aba 'BD_Carteira' para calcular o preço médio e rendimento passivo mensal real._"
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=texto, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "voltar_menu")
def voltar_menu_principal(call):
    enviar_menu(call.message)

# ==========================================
# MOTOR DO SERVIDOR WEB (FLASK) 
# ==========================================
@app.route(f'/{TELEGRAM_BOT_TOKEN}', methods=['POST'])
def webhook():
    try:
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "OK", 200
    except Exception as e:
        print(f"❌ ERRO FATAL NO WEBHOOK: {e}")
        traceback.print_exc()
        return "Erro", 500