import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import io
import json
import requests
import os
from flask import Flask, request
from googleapiclient.discovery import build
from google.oauth2 import service_account
from googleapiclient.http import MediaIoBaseUpload
from sqlalchemy import func

import config
from models import Ativo, DocumentosQualitativos, SessionDB
from modules.utils import conectar_gspread
from modules import module_cvm
from modules import module_ia
from modules import module_macro

print(f"DEBUG: Groq Key encontrada: {'SIM' if os.environ.get('GROQ_API_KEY') else 'NÃO'}")

bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN, threaded=False)
app = Flask(__name__)

# ==========================================
# UTILITÁRIO: LOGOS DAS EMPRESAS (CACHE NO DRIVE)
# ==========================================
def autenticar_drive_logos():
    try:
        google_creds = os.environ.get('GOOGLE_CREDS')
        if not google_creds: return None
        creds = service_account.Credentials.from_service_account_info(
            json.loads(google_creds), 
            scopes=['https://www.googleapis.com/auth/drive.file', 'https://www.googleapis.com/auth/drive.readonly']
        )
        return build('drive', 'v3', credentials=creds)
    except:
        return None

def obter_e_salvar_logo(ticker):
    """
    Orquestrador de Logos: Drive -> GitHub -> Logo.dev -> Google Favicons
    Blindado contra falhas do Google Drive e adaptado para o Telegram.
    """
    ticker_upper = ticker.upper()
    nome_arquivo = f"{ticker_upper}_logo.png"
    service = autenticar_drive_logos()

    # 1. TENTA NO DRIVE (CACHE)
    if service:
        try:
            query = f"name='{nome_arquivo}' and '{config.DRIVE_FOLDER_ID}' in parents and trashed=false"
            resultados = service.files().list(q=query, fields="files(id)").execute()
            arquivos = resultados.get('files', [])

            if arquivos:
                file_id = arquivos[0]['id']
                foto_bytes = service.files().get_media(fileId=file_id).execute()

                # Prepara para o Telegram (Exige Nome e Cursor no início)
                img_stream = io.BytesIO(foto_bytes)
                img_stream.name = nome_arquivo
                img_stream.seek(0)
                return img_stream
        except Exception as e:
            print(f"⚠️ Aviso Drive (Leitura): {e}")

    # 2. SE NÃO TEM NO DRIVE, BUSCA NA INTERNET
    url_encontrada = None

    # A. Tenta o seu GitHub
    mapa_antigos = {"GARE11": "GALG11", "RZTR11": "RZTR11"}
    ticker_busca = mapa_antigos.get(ticker_upper, ticker_upper)
    url_github = f"https://raw.githubusercontent.com/WandesonMarcone/icones-bolsabr/main/icones/{ticker_busca}.png"

    try:
        if requests.head(url_github, timeout=2).status_code == 200:
            url_encontrada = url_github
    except: pass

    # B. Tenta Logo.dev ou Google Favicons
    if not url_encontrada:
        dominios = {
            "PETR4": "petrobras.com.br",
            "VALE3": "vale.com",
            "BBAS3": "bb.com.br",
            "ITUB4": "itau.com.br",
            "HGLG11": "cshg.com.br",
            "VISC11": "vincipartners.com",
            "KNRI11": "kinea.com.br",
            "GARE11": "guardiangestora.com.br",
            "MXRF11": "xpi.com.br"
        }
        dominio = dominios.get(ticker_upper)

        if dominio:
            token_logodev = os.environ.get('LOGO_DEV_TOKEN')
            if token_logodev:
                url_encontrada = f"https://img.logo.dev/{dominio}?token={token_logodev}"
            else:
                url_encontrada = f"https://www.google.com/s2/favicons?domain={dominio}&sz=256"

    # 3. SALVA NO DRIVE E RETORNA PARA O TELEGRAM
    if url_encontrada:
        try:
            resposta = requests.get(url_encontrada, timeout=5)
            if resposta.status_code == 200:
                foto_bytes = resposta.content

                # Tenta salvar no Drive isoladamente
                if service:
                    try:
                        file_metadata = {'name': nome_arquivo, 'parents': [config.DRIVE_FOLDER_ID]}
                        media = MediaIoBaseUpload(io.BytesIO(foto_bytes), mimetype='image/png')
                        service.files().create(body=file_metadata, media_body=media, fields='id').execute()
                        print(f"💾 {ticker} salva no Drive com sucesso!")
                    except Exception as e_drive:
                        print(f"⚠️ Aviso Drive (Salvamento): {e_drive}")

                # Prepara para o Telegram
                img_stream = io.BytesIO(foto_bytes)
                img_stream.name = nome_arquivo
                img_stream.seek(0)
                return img_stream
        except Exception as e:
            print(f"⚠️ Erro ao baixar imagem da internet: {e}")

    # 4. FALLBACK PADRÃO
    is_fii = ticker_upper.endswith(('11', '13', '14'))
    if is_fii:
        return "https://cdn-icons-png.flaticon.com/512/3125/3125692.png" 
    return "https://cdn-icons-png.flaticon.com/512/2933/2933116.png"

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
# MENUS DE NAVEGAÇÃO E LOGS
# ==========================================
@bot.message_handler(commands=['menu', 'start'])
def enviar_menu(message):
    """Menu principal limpo com acesso à seção de Ajuda."""
    try:
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("🏢 FIIs (Imobiliários)", callback_data="menu_fiis"),
                   InlineKeyboardButton("📈 Ações (Empresas)", callback_data="menu_acoes"))
        markup.row(InlineKeyboardButton("🌍 Visão Macro & Notícias", callback_data="menu_macro"))
        
        # O novo botão de Ajuda / Logs
        markup.row(InlineKeyboardButton("ℹ️ Ajuda / Sobre", callback_data="menu_ajuda"))

        mensagem_final = "🤖 *Terminal Institucional* 🤖\nSelecione o módulo de análise abaixo:"
        bot.send_message(message.chat.id, mensagem_final, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        print(f"Erro no menu inicial: {e}")
        bot.reply_to(message, "❌ Erro ao abrir o menu.")

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

# ==========================================
# PORTEIRO DOS BOTÕES (Callback Handler Único)
# ==========================================
@bot.callback_query_handler(func=lambda call: True)
def callback_geral(call):
    try:
        dados = call.data

        # 1. Menus Principais
        if dados == "voltar_menu":
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("🏢 FIIs (Imobiliários)", callback_data="menu_fiis"),
                       InlineKeyboardButton("📈 Ações (Empresas)", callback_data="menu_acoes"))
            markup.row(InlineKeyboardButton("🌍 Visão Macro & Notícias", callback_data="menu_macro"))
            markup.row(InlineKeyboardButton("ℹ️ Ajuda / Sobre", callback_data="menu_ajuda")) # Adicionado aqui também
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                                  text="🤖 *Terminal Institucional* 🤖\nSelecione o módulo de análise abaixo:", 
                                  reply_markup=markup, parse_mode="Markdown")
            return

        # --- NOVA SEÇÃO: AJUDA E LOGS ---
        elif dados == "menu_ajuda":
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("⚠️ Histórico de Logs", callback_data="ver_logs"))
            markup.row(InlineKeyboardButton("🔙 Voltar ao Início", callback_data="voltar_menu"))
            texto_ajuda = (
                "ℹ️ *Painel de Ajuda / Sobre*\n\n"
                "Este é o seu Terminal Institucional. O robô monitora, coleta e "
                "processa dados oficiais da CVM e B3 automaticamente todos os dias.\n\n"
                "Selecione uma opção abaixo para auditar o sistema."
            )
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                                  text=texto_ajuda, reply_markup=markup, parse_mode="Markdown")
            return

        elif dados == "ver_logs":
            bot.answer_callback_query(call.id, "A buscar e organizar logs...")
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("🔙 Voltar para Ajuda", callback_data="menu_ajuda"))
            
            try:
                planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
                aba_logs = planilha.worksheet("BD_Logs")
                linhas = aba_logs.get_all_values()
                
                if len(linhas) > 1:
                    # Pega os dados, remove o cabeçalho e inverte (para o mais novo ficar no topo)
                    logs_dados = linhas[1:]
                    logs_dados.reverse()
                    
                    # Pega apenas os 10 mais recentes para não bugar a mensagem do Telegram
                    logs_recentes = logs_dados[:10]
                    
                    texto_logs = "📜 *Histórico de Logs (Mais Recentes Primeiro):*\n"
                    
                    data_atual = ""
                    for linha in logs_recentes:
                        data_completa = linha[0] # Ex: 13/07/2026 10:45:00
                        data_dia = data_completa[:10]
                        hora = data_completa[11:16]
                        erro_limpo = str(linha[2]).replace('*', '').replace('_', '').replace('[', '(').replace(']', ')')
                        
                        # Se mudou de dia, cria um título novo (agrupa pela data visualmente)
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
                                      text=f"❌ Erro ao ler logs na planilha: {e}", reply_markup=markup, parse_mode="Markdown")
            return
        # --------------------------------
        
        # Daqui para baixo o código continua igual (menu_macro, menu_fiis, etc...)

        elif dados == "menu_macro":
            bot.answer_callback_query(call.id, "🌍 Coletando dados macroeconômicos oficiais...")
            resultado = module_macro.obter_dados_macro()
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="voltar_menu"))
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=resultado, reply_markup=markup, parse_mode="Markdown")
            return

        # 1.1 Módulo Hierárquico de FIIs
        elif dados == "menu_fiis":
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("⭐ Meus Favoritos", callback_data="lista_fiis_favoritos"))
            markup.row(InlineKeyboardButton("🔥 Oportunidades (Desconto)", callback_data="lista_fiis_oportunidades"))
            markup.row(
                InlineKeyboardButton("🧱 Tijolo", callback_data="lista_fiis_tijolo"),
                InlineKeyboardButton("📄 Papel", callback_data="lista_fiis_papel")
            )
            markup.row(InlineKeyboardButton("🔙 Voltar ao Início", callback_data="voltar_menu"))
            bot.edit_message_text("🏢 *Módulo FIIs*\nFiltre o mercado por estratégia ou segmento:", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
            return

        # 1.2 Módulo Hierárquico de Ações
        elif dados == "menu_acoes":
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("⭐ Meus Favoritos", callback_data="lista_acoes_favoritos"))
            markup.row(InlineKeyboardButton("🔥 Oportunidades do Dia", callback_data="lista_acoes_oportunidades"))
            markup.row(
                InlineKeyboardButton("🏦 Bancos", callback_data="lista_acoes_bancos"),
                InlineKeyboardButton("⚡ Energia", callback_data="lista_acoes_energia")
            )
            markup.row(InlineKeyboardButton("🔙 Voltar ao Início", callback_data="voltar_menu"))
            bot.edit_message_text("📈 *Módulo de Ações*\nFiltre o mercado por setor ou tese de investimento:", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
            return

        # 1.3 Submenus de FIIs (Geração de Listas via Google Sheets)
        elif dados.startswith("lista_fiis_"):
            categoria = dados.split("_")[2]
            bot.answer_callback_query(call.id, f"A carregar {categoria}...")
            markup = InlineKeyboardMarkup()

            if categoria == "favoritos":
                for ticker in config.FIXAS_FIIS:
                    markup.row(InlineKeyboardButton(f"🏢 {ticker}", callback_data=f"fii_{ticker}"))
            else:
                aba_fiis = conectar_gspread().open_by_url(config.SPREADSHEET_URL).worksheet("BD_FIIs")
                dados_planilha = aba_fiis.get_all_values()
                for row in dados_planilha[1:]:
                    if row and row[0].strip() and not row[0].replace(',', '').isnumeric():
                        ticker = row[0].strip().upper()
                        markup.row(InlineKeyboardButton(f"🏢 {ticker}", callback_data=f"fii_{ticker}"))

            markup.row(InlineKeyboardButton("🔙 Voltar aos FIIs", callback_data="menu_fiis"))
            bot.edit_message_text(f"🏢 *Categoria: {categoria.capitalize()}*\nSelecione um ativo para Raio-X:", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
            return

        # 1.4 Submenus de Ações (Geração de Listas via Google Sheets)
        elif dados.startswith("lista_acoes_"):
            categoria = dados.split("_")[2]
            bot.answer_callback_query(call.id, f"A carregar {categoria}...")
            markup = InlineKeyboardMarkup()

            if categoria == "favoritos":
                for ticker in getattr(config, 'FIXAS_ACOES', []):
                    markup.row(InlineKeyboardButton(f"📈 {ticker}", callback_data=f"acao_{ticker}"))
            else:
                aba_acoes = conectar_gspread().open_by_url(config.SPREADSHEET_URL).worksheet("BD_Acoes")
                dados_planilha = aba_acoes.get_all_values()
                for row in dados_planilha[1:]:
                    if row and row[0].strip() and not row[0].replace(',', '').isnumeric():
                        ticker = row[0].strip().upper()
                        markup.row(InlineKeyboardButton(f"📈 {ticker}", callback_data=f"acao_{ticker}"))

            markup.row(InlineKeyboardButton("🔙 Voltar às Ações", callback_data="menu_acoes"))
            bot.edit_message_text(f"📈 *Categoria: {categoria.capitalize()}*\nSelecione um ativo para Raio-X:", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
            return

        # 2. Perfil do Ativo (Quando clica num Ticker)
        elif dados.startswith("acao_") or dados.startswith("fii_"):
            partes = dados.split("_")
            tipo = partes[0]
            ticker = partes[1]
            bot.answer_callback_query(call.id, f"A abrir terminal para {ticker}...")
            markup = InlineKeyboardMarkup()

            if tipo == "acao":
                markup.row(InlineKeyboardButton("📊 Resultados Oficiais (CVM)", callback_data=f"doc_trimestre_{ticker}"))
                markup.row(InlineKeyboardButton("🚨 Fatos Relevantes", callback_data=f"doc_fato_{ticker}_acao"))
                markup.row(InlineKeyboardButton("🔙 Voltar para Ações", callback_data="menu_acoes"))
                texto = f"📌 *Painel de Controle: {ticker}*\n\nAqui você extrai os balanços direto do banco de dados institucional CVM/B3."
            else:
                markup.row(InlineKeyboardButton("📑 Relatório Gerencial", callback_data=f"doc_gerencial_{ticker}"))
                markup.row(InlineKeyboardButton("🚨 Fatos Relevantes", callback_data=f"doc_fato_{ticker}_fii"))
                markup.row(InlineKeyboardButton("🔙 Voltar para FIIs", callback_data="menu_fiis"))
                texto = f"📌 *Painel de Controle: {ticker}*\n\nAcesse relatórios gerenciais e comunicados oficiais do FNET."

            foto_dado = obter_e_salvar_logo(ticker)
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_photo(call.message.chat.id, foto_dado, caption=texto, reply_markup=markup, parse_mode="Markdown")
            return

        # 3. Funções de Documentos (A conexão com o module_cvm)
        elif dados.startswith("doc_"):
            bot.answer_callback_query(call.id, "A vasculhar o banco de dados oficial...")
            partes = dados.split("_")
            acao_solicitada = partes[1] # 'trimestre', 'fato' ou 'gerencial'
            ticker = partes[2]
            
            bot.send_message(call.message.chat.id, f"⏳ Analisando dados oficiais de {ticker}. Aguarde um instante...", parse_mode="Markdown")
            
            resultado = "Dados não encontrados."
            
            if acao_solicitada == "trimestre":
                resultado = module_cvm.buscar_resultados_trimestrais(ticker)
            elif acao_solicitada == "gerencial":
                resultado = module_cvm.buscar_relatorios_gerenciais(ticker)
            elif acao_solicitada == "fato":
                resultado = module_cvm.buscar_fatos_relevantes(ticker)
                
            bot.send_message(call.message.chat.id, resultado, parse_mode="Markdown")

    except Exception as e:
        print(f"Erro no Callback: {e}")
        bot.answer_callback_query(call.id, f"Erro interno: {str(e)[:50]}")