import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import gspread
import os
import json
import threading
import traceback
import math
import yfinance as yf
from datetime import datetime
from flask import Flask, request

# --- IMPORTAÇÃO DOS SEUS CÉREBROS ---
import module_ia 
import module_macro
import module_cvm_bridge

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

            dy = f"{float(linha_ativo[6])*100:.2f}%" if (len(linha_ativo) > 6 and linha_ativo[6].replace('.', '').isnumeric()) else "Aguardando atualização..."
            vacancia = f"{float(linha_ativo[7])*100:.2f}%" if (len(linha_ativo) > 7 and linha_ativo[7].replace('.', '').isnumeric()) else "0.00%"

            texto = f"📌 *{ticker}* ({tipo} - {setor})\n\n💵 *Preço Atual:* R$ {preco}\n⚖️ *P/VP:* {pvp}\n💰 *DY (12m):* {dy}\n🏢 *Vacância Média:* {vacancia}\n\n_Dados extraídos diretamente da infraestrutura do seu Banco de Dados._"

            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("📑 Relatório Gerencial", callback_data=f"doc_gerencial_{ticker}"))
            markup.row(InlineKeyboardButton("🚨 Fatos Relevantes", callback_data=f"doc_fato_{ticker}_fii"))
            markup.row(InlineKeyboardButton("🧠 Resumo IA (Geral)", callback_data=f"ia_{ticker}"))
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

# --- 6. VISUALIZAR DETALHE DA AÇÃO (RAIO-X COMPLETO) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("acao_"))
def detalhe_acao(call):
    ticker = call.data.split("_")[1]
    bot.answer_callback_query(call.id, f"A extrair Raio-X financeiro de {ticker}...")
    try:
        asset = yf.Ticker(f"{ticker}.SA")
        info = asset.info

        preco_atual = info.get('currentPrice') or info.get('regularMarketPrice') or 0
        setor = info.get('sector', 'Não Informado')
        pl = info.get('trailingPE', 0)
        pvp = info.get('priceToBook', 0)
        lpa = info.get('trailingEps', 0)
        vpa = info.get('bookValue', 0)
        dy = (info.get('dividendYield', 0) * 100) if info.get('dividendYield') else 0

        historico_divs = asset.dividends
        ano_atual = datetime.now().year
        divs_5_anos = historico_divs[historico_divs.index.year >= (ano_atual - 5)]
        dpa_medio_5a = divs_5_anos.sum() / 5 if not divs_5_anos.empty else 0
        payout = (dpa_medio_5a / lpa * 100) if lpa > 0 else 0

        texto = f"📌 *RAIO-X ESTRUTURAL: {ticker}*\n"
        texto += f"🏭 *Setor:* {setor}\n\n"

        texto += f"💵 *Preço Atual:* R$ {preco_atual:.2f}\n"
        texto += f"💰 *Dividend Yield:* {dy:.2f}%\n"
        texto += f"📊 *Payout Histórico Médio:* {payout:.1f}%\n\n"

        texto += f"📈 *Múltiplos de Valuation:*\n"
        texto += f"• *P/L (Preço/Lucro):* {pl:.2f}\n"
        texto += f"• *P/VP (Preço/Valor Patrimonial):* {pvp:.2f}\n"
        texto += f"• *LPA (Lucro por Ação):* R$ {lpa:.2f}\n"
        texto += f"• *VPA (Valor Patrimonial):* R$ {vpa:.2f}\n"

        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("📊 Resultados 1º Tri / Lucros", callback_data=f"doc_trimestre_{ticker}"))
        markup.row(InlineKeyboardButton("🚨 Fatos Relevantes", callback_data=f"doc_fato_{ticker}_acao"))
        markup.row(InlineKeyboardButton("🎯 Preços Teto (Graham/Bazin)", callback_data=f"teto_{ticker}"))
        markup.row(InlineKeyboardButton("🚀 Preço Projetivo (Vídeo)", callback_data=f"proj_{ticker}"))
        markup.row(InlineKeyboardButton("🧠 Avaliação IA (Geral)", callback_data=f"ia_{ticker}"))
        markup.row(InlineKeyboardButton("🔙 Voltar para Ações", callback_data="menu_acoes"))

        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=texto, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        if "message is not modified" not in str(e):
            bot.send_message(call.message.chat.id, f"❌ Erro ao processar dados de {ticker}: {e}")

# --- 7. MÓDULO: PREÇOS TETO (GRAHAM E BAZIN) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("teto_"))
def precos_teto(call):
    ticker = call.data.split("_")[1]
    bot.answer_callback_query(call.id, f"A calcular Graham e Bazin para {ticker}...")

    try:
        asset = yf.Ticker(f"{ticker}.SA")
        info = asset.info
        preco_atual = info.get('currentPrice') or info.get('regularMarketPrice') or 0
        lpa = info.get('trailingEps', 0)
        vpa = info.get('bookValue', 0)

        historico_divs = asset.dividends
        ano_atual = datetime.now().year
        divs_5_anos = historico_divs[historico_divs.index.year >= (ano_atual - 5)]
        dpa_medio_5a = divs_5_anos.sum() / 5 if not divs_5_anos.empty else 0
        teto_bazin = dpa_medio_5a / 0.06
        margem_bazin = ((teto_bazin/preco_atual)-1)*100 if preco_atual > 0 else 0

        if lpa > 0 and vpa > 0:
            teto_graham = math.sqrt(22.5 * lpa * vpa)
            margem_graham = ((teto_graham/preco_atual)-1)*100 if preco_atual > 0 else 0
            texto_graham = f"R$ {teto_graham:.2f} ({margem_graham:+.1f}%)"
        else:
            texto_graham = "N/A (LPA ou VPA negativos)"

        texto = f"🎯 *PREÇOS TETO (HISTÓRICOS): {ticker}*\n"
        texto += f"💵 Preço Atual: R$ {preco_atual:.2f}\n\n"

        texto += f"🏛️ *1. FÓRMULA DE GRAHAM*\n"
        texto += f"_Baseado no Lucro e Patrimônio_\n"
        texto += f"Teto: {texto_graham}\n\n"

        texto += f"💰 *2. MÉTODO DE BAZIN*\n"
        texto += f"_Baseado na média de dividendos (6%)_\n"
        texto += f"Teto: R$ {teto_bazin:.2f} ({margem_bazin:+.1f}%)\n"

        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("🚀 Ir para Preço Projetivo", callback_data=f"proj_{ticker}"))
        markup.row(InlineKeyboardButton("🔙 Voltar", callback_data=f"acao_{ticker}"))

        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=texto, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Erro no cálculo: {e}")

# --- 8. MÓDULO: PREÇO PROJETIVO (DO VÍDEO) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("proj_"))
def valuation_projetivo(call):
    partes = call.data.split("_")
    ticker = partes[1]

    payout_custom = float(partes[2]) if len(partes) > 2 else 50.0 
    yield_exigido = float(partes[3]) if len(partes) > 3 else 0.08 

    bot.answer_callback_query(call.id, f"Projetando DRE de {ticker}...")

    try:
        asset = yf.Ticker(f"{ticker}.SA")
        info = asset.info
        preco_atual = info.get('currentPrice') or info.get('regularMarketPrice') or 0
        lpa_atual = info.get('trailingEps') or 0.01 

        cagr_lucro = 0.05 
        lpa_projetado = lpa_atual * (1 + cagr_lucro)

        dividendo_projetado = lpa_projetado * (payout_custom / 100)
        teto_projetivo = dividendo_projetado / yield_exigido
        margem_proj = ((teto_projetivo/preco_atual)-1)*100 if preco_atual > 0 else 0

        texto = f"🚀 *PREÇO TETO PROJETIVO: {ticker}*\n"
        texto += f"💵 Preço Atual: R$ {preco_atual:.2f}\n\n"

        texto += f"📊 *Premissas do Próximo Ano:*\n"
        texto += f"• LPA Projetado: R$ {lpa_projetado:.2f}\n"
        texto += f"• Payout Simulado: {payout_custom:.1f}%\n"
        texto += f"• Dividendo Projetado: R$ {dividendo_projetado:.2f}\n\n"

        texto += f"🎯 *RESULTADO (Exigindo {yield_exigido*100:.1f}% de DY)*\n"
        texto += f"💎 *Preço Teto:* R$ {teto_projetivo:.2f}\n"

        if margem_proj > 0:
            texto += f"🟢 *Margem:* +{margem_proj:.1f}% (Oportunidade)"
        else:
            texto += f"🔴 *Margem:* {margem_proj:.1f}% (Caro)"

        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("📊 Payout 40%", callback_data=f"proj_{ticker}_40_{yield_exigido}"),
            InlineKeyboardButton("📊 Payout 60%", callback_data=f"proj_{ticker}_60_{yield_exigido}")
        )
        markup.row(
            InlineKeyboardButton("🎯 Exigir 6% DY", callback_data=f"proj_{ticker}_{payout_custom}_0.06"),
            InlineKeyboardButton("🎯 Exigir 8% DY", callback_data=f"proj_{ticker}_{payout_custom}_0.08")
        )
        markup.row(InlineKeyboardButton("💾 Salvar na Planilha", callback_data=f"salvar_{ticker}_{teto_projetivo:.2f}"))
        markup.row(InlineKeyboardButton("🔙 Voltar", callback_data=f"acao_{ticker}"))

        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=texto, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Erro no cálculo projetivo: {e}")

# --- 9. AVALIAÇÃO IA GENÉRICA ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("ia_"))
def chamar_ia(call):
    ticker = call.data.split("_")[1]
    bot.answer_callback_query(call.id, f"O Gemini está analisando {ticker}...")

    analise = module_ia.analisar_fatos_com_ia(ticker)

    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="voltar_menu"))
    try:
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"🧠 *Análise Gemini - {ticker}*\n\n{analise}", reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        if "message is not modified" not in str(e):
            print(f"Erro IA: {e}")

# --- 10. MÓDULO MINHA CARTEIRA ---
@bot.callback_query_handler(func=lambda call: call.data == "menu_carteira")
def submenu_carteira(call):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("🔙 Voltar", callback_data="voltar_menu"))
    texto = "💼 *Minha Carteira*\n\n_Módulo de consolidação em construção._"
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=texto, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "voltar_menu")
def voltar_menu_principal(call):
    enviar_menu(call.message)

# --- 11. MÓDULO MACROECONOMIA ---
@bot.callback_query_handler(func=lambda call: call.data == "menu_macro")
def submenu_macro(call):
    bot.answer_callback_query(call.id, "A consultar o Banco Central do Brasil...")

    dados_macro = module_macro.obter_dados_macro()

    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("📰 Últimas Notícias do Mercado", callback_data="noticias_macro"))
    markup.row(InlineKeyboardButton("🔄 Atualizar", callback_data="menu_macro"))
    markup.row(InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="voltar_menu"))

    try:
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=dados_macro, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        if "message is not modified" not in str(e):
            print(e)

# --- 12. PONTES CVM E FUNDOSNET (NOVOS HANDLERS IA) ---

@bot.callback_query_handler(func=lambda call: call.data.startswith("doc_fato_"))
def relatorio_fato_relevante(call):
    try:
        dados = call.data.split("_")
        ticker = dados[2]
        tipo_ativo = dados[3]  # 'acao' ou 'fii'

        bot.answer_callback_query(call.id, f"A ler Fatos Relevantes para {ticker}...")
        is_fii = True if tipo_ativo == 'fii' else False

        resumo = module_cvm_bridge.buscar_fatos_relevantes(ticker, is_fii)

        # CÓDIGO CORRIGIDO (O Erro de Sintaxe estava aqui)
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("🔙 Voltar", callback_data=f"acao_{ticker}" if not is_fii else f"detalhe_{ticker}"))

        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=resumo, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        # Se for o erro do Telegram "message is not modified", a gente ignora silenciosamente
        if "message is not modified" not in str(e):
            print(f"❌ ERRO CRÍTICO NO HANDLER: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("doc_gerencial_"))
def relatorio_gerencial(call):
    try:
        ticker = call.data.split("_")[2]
        bot.answer_callback_query(call.id, f"A extrair relatórios de {ticker}...")

        resumo = module_cvm_bridge.buscar_relatorios_gerenciais(ticker)

        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("🔙 Voltar", callback_data=f"detalhe_{ticker}"))
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=resumo, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        if "message is not modified" not in str(e):
            print(e)

@bot.callback_query_handler(func=lambda call: call.data.startswith("doc_trimestre_"))
def relatorio_trimestral(call):
    try:
        ticker = call.data.split("_")[2]
        bot.answer_callback_query(call.id, f"A ler ITR/DFP de {ticker}...")

        resumo = module_cvm_bridge.buscar_resultados_trimestrais(ticker)

        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("🔙 Voltar", callback_data=f"acao_{ticker}"))
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=resumo, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        if "message is not modified" not in str(e):
            print(e)

@bot.callback_query_handler(func=lambda call: call.data == "noticias_macro")
def noticias_macro(call):
    try:
        bot.answer_callback_query(call.id, "A pesquisar jornais e feeds macroeconómicos...")

        resumo = module_cvm_bridge.buscar_noticias_macro()

        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("🔙 Voltar ao Macro", callback_data="menu_macro"))
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"🌍 *Radar Macroeconómico*\n\n{resumo}", reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        if "message is not modified" not in str(e):
            print(e)

# ==========================================
# MOTOR DO SERVIDOR WEB (COM THREADING E ESCUDO)
# ==========================================
@app.route(f'/{TELEGRAM_BOT_TOKEN}', methods=['POST'])
def webhook():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)

    # Função isolada para rodar em paralelo sem estourar o limite de tempo do Telegram
    def processo_paralelo():
        try:
            bot.process_new_updates([update])
            except Exception as e:
            # O "Escudo Anti-Clone"