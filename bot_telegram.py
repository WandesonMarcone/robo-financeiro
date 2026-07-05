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

# --- 6. VISUALIZAR DETALHE DA AÇÃO ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("acao_"))
def detalhe_acao(call):
    ticker = call.data.split("_")[1]
    bot.answer_callback_query(call.id, f"A preparar motor de cálculo para {ticker}...")
    try:
        texto = f"📌 *ANÁLISE ESTRUTURAL: {ticker}*\n\n"
        texto += "⏳ _Os motores de Valuation Triplo e IA estão prontos nos botões abaixo._"

        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("📰 Resumo IA (Fatos)", callback_data=f"ia_{ticker}"))
        # Chamamos o valuation sem parâmetros iniciais para ele calcular o histórico sozinho
        markup.row(InlineKeyboardButton("🧮 Calcular Valuation Triplo", callback_data=f"val_{ticker}"))
        markup.row(InlineKeyboardButton("🔙 Voltar", callback_data="menu_acoes"))

        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=texto, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Erro: {e}")

# --- 7. MOTOR MATEMÁTICO: VALUATION TRIPLO (BAZIN, PROJETIVO E FCD) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("val_"))
def valuation_triplo(call):
    partes = call.data.split("_")
    ticker = partes[1]
    
    # Se existirem parâmetros nos botões de simulação
    payout_custom = float(partes[2]) if len(partes) > 2 else None
    yield_exigido = float(partes[3]) if len(partes) > 3 else 0.08
    
    bot.answer_callback_query(call.id, f"Lendo DRE e projetando {ticker}...")
    
    try:
        asset = yf.Ticker(f"{ticker}.SA")
        info = asset.info
        preco_atual = info.get('currentPrice') or info.get('regularMarketPrice') or 0
        lpa_atual = info.get('trailingEps') or 0.01 
        
        # A) DADOS HISTÓRICOS BAZIN
        historico_divs = asset.dividends
        ano_atual = datetime.now().year
        divs_5_anos = historico_divs[historico_divs.index.year >= (ano_atual - 5)]
        dpa_medio_5a = divs_5_anos.sum() / 5 if not divs_5_anos.empty else 0
        
        # Limita o Payout Histórico Base para ser seguro (entre 10% e 100%)
        payout_historico = (dpa_medio_5a / lpa_atual) if lpa_atual > 0 else 0.5
        payout_historico = max(0.1, min(payout_historico, 1.0))
        
        # B) ACESSA A DRE (LUCRO LÍQUIDO DOS ÚLTIMOS 3-4 ANOS) PARA CALCULAR CRESCIMENTO
        try:
            lucros = asset.income_stmt.loc['Net Income']
            lucros_lista = lucros.dropna().values[::-1] # Do mais antigo para o mais novo
            # Calcula o CAGR (Taxa de Crescimento Anual Composta)
            if len(lucros_lista) >= 2 and lucros_lista[0] > 0:
                cagr_lucro = (lucros_lista[-1] / lucros_lista[0]) ** (1 / (len(lucros_lista) - 1)) - 1
            else:
                cagr_lucro = 0.05
        except:
            cagr_lucro = 0.05
            
        cagr_lucro = max(0, min(cagr_lucro, 0.15)) # Limita o crescimento projetado a 15% (Conservador)
        
        # C) AS PROJEÇÕES PARA O PRÓXIMO ANO
        lpa_projetado = lpa_atual * (1 + cagr_lucro)
        payout_usado = payout_custom / 100 if payout_custom else payout_historico
        dividendo_projetado = lpa_projetado * payout_usado

        # D) OS CÁLCULOS DOS 3 MÉTODOS
        teto_bazin = dpa_medio_5a / 0.06
        teto_projetivo = dividendo_projetado / yield_exigido
        
        taxa_desconto_fcd = 0.12 # WACC Conservador do Brasil (12%)
        teto_fcd = lpa_projetado / (taxa_desconto_fcd - cagr_lucro) if taxa_desconto_fcd > cagr_lucro else 0

        # E) MONTAGEM DA INTERFACE
        texto = f"🧮 *VALUATION TRIPLO: {ticker}*\n"
        texto += f"💵 Preço Atual: R$ {preco_atual:.2f}\n\n"
        
        texto += f"📊 *Projeção (Próx. 12m):*\n"
        texto += f"• Crescimento Histórico (DRE): {cagr_lucro*100:.1f}%\n"
        texto += f"• LPA Projetado: R$ {lpa_projetado:.2f}\n"
        texto += f"• Payout Utilizado: {payout_usado*100:.1f}%\n"
        texto += f"• Dividendo Projetado: R$ {dividendo_projetado:.2f}\n\n"

        margem_bazin = ((teto_bazin/preco_atual)-1)*100 if preco_atual > 0 else 0
        texto += f"🏛️ *1. TETO BAZIN (Histórico)*\n"
        texto += f"R$ {teto_bazin:.2f} ({margem_bazin:+.1f}%)\n\n"

        margem_proj = ((teto_projetivo/preco_atual)-1)*100 if preco_atual > 0 else 0
        texto += f"🚀 *2. TETO PROJETIVO (Vídeo)*\n"
        texto += f"_Exigindo {yield_exigido*100:.1f}% de DY_\n"
        texto += f"R$ {teto_projetivo:.2f} ({margem_proj:+.1f}%)\n\n"

        margem_fcd = ((teto_fcd/preco_atual)-1)*100 if preco_atual > 0 else 0
        texto += f"💸 *3. TETO FCD (Lucro Total)*\n"
        texto += f"R$ {teto_fcd:.2f} ({margem_fcd:+.1f}%)\n"

        # F) OS BOTÕES MÁGICOS DE SIMULAÇÃO
        markup = InlineKeyboardMarkup()
        p_val = payout_usado * 100
        markup.row(
            InlineKeyboardButton("📊 Payout 40%", callback_data=f"val_{ticker}_40_{yield_exigido}"),
            InlineKeyboardButton("📊 Payout 60%", callback_data=f"val_{ticker}_60_{yield_exigido}")
        )
        markup.row(
            InlineKeyboardButton("🎯 Exigir 6% DY", callback_data=f"val_{ticker}_{p_val:.1f}_0.06"),
            InlineKeyboardButton("🎯 Exigir 8% DY", callback_data=f"val_{ticker}_{p_val:.1f}_0.08")
        )
        markup.row(InlineKeyboardButton("🔙 Voltar para a Ação", callback_data=f"acao_{ticker}"))

        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=texto, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Erro no cálculo: {e}")

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