import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import threading
import traceback
from flask import Flask, request
import config
from datetime import datetime

from modules.utils import conectar_gspread
from modules import module_cvm
from modules import module_ia
from modules import module_macro

bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN, threaded=False)
app = Flask(__name__)

# ==========================================
# UTILITÁRIO: LOGOS DAS EMPRESAS
# ==========================================
import requests

# ==========================================
# UTILITÁRIO: LOGOS DAS EMPRESAS (VIA GITHUB)
# ==========================================
def obter_url_logo(ticker):
    """
    1º Tenta buscar no GitHub fornecido.
    2º Resolve tickers antigos (ex: GARE11 -> GALG11).
    3º Faz fallback para Clearbit ou Imagem Padrão.
    """
    ticker_upper = ticker.upper()

    # 1. Tradutor de Tickers Desatualizados (Adicione outros se precisar)
    mapa_antigos = {
        "GARE11": "GALG11",
        "RZTR11": "RZTR11", # Exemplo, se precisar mapear outro
        # "NOVO": "ANTIGO"
    }
    
    # Se o ticker estiver no mapa, ele usa o antigo para buscar a foto. Se não, usa o normal.
    ticker_busca = mapa_antigos.get(ticker_upper, ticker_upper)

    # 2. Tenta buscar no Repositório do GitHub
    # ATENÇÃO: Verifique se as imagens estão na raiz ou numa pasta. 
    # Estou a assumir que o formato é .png (se for .jpg, altere abaixo)
    url_github = f"https://raw.githubusercontent.com/WandesonMarcone/icones-bolsabr/main/ícones/{ticker_busca}.png"
    
    try:
        # Faz um request rápido (HEAD) só para ver se a imagem existe sem fazer download dela
        resposta = requests.head(url_github, timeout=3)
        if resposta.status_code == 200:
            return url_github
    except Exception as e:
        print(f"Aviso: Imagem {ticker_busca} não encontrada no GitHub.")

    # 3. Fallback 1: Clearbit (Se não tiver no GitHub, tenta pelo site da gestora)
    dominios = {
        "PETR4": "petrobras.com.br",
        "VALE3": "vale.com",
        "BBAS3": "bb.com.br",
        "ITUB4": "itau.com.br",
        "HGLG11": "cshg.com.br",
        "VISC11": "vincipartners.com",
        "KNRI11": "kinea.com.br",
        "GARE11": "guardiangestora.com.br"
    }
    
    dominio = dominios.get(ticker_upper)
    if dominio:
        return f"https://logo.clearbit.com/{dominio}"
    
    # 4. Fallback 2: Imagem padrão de banco
    return "https://cdn-icons-png.flaticon.com/512/2830/2830284.png"

# ==========================================
# COMANDO: ADICIONAR ATIVO (/adicionar)
# ==========================================
@bot.message_handler(commands=['adicionar'])
def comando_adicionar(message):
    try:
        partes = message.text.split()
        if len(partes) < 2:
            bot.reply_to(message, "⚠️ Uso correto: `/adicionar TICKER` (ex: /adicionar BBAS3)", parse_mode="Markdown")
            return

        ticker = partes[1].strip().upper()
        bot.reply_to(message, f"A procurar {ticker} e a injetar no Banco de Dados...")

        planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
        is_fii = True if ticker.endswith('11') else False
        nome_aba = "BD_FIIs" if is_fii else "BD_Acoes"
        aba = planilha.worksheet(nome_aba)

        dados = aba.get_all_values()
        proxima_linha = len(dados) + 1
        aba.update(f'A{proxima_linha}', [[ticker]])

        bot.send_message(message.chat.id, f"✅ *{ticker}* adicionado com sucesso na aba `{nome_aba}`!", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Erro ao adicionar ativo: {e}")

@bot.message_handler(commands=['cvm'])
def cvm_command(message):
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "⚠️ *Comando incompleto!*\nUse: `/cvm TICKER` (Exemplo: `/cvm GARE11`)", parse_mode="Markdown")
        return

    ticker = args[1].upper()
    bot.reply_to(message, f"🔍 *Consultando bases oficiais (CVM/B3) para {ticker}...*", parse_mode="Markdown")

    try:
        is_fii = ticker.endswith(('11', '13', '14')) 
        resultado = module_cvm.buscar_relatorios_gerenciais(ticker)
        bot.reply_to(message, resultado, parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Erro ao buscar documento para {ticker}: {e}")

@bot.message_handler(commands=['risco'])
def comando_risco(message):
    try:
        ticker = message.text.split()[1].upper()
        bot.reply_to(message, f"📊 Calculando matriz de risco (QuantStats) para {ticker}...")
        resultado = module_cvm.analisar_performance_quantstats(ticker)
        bot.reply_to(message, resultado, parse_mode="Markdown")
    except:
        bot.reply_to(message, "Use: /risco TICKER")

# ==========================================
# MENUS DE NAVEGAÇÃO E LOGS
# ==========================================
@bot.message_handler(commands=['menu'])
def enviar_menu(message):
    """Menu limpo, sem exibir logs."""
    try:
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("🏢 FIIs (Imobiliários)", callback_data="menu_fiis"),
                   InlineKeyboardButton("📈 Ações (Empresas)", callback_data="menu_acoes"))
        markup.row(InlineKeyboardButton("🌍 Visão Macro & Notícias", callback_data="menu_macro"))

        mensagem_final = "🤖 *Terminal Institucional* 🤖\nSelecione o módulo de análise abaixo:"

        bot.send_message(message.chat.id, mensagem_final, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        traceback.print_exc()
        bot.reply_to(message, "❌ Erro ao abrir o menu.")

@bot.message_handler(commands=['logs'])
def mostrar_logs(message):
    """Mostra os logs agrupados pela data."""
    try:
        planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
        aba_logs = planilha.worksheet("BD_Logs")
        linhas = aba_logs.get_all_values()
        
        # Pega as últimas 10 linhas, ignorando o cabeçalho
        ultimas_linhas = linhas[-10:] if len(linhas) > 10 else linhas[1:] 

        # Hoje para filtro básico
        hoje_str = datetime.now().strftime("%d/%m/%Y")
        
        texto_logs = f"📜 *Logs Recentes (Foco em: {hoje_str}):*\n\n"
        
        # O Google Sheets costuma retornar '2026-07-10 14:30:00'
        for linha in ultimas_linhas:
            data_hora = linha[0]
            nivel = linha[1]
            erro_limpo = str(linha[2]).replace('*', '').replace('_', '').replace('[', '(').replace(']', ')')
            
            # Formatação limpa
            texto_logs += f"📅 `{data_hora[:10]}` 🕒 `{data_hora[11:16]}` | {nivel}\n💬 {erro_limpo}\n\n"

        bot.reply_to(message, texto_logs, parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Erro ao ler logs: {e}")

# ==========================================
# PORTEIRO DOS BOTÕES (Callback Handler Único)
# ==========================================
# Removemos os vários decoradores callback_query_handler que estavam a dar conflito
# e centralizamos tudo num único "porteiro".

@bot.callback_query_handler(func=lambda call: True)
def callback_geral(call):
    try:
        dados = call.data
        
        # 1. Menus Principais
        if dados == "voltar_menu":
            # Recria o menu limpo
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("🏢 FIIs (Imobiliários)", callback_data="menu_fiis"),
                       InlineKeyboardButton("📈 Ações (Empresas)", callback_data="menu_acoes"))
            markup.row(InlineKeyboardButton("🌍 Visão Macro & Notícias", callback_data="menu_macro"))
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                                  text="🤖 *Terminal Institucional* 🤖\nSelecione o módulo de análise abaixo:", 
                                  reply_markup=markup, parse_mode="Markdown")
            return
            
        elif dados == "menu_macro":
            bot.answer_callback_query(call.id, "🌍 Coletando dados macroeconômicos oficiais...")
            resultado = module_macro.obter_dados_macro()
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="voltar_menu"))
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=resultado, reply_markup=markup, parse_mode="Markdown")
            return
            
        elif dados == "menu_acoes":
            bot.answer_callback_query(call.id, "A carregar Carteira de Ações...")
            aba_acoes = conectar_gspread().open_by_url(config.SPREADSHEET_URL).worksheet("BD_Acoes")
            dados_planilha = aba_acoes.get_all_values()
            markup = InlineKeyboardMarkup()
            encontrou = False
            for row in dados_planilha[1:]:
                if row and row[0].strip() and not row[0].replace(',', '').isnumeric():
                    ticker = row[0].strip().upper()
                    markup.row(InlineKeyboardButton(f"📈 {ticker}", callback_data=f"acao_{ticker}"))
                    encontrou = True
            markup.row(InlineKeyboardButton("🔙 Voltar", callback_data="voltar_menu"))
            texto = "📈 *Selecione uma Ação para Raio-X e Documentos:*" if encontrou else "Nenhuma ação encontrada."
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=texto, reply_markup=markup, parse_mode="Markdown")
            return
            
        elif dados == "menu_fiis":
            bot.answer_callback_query(call.id, "A carregar Carteira de FIIs...")
            aba_fiis = conectar_gspread().open_by_url(config.SPREADSHEET_URL).worksheet("BD_FIIs")
            dados_planilha = aba_fiis.get_all_values()
            markup = InlineKeyboardMarkup()
            encontrou = False
            for row in dados_planilha[1:]:
                if row and row[0].strip() and not row[0].replace(',', '').isnumeric():
                    ticker = row[0].strip().upper()
                    markup.row(InlineKeyboardButton(f"🏢 {ticker}", callback_data=f"fii_{ticker}"))
                    encontrou = True
            markup.row(InlineKeyboardButton("🔙 Voltar", callback_data="voltar_menu"))
            texto = "🏢 *Selecione um FII para Raio-X e Documentos:*" if encontrou else "Nenhum FII encontrado."
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=texto, reply_markup=markup, parse_mode="Markdown")
            return

        # 2. Perfil do Ativo (Quando clica num Ticker)
        elif dados.startswith("acao_") or dados.startswith("fii_"):
            partes = dados.split("_")
            tipo = partes[0]
            ticker = partes[1]
            bot.answer_callback_query(call.id, f"A abrir terminal para {ticker}...")
            markup = InlineKeyboardMarkup()

            if tipo == "acao":
                markup.row(InlineKeyboardButton("📊 Resultados 1º Tri (ITR)", callback_data=f"doc_trimestre_{ticker}"))
                markup.row(InlineKeyboardButton("🚨 Fatos Relevantes", callback_data=f"doc_fato_{ticker}_acao"))
                markup.row(InlineKeyboardButton("🧠 Avaliação IA (Geral)", callback_data=f"ia_{ticker}"))
                markup.row(InlineKeyboardButton("🔙 Voltar para Ações", callback_data="menu_acoes"))
                texto = f"📌 *Painel de Controle: {ticker}*\n\nAqui você extrai os documentos oficiais e balanços direto das fontes regulatórias."
            else:
                markup.row(InlineKeyboardButton("📑 Relatório Gerencial", callback_data=f"doc_gerencial_{ticker}"))
                markup.row(InlineKeyboardButton("🚨 Fatos Relevantes", callback_data=f"doc_fato_{ticker}_fii"))
                markup.row(InlineKeyboardButton("🧠 Resumo IA (Geral)", callback_data=f"ia_{ticker}"))
                markup.row(InlineKeyboardButton("🔙 Voltar para FIIs", callback_data="menu_fiis"))
                texto = f"📌 *Painel de Controle: {ticker}*\n\nAcesse relatórios gerenciais e comunicados ao mercado."
            
            # Exclui a mensagem anterior e envia uma nova COM A LOGO
            url_logo = obter_url_logo(ticker)
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_photo(call.message.chat.id, url_logo, caption=texto, reply_markup=markup, parse_mode="Markdown")
            return

        # 3. Funções de Documentos e IA
        elif dados.startswith("doc_fato_"):
            partes = dados.split("_")
            ticker = partes[2]
            tipo_ativo = partes[3]
            bot.answer_callback_query(call.id, f"A ler Fatos Relevantes para {ticker}...")
            is_fii = True if tipo_ativo == 'fii' else False
            resumo = module_cvm.buscar_fatos_relevantes(ticker, is_fii)
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("🔙 Voltar", callback_data=f"acao_{ticker}" if not is_fii else f"fii_{ticker}"))
            # Como a mensagem atual é uma foto, precisamos usar edit_message_caption ou enviar nova
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, resumo, reply_markup=markup, parse_mode="Markdown")
            return

        elif dados.startswith("doc_gerencial_"):
            ticker = dados.split("_")[2]
            bot.answer_callback_query(call.id, f"A extrair relatórios de {ticker}...")
            resumo = module_cvm.buscar_relatorios_gerenciais(ticker)
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("🔙 Voltar", callback_data=f"fii_{ticker}"))
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, resumo, reply_markup=markup, parse_mode="Markdown")
            return

        elif dados.startswith("doc_trimestre_"):
            ticker = dados.split("_")[2]
            bot.answer_callback_query(call.id, f"A baixar balanço ITR de {ticker}...")
            resumo = module_cvm.buscar_resultados_trimestrais(ticker)
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("🔙 Voltar", callback_data=f"acao_{ticker}"))
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, resumo, reply_markup=markup, parse_mode="Markdown")
            return

        elif dados.startswith("ia_"):
            ticker = dados.split("_")[1]
            bot.answer_callback_query(call.id, f"Gemini a analisar {ticker}...")
            analise = module_ia.analisar_fatos_com_ia(f"Faça um resumo financeiro geral da saúde e dos últimos movimentos do ativo {ticker}")
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="voltar_menu"))
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, f"🧠 *Análise Gemini - {ticker}*\n\n{analise}", reply_markup=markup, parse_mode="Markdown")
            return

    except Exception as e:
        print(f"Erro no botão {call.data}: {e}")
        bot.answer_callback_query(call.id, "❌ Erro ao processar o comando.")

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