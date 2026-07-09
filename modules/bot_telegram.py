import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import threading
import traceback
from flask import Flask, request
import config
from modules.utils import conectar_gspread

# Importa as suas pontes de dados externas
import module_ia
import module_cvm_bridge
import module_macro

bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN, threaded=False)
app = Flask(__name__)

# ==========================================
# COMANDO: ADICIONAR ATIVO (/adicionar)
# ==========================================
@bot.message_handler(commands=['adicionar'])
def comando_adicionar(message):
    try:
        # Pega o que o utilizador digitou após o comando (ex: /adicionar BBAS3)
        partes = message.text.split()
        if len(partes) < 2:
            bot.reply_to(message, "⚠️ Uso correto: `/adicionar TICKER` (ex: /adicionar BBAS3)", parse_mode="Markdown")
            return

        ticker = partes[1].strip().upper()
        bot.reply_to(message, f"A procurar {ticker} e a injetar no Banco de Dados...")

        planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
        
        # Lógica simples: Se termina em 11 (na maioria dos casos), é FII. Senão, é Ação.
        is_fii = True if ticker.endswith('11') else False
        nome_aba = "BD_FIIs" if is_fii else "BD_Acoes"
        aba = planilha.worksheet(nome_aba)

        # Adiciona o Ticker na primeira coluna da próxima linha vazia
        dados = aba.get_all_values()
        proxima_linha = len(dados) + 1
        aba.update(f'A{proxima_linha}', [[ticker]])

        bot.send_message(message.chat.id, f"✅ *{ticker}* adicionado com sucesso na aba `{nome_aba}`!\nEle será processado na próxima auditoria do sistema.", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Erro ao adicionar ativo: {e}")

# ==========================================
# MENUS DE NAVEGAÇÃO
# ==========================================
@bot.message_handler(commands=['start', 'menu'])
def enviar_menu(message):
    try:
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("🏢 FIIs (Imobiliários)", callback_data="menu_fiis"),
                   InlineKeyboardButton("📈 Ações (Empresas)", callback_data="menu_acoes"))
        markup.row(InlineKeyboardButton("🌍 Visão Macro & Notícias", callback_data="menu_macro"))

        bot.send_message(message.chat.id, "🤖 *Terminal Institucional* 🤖\nSelecione o módulo de análise:", reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        traceback.print_exc()

@bot.callback_query_handler(func=lambda call: call.data == "menu_acoes")
def submenu_acoes(call):
    bot.answer_callback_query(call.id, "A carregar Carteira de Ações...")
    try:
        aba_acoes = conectar_gspread().open_by_url(config.SPREADSHEET_URL).worksheet("BD_Acoes")
        dados = aba_acoes.get_all_values()

        markup = InlineKeyboardMarkup()
        encontrou = False

        # Lista todas as ações encontradas na planilha
        for row in dados[1:]:
            if row and row[0].strip() and not row[0].replace(',', '').isnumeric():
                ticker = row[0].strip().upper()
                markup.row(InlineKeyboardButton(f"📈 {ticker}", callback_data=f"acao_{ticker}"))
                encontrou = True

        markup.row(InlineKeyboardButton("🔙 Voltar", callback_data="voltar_menu"))
        texto = "📈 *Selecione uma Ação para Raio-X e Documentos:*" if encontrou else "Nenhuma ação encontrada."
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=texto, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        print(f"Erro Ações: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "menu_fiis")
def submenu_fiis(call):
    bot.answer_callback_query(call.id, "A carregar Carteira de FIIs...")
    try:
        aba_fiis = conectar_gspread().open_by_url(config.SPREADSHEET_URL).worksheet("BD_FIIs")
        dados = aba_fiis.get_all_values()

        markup = InlineKeyboardMarkup()
        encontrou = False

        for row in dados[1:]:
            if row and row[0].strip() and not row[0].replace(',', '').isnumeric():
                ticker = row[0].strip().upper()
                markup.row(InlineKeyboardButton(f"🏢 {ticker}", callback_data=f"fii_{ticker}"))
                encontrou = True

        markup.row(InlineKeyboardButton("🔙 Voltar", callback_data="voltar_menu"))
        texto = "🏢 *Selecione um FII para Raio-X e Documentos:*" if encontrou else "Nenhum FII encontrado."
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=texto, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        print(f"Erro FIIs: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "voltar_menu")
def voltar_menu_principal(call):
    enviar_menu(call.message)

# ==========================================
# PERFIL DO ATIVO E PONTES PARA A CVM/B3
# ==========================================
@bot.callback_query_handler(func=lambda call: call.data.startswith("acao_") or call.data.startswith("fii_"))
def detalhe_ativo(call):
    partes = call.data.split("_")
    tipo = partes[0]
    ticker = partes[1]
    
    bot.answer_callback_query(call.id, f"A abrir terminal para {ticker}...")
    
    markup = InlineKeyboardMarkup()
    
    if tipo == "acao":
        # Botões de Documentos para Ações (CVM/Yahoo)
        markup.row(InlineKeyboardButton("📊 Resultados 1º Tri (ITR)", callback_data=f"doc_trimestre_{ticker}"))
        markup.row(InlineKeyboardButton("🚨 Fatos Relevantes", callback_data=f"doc_fato_{ticker}_acao"))
        markup.row(InlineKeyboardButton("🧠 Avaliação IA (Geral)", callback_data=f"ia_{ticker}"))
        markup.row(InlineKeyboardButton("🔙 Voltar para Ações", callback_data="menu_acoes"))
        texto = f"📌 *Painel de Controle: {ticker}*\n\nAqui você extrai os documentos oficiais e balanços direto das fontes regulatórias."
    else:
        # Botões de Documentos para FIIs (FundosNet/B3)
        markup.row(InlineKeyboardButton("📑 Relatório Gerencial", callback_data=f"doc_gerencial_{ticker}"))
        markup.row(InlineKeyboardButton("🚨 Fatos Relevantes", callback_data=f"doc_fato_{ticker}_fii"))
        markup.row(InlineKeyboardButton("🧠 Resumo IA (Geral)", callback_data=f"ia_{ticker}"))
        markup.row(InlineKeyboardButton("🔙 Voltar para FIIs", callback_data="menu_fiis"))
        texto = f"📌 *Painel de Controle: {ticker}*\n\nAcesse relatórios gerenciais e comunicados ao mercado diretamente do FundosNet."

    try:
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=texto, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        if "message is not modified" not in str(e): print(e)

# ==========================================
# CHAMADAS DE DOCUMENTOS (A PONTE COM A CVM)
# ==========================================
@bot.callback_query_handler(func=lambda call: call.data.startswith("doc_fato_"))
def relatorio_fato_relevante(call):
    try:
        dados = call.data.split("_")
        ticker = dados[2]
        tipo_ativo = dados[3]

        bot.answer_callback_query(call.id, f"A ler Fatos Relevantes para {ticker}...")
        is_fii = True if tipo_ativo == 'fii' else False

        # Chama a nossa ponte CVM que escrevemos no module_cvm_bridge.py
        resumo = module_cvm_bridge.buscar_fatos_relevantes(ticker, is_fii)

        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("🔙 Voltar", callback_data=f"acao_{ticker}" if not is_fii else f"fii_{ticker}"))

        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=resumo, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        if "message is not modified" not in str(e): print(f"❌ Erro Fato Relevante: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("doc_gerencial_"))
def relatorio_gerencial(call):
    try:
        ticker = call.data.split("_")[2]
        bot.answer_callback_query(call.id, f"A extrair relatórios de {ticker} da B3...")

        resumo = module_cvm_bridge.buscar_relatorios_gerenciais(ticker)

        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("🔙 Voltar", callback_data=f"fii_{ticker}"))
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=resumo, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        if "message is not modified" not in str(e): print(e)

@bot.callback_query_handler(func=lambda call: call.data.startswith("doc_trimestre_"))
def relatorio_trimestral(call):
    try:
        ticker = call.data.split("_")[2]
        bot.answer_callback_query(call.id, f"A baixar balanço ITR de {ticker}...")

        resumo = module_cvm_bridge.buscar_resultados_trimestrais(ticker)

        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("🔙 Voltar", callback_data=f"acao_{ticker}"))
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=resumo, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        if "message is not modified" not in str(e): print(e)

@bot.callback_query_handler(func=lambda call: call.data.startswith("ia_"))
def chamar_ia_geral(call):
    try:
        ticker = call.data.split("_")[1]
        bot.answer_callback_query(call.id, f"Gemini a analisar {ticker}...")

        analise = module_ia.analisar_fatos_com_ia(f"Faça um resumo financeiro geral da saúde e dos últimos movimentos do ativo {ticker}")

        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="voltar_menu"))
        
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"🧠 *Análise Gemini - {ticker}*\n\n{analise}", reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        if "message is not modified" not in str(e): print(e)

# ==========================================
# MOTOR DO SERVIDOR WEB WEBHOOK
# ==========================================
@app.route(f'/{config.TELEGRAM_BOT_TOKEN}', methods=['POST'])
def webhook():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)

    def processo_paralelo():
        try:
            bot.process_new_updates([update])
        except Exception as e:
            if "message is not modified" not in str(e):
                print(f"❌ Erro na Thread do Telegram: {e}")

    thread = threading.Thread(target=processo_paralelo)
    thread.start()
    
    return "OK", 200
