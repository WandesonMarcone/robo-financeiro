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
# Cria o motor do banco de dados diretamente no bot usando o seu arquivo original
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
    """Recebe os avisos do Telegram e repassa para o robô processar."""
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "OK", 200
    return "Erro", 403

@app.route('/')
def index():
    """Página inicial para o Render saber que o servidor está vivo."""
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
    """Mostra um resumo da saúde do seu banco de dados."""
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
    """Busca os últimos 10 relatórios salvos no banco e envia no Telegram."""
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
        print(f"Erro ao buscar relatórios: {e}")
        bot.send_message(message.chat.id, "❌ Ops! Deu um erro ao tentar ler o banco de dados.")
    finally:
        session.close()


# ==========================================
# MENUS DE NAVEGAÇÃO
# ==========================================
@bot.message_handler(commands=['menu', 'start'])
def enviar_menu(message):
    """Menu principal limpo."""
    try:
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("🏢 FIIs (Imobiliários)", callback_data="menu_fiis"),
                   InlineKeyboardButton("📈 Ações (Empresas)", callback_data="menu_acoes"))
        markup.row(InlineKeyboardButton("🌍 Visão Macro & Notícias", callback_data="menu_macro"))
        markup.row(InlineKeyboardButton("ℹ️ Ajuda / Sobre", callback_data="menu_ajuda"))

        bot.send_message(message.chat.id, "🤖 *Terminal Institucional* 🤖\nSelecione o módulo de análise abaixo:", reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        print(f"Erro no menu inicial: {e}")
        bot.reply_to(message, "❌ Erro ao abrir o menu.")


# ==========================================
# PORTEIRO DOS BOTÕES (Callback Handler Único)
# ==========================================
@bot.callback_query_handler(func=lambda call: True)
def callback_geral(call):
    try:
        dados = call.data

        if dados == "voltar_menu":
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("🏢 FIIs (Imobiliários)", callback_data="menu_fiis"),
                       InlineKeyboardButton("📈 Ações (Empresas)", callback_data="menu_acoes"))
            markup.row(InlineKeyboardButton("🌍 Visão Macro & Notícias", callback_data="menu_macro"))
            markup.row(InlineKeyboardButton("ℹ️ Ajuda / Sobre", callback_data="menu_ajuda"))
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                                  text="🤖 *Terminal Institucional* 🤖\nSelecione o módulo de análise abaixo:", 
                                  reply_markup=markup, parse_mode="Markdown")
            return

        elif dados == "menu_ajuda":
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("⚠️ Histórico de Logs", callback_data="ver_logs"))
            markup.row(InlineKeyboardButton("🔙 Voltar ao Início", callback_data="voltar_menu"))
            texto_ajuda = (
                "ℹ️ *Painel de Ajuda / Sobre*\n\n"
                "Este é o seu Terminal Institucional. O robô monitora, coleta e "
                "processa dados oficiais da CVM e B3 automaticamente todos os dias.\n\n"
                "Comandos rápidos disponíveis:\n"
                "`/status` - Saúde do Banco de Dados\n"
                "`/relatorios` - Últimos documentos baixados\n"
                "`/adicionar TICKER` - Adiciona um novo ativo à base\n"
            )
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                                  text=texto_ajuda, reply_markup=markup, parse_mode="Markdown")
            return

        elif dados == "ver_logs":
            bot.answer_callback_query(call.id, "A buscar logs...")
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("🔙 Voltar para Ajuda", callback_data="menu_ajuda"))

            try:
                planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
                aba_logs = planilha.worksheet("BD_Logs")
                linhas = aba_logs.get_all_values()

                if len(linhas) > 1:
                    logs_dados = linhas[1:]
                    logs_dados.reverse()
                    logs_recentes = logs_dados[:10]

                    texto_logs = "📜 *Histórico de Logs (Mais Recentes):*\n"
                    data_atual = ""
                    for linha in logs_recentes:
                        data_completa = linha[0]
                        data_dia = data_completa[:10]
                        hora = data_completa[11:16]
                        erro_limpo = str(linha[2]).replace('*', '').replace('_', '').replace('[', '(').replace(']', ')')

                        if data_dia != data_atual:
                            texto_logs += f"\n📅 *{data_dia}*\n"
                            data_atual = data_dia

                        texto_logs += f" 🕒 `{hora}` - {erro_limpo}\n"
                else:
                    texto_logs = "✅ *Status perfeito:* Nenhum log de erro registrado."

                bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                                      text=texto_logs, reply_markup=markup, parse_mode="Markdown")
            except Exception as e:
                bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                                      text=f"❌ Erro ao ler logs: {e}", reply_markup=markup, parse_mode="Markdown")
            return

        elif dados == "menu_macro":
            bot.answer_callback_query(call.id, "🌍 Coletando dados macroeconômicos oficiais...")
            resultado = module_macro.obter_dados_macro()
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="voltar_menu"))
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=resultado, reply_markup=markup, parse_mode="Markdown")
            return

        elif dados == "menu_fiis":
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("⭐ Meus Favoritos", callback_data="lista_fiis_favoritos"))
            markup.row(InlineKeyboardButton("🔥 Oportunidades (Desconto)", callback_data="lista_fiis_oportunidades"))
            markup.row(InlineKeyboardButton("🔙 Voltar ao Início", callback_data="voltar_menu"))
            bot.edit_message_text("🏢 *Módulo FIIs*\nFiltre o mercado:", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
            return

        elif dados == "menu_acoes":
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("⭐ Meus Favoritos", callback_data="lista_acoes_favoritos"))
            markup.row(InlineKeyboardButton("🔥 Oportunidades do Dia", callback_data="lista_acoes_oportunidades"))
            markup.row(InlineKeyboardButton("🔙 Voltar ao Início", callback_data="voltar_menu"))
            bot.edit_message_text("📈 *Módulo de Ações*\nFiltre o mercado:", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
            return

        # Daqui pra frente você desenvolve a lógica dos relatórios individuais (fii_VISC11, acao_PETR4, etc)
        elif dados.startswith("fii_") or dados.startswith("acao_"):
            ticker = dados.split("_")[1]
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("🔙 Voltar", callback_data="voltar_menu"))
            bot.edit_message_text(f"O ativo selecionado foi: {ticker}. Lógica em construção.", call.message.chat.id, call.message.message_id, reply_markup=markup)
            return

    except Exception as e:
        print(f"Erro no callback: {e}")