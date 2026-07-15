import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import io
import json
import requests
import os
from flask import Flask, request
from sqlalchemy import func, create_engine
from sqlalchemy.orm import sessionmaker

import config
from modules.utils import conectar_gspread
from modules import module_cvm
from modules import module_ia
from modules import module_macro
from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos

# ==========================================
# CONFIGURAÇÕES INICIAIS
# ==========================================
engine = create_engine("sqlite:///pipeline_dados/banco_institucional.db")
SessionDB = sessionmaker(bind=engine)

print(f"DEBUG: Groq Key encontrada: {'SIM' if os.environ.get('GROQ_API_KEY') else 'NÃO'}")

bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN, threaded=False)
app = Flask(__name__)

# ==========================================
# ROTAS DO SERVIDOR WEB (WEBHOOK TELEGRAM)
# ==========================================
@app.route('/' + config.TELEGRAM_BOT_TOKEN, methods=['POST'])
def webhook_handler():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "OK", 200
    return "Erro", 403

@app.route('/')
def index():
    return "Bot Institucional Ativo e Operante!", 200


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
        bot.reply_to(message, f"A procurar {ticker} e a injetar na Planilha do Google...")

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


# ==========================================
# COMANDOS DE STATUS E RELATÓRIOS
# ==========================================
@bot.message_handler(commands=['status'])
def status_banco(message):
    session = SessionDB()
    try:
        total_ativos = session.query(Ativo).count()
        total_docs = session.query(DocumentosQualitativos).count()
        ultimos = session.query(Ativo.ticker).order_by(Ativo.id.desc()).limit(5).all()
        lista_tickers = ", ".join([a[0] for a in ultimos])
        ultima_data = session.query(func.max(DocumentosQualitativos.data_publicacao)).scalar()

        resposta = (
            f"📊 **Painel de Controle do Motor de Dados**\n\n"
            f"🏢 **Ativos monitorados (SQLite):** {total_ativos}\n"
            f"📄 **Documentos salvos (SQLite):** {total_docs}\n"
            f"📅 **Última atualização (SQLite):** {ultima_data}\n\n"
            f"🚀 **Últimos ativos:**\n{lista_tickers}"
        )
        bot.reply_to(message, resposta)
    except Exception as e:
        bot.reply_to(message, f"❌ Erro ao consultar banco: {e}")
    finally:
        session.close()

@bot.message_handler(commands=['relatorios', 'docs'])
def enviar_ultimos_relatorios(message):
    bot.reply_to(message, "🔎 Buscando os últimos documentos no cofre...")
    session = SessionDB()
    try:
        ultimos_docs = session.query(DocumentosQualitativos, Ativo)\
            .join(Ativo, DocumentosQualitativos.ativo_id == Ativo.id)\
            .order_by(DocumentosQualitativos.data_publicacao.desc())\
            .limit(10).all()

        if not ultimos_docs:
            bot.send_message(message.chat.id, "📭 Nenhum documento encontrado no banco ainda.")
            return

        resposta = "📄 **Últimos Relatórios Capturados:**\n\n"
        for doc, ativo in ultimos_docs:
            data_formatada = doc.data_publicacao.strftime('%d/%m/%Y')
            resposta += f"🏢 **{ativo.ticker}** - {data_formatada}\n"
            resposta += f"🏷️ Tipo: {doc.tipo_documento}\n"
            if doc.assunto and doc.assunto.strip():
                resposta += f"📌 Assunto: {doc.assunto}\n"
            resposta += f"🔗 [Acessar PDF]({doc.url_pdf})\n"
            resposta += "➖➖➖➖➖➖➖➖➖➖\n"

        bot.send_message(message.chat.id, resposta, parse_mode='Markdown', disable_web_page_preview=True)
    except Exception as e:
        bot.send_message(message.chat.id, "❌ Ops! Deu um erro ao tentar ler o banco de dados.")
    finally:
        session.close()

# ==========================================
# O NOVO MOTOR DE DASHBOARD (Arquitetura)
# ==========================================
def _buscar_dados_planilha(ticker):
    """Função de apoio para buscar dados da sua aba no Google Sheets"""
    # TODO: Conectar com o Google Sheets aqui! 
    # Por enquanto, retorna valores simulados para a interface não quebrar.
    return {
        "preco": "115,50", 
        "dy": "8.4%", 
        "pl": "12.5", 
        "pvp": "1.03"
    }

def gerar_painel_ativo(ticker, tipo, chat_id, message_id=None):
    """Gera a mensagem principal com os botões interativos e dados em tempo real"""
    icone = "🏢 Fundo" if tipo == "fii" else "📈 Ação"
    voltar_cmd = "menu_fiis" if tipo == "fii" else "menu_acoes"
    
    # 1. Puxar os indicadores da Planilha
    indicadores = _buscar_dados_planilha(ticker)
    
    # 2. Puxar Resumo da IA
    resumo_ia = f"Fundo/Ação focado na geração de valor e exploração de ativos estratégicos no mercado brasileiro." # Substituir pelo modulo_ia
    
    # 3. Montar a tela exata da sua arquitetura
    texto = (
        f"{icone}: **{ticker}**\n"
        f"📝 **Resumo:** _{resumo_ia}_\n\n"
        f"💰 **Preço:** R$ {indicadores['preco']}\n"
        f"💸 **Dividend Yield:** {indicadores['dy']}\n"
        f"📊 **P/L:** {indicadores['pl']} | ⚖️ **P/VP:** {indicadores['pvp']}\n"
    )

    # 4. Criar os Botões (Submenus)
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📎 Dados Importantes", callback_data=f"dados_{ticker}_{tipo}"),
        InlineKeyboardButton("📑 Documentos", callback_data=f"docs_{ticker}_{tipo}")
    )
    markup.add(InlineKeyboardButton("⚠️ Análise de IA", callback_data=f"ia_{ticker}_{tipo}"))
    markup.add(InlineKeyboardButton(f"🔙 Voltar aos {icone.split()[1]}s", callback_data=voltar_cmd))

    if message_id:
        bot.edit_message_text(texto, chat_id, message_id, reply_markup=markup, parse_mode="Markdown")
    else:
        bot.send_message(chat_id, texto, reply_markup=markup, parse_mode="Markdown")


# ==========================================
# MENUS DE NAVEGAÇÃO E CALLBACKS
# ==========================================
@bot.message_handler(commands=['menu', 'start'])
def enviar_menu(message):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("🏢 FIIs (Imobiliários)", callback_data="menu_fiis"),
               InlineKeyboardButton("📈 Ações (Empresas)", callback_data="menu_acoes"))
    markup.row(InlineKeyboardButton("🌍 Visão Macro & Notícias", callback_data="menu_macro"))
    markup.row(InlineKeyboardButton("ℹ️ Ajuda / Sobre", callback_data="menu_ajuda"))
    bot.send_message(message.chat.id, "🤖 *Terminal Institucional* 🤖\nSelecione o módulo de análise abaixo:", reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda call: True)
def callback_geral(call):
    try:
        dados = call.data
        chat_id = call.message.chat.id
        msg_id = call.message.message_id

        # --- MENUS PRINCIPAIS ---
        if dados == "voltar_menu":
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("🏢 FIIs (Imobiliários)", callback_data="menu_fiis"),
                       InlineKeyboardButton("📈 Ações (Empresas)", callback_data="menu_acoes"))
            markup.row(InlineKeyboardButton("🌍 Visão Macro & Notícias", callback_data="menu_macro"))
            markup.row(InlineKeyboardButton("ℹ️ Ajuda / Sobre", callback_data="menu_ajuda"))
            bot.edit_message_text("🤖 *Terminal Institucional* 🤖\nSelecione o módulo de análise abaixo:", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        elif dados == "menu_ajuda":
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("⚠️ Histórico de Logs", callback_data="ver_logs"))
            markup.row(InlineKeyboardButton("🔙 Voltar ao Início", callback_data="voltar_menu"))
            texto_ajuda = (
                "ℹ️ *Painel de Ajuda / Sobre*\n\n"
                "O robô monitora, coleta e processa dados oficiais da CVM e B3 automaticamente.\n\n"
                "📌 *Comandos Rápidos:*\n"
                "`/status` - Saúde do Banco de Dados SQLite\n"
                "`/relatorios` - Últimos documentos (PDFs do Dropbox)\n"
                "`/adicionar TICKER` - Insere ativos na Planilha e no Radar\n\n"
                "📊 *A Nova Arquitetura de Ativos:*\n"
                "Ao selecionar um FII ou Ação, você terá acesso imediato a:\n"
                "- Resumo IA Direto ao Ponto\n"
                "- Indicadores Financeiros (P/L, P/VP, DY)\n"
                "- Submenu `[📑 Documentos]` organizados por mês (via Dropbox)\n"
                "- Submenu `[⚠️ Análise de IA]` para varredura de riscos operacionais."
            )
            bot.edit_message_text(texto_ajuda, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        elif dados == "ver_logs":
            bot.answer_callback_query(call.id, "A buscar logs...")
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("🔙 Voltar para Ajuda", callback_data="menu_ajuda"))
            # Sua lógica de logs continua igual
            bot.edit_message_text("📜 *Histórico de Logs (Mais Recentes):* \n[Em integração com a planilha...]", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        elif dados == "menu_macro":
            bot.answer_callback_query(call.id, "🌍 Coletando dados macroeconômicos oficiais...")
            resultado = module_macro.obter_dados_macro()
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="voltar_menu"))
            bot.edit_message_text(resultado, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        elif dados == "menu_fiis":
            markup = InlineKeyboardMarkup()
            # Botões temporários para testarmos a arquitetura nova
            markup.row(InlineKeyboardButton("🏢 XPML11", callback_data="fii_XPML11"),
                       InlineKeyboardButton("🏢 KNCR11", callback_data="fii_KNCR11"))
            markup.row(InlineKeyboardButton("🔙 Voltar ao Início", callback_data="voltar_menu"))
            bot.edit_message_text("🏢 *Módulo FIIs*\nSelecione um ativo para abrir o Terminal:", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        elif dados == "menu_acoes":
            markup = InlineKeyboardMarkup()
            # Botões temporários para testarmos a arquitetura nova
            markup.row(InlineKeyboardButton("📈 PETR4", callback_data="acao_PETR4"),
                       InlineKeyboardButton("📈 VALE3", callback_data="acao_VALE3"))
            markup.row(InlineKeyboardButton("🔙 Voltar ao Início", callback_data="voltar_menu"))
            bot.edit_message_text("📈 *Módulo de Ações*\nSelecione um ativo para abrir o Terminal:", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # --- A MÁGICA DA NOVA ARQUITETURA DE DADOS ---

        # 1. Abre a tela principal do Ativo
        elif dados.startswith("fii_") or dados.startswith("acao_"):
            partes = dados.split("_")
            tipo = partes[0] # 'fii' ou 'acao'
            ticker = partes[1]
            gerar_painel_ativo(ticker, tipo, chat_id, msg_id)

        # 2. Submenu: Dados Importantes (Google Sheets Completo)
        elif dados.startswith("dados_"):
            partes = dados.split("_")
            ticker = partes[1]
            tipo = partes[2]
            
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(f"🔙 Voltar para {ticker}", callback_data=f"{tipo}_{ticker}"))
            
            texto_dados = f"📎 **Dados Completos: {ticker}**\n\n_(Aqui o bot puxará toda a linha correspondente a este ativo lá do Google Sheets...)_"
            bot.edit_message_text(texto_dados, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # 3. Submenu: Documentos por Mês (Banco de Dados + Dropbox)
        elif dados.startswith("docs_"):
            partes = dados.split("_")
            ticker = partes[1]
            tipo = partes[2]
            
            markup = InlineKeyboardMarkup()
            # Simulando o submenu de meses/documentos
            markup.row(InlineKeyboardButton("📄 Relatório Gerencial (Julho)", url="https://dropbox.com/link_aqui"))
            markup.row(InlineKeyboardButton("📄 Fato Relevante (Junho)", url="https://dropbox.com/link_aqui"))
            markup.add(InlineKeyboardButton(f"🔙 Voltar para {ticker}", callback_data=f"{tipo}_{ticker}"))
            
            texto_docs = f"📑 **Central de Documentos: {ticker}**\nEscolha o arquivo abaixo para abrir no Dropbox:"
            bot.edit_message_text(texto_docs, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # 4. Submenu: Análise IA
        elif dados.startswith("ia_"):
            bot.answer_callback_query(call.id, "Gerando análise de risco avançada...")
            partes = dados.split("_")
            ticker = partes[1]
            tipo = partes[2]
            
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(f"🔙 Voltar para {ticker}", callback_data=f"{tipo}_{ticker}"))
            
            texto_ia = (
                f"⚠️ **Análise de Risco Operacional: {ticker}**\n\n"
                "🔹 **Pontos de Atenção:** (Conectar IA aqui)\n"
                "🔹 **Alavancagem:** (Conectar IA aqui)\n"
                "🔹 **Vacância/Vencimentos:** (Conectar IA aqui)"
            )
            bot.edit_message_text(texto_ia, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

    except Exception as e:
        print(f"Erro no callback: {e}")

if __name__ == '__main__':
    bot.polling(none_stop=True)