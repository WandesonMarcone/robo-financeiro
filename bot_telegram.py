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
from atualizador_documentos import rotina_de_atualizacao_em_massa
from modules.utils import conectar_gspread
from pipeline_dados import coletor_cvm
from modules import module_cvm
from modules import module_ia
from modules import module_macro
from modules.GoogleDriveManager import GoogleDriveManager
from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz # Para lidar com o fuso horário do Brasil

# ==========================================
# CONFIGURAÇÃO FILTRO OPORTUNIDADE🚀
# ==========================================
import json
import os

def carregar_filtros():
    """Lê o arquivo de filtros, com proteção contra arquivo inexistente."""
    # Se o arquivo não existir, retorna um dicionário de segurança (padrão)
    if not os.path.exists('filtros.json'):
        print("⚠️ Arquivo filtros.json não encontrado. Usando filtros padrão.")
        return {
            "fii": {"pvp_min": 0.5, "pvp_max": 1.15, "dy_min": 0.08, "liq_min": 1000000, "vac_max": 0.15},
            "acao": {"pl_min": 2, "pl_max": 15, "pvp_min": 0.5, "pvp_max": 2.5, "dy_min": 0.06, "roe_min": 0.10}
        }
        
    with open('filtros.json', 'r') as f:
        return json.load(f)

def salvar_filtros(filtros):
    """Salva as alterações feitas pelo Telegram no arquivo local."""
    with open('filtros.json', 'w') as f:
        json.dump(filtros, f, indent=4)

def converter_numero(valor_string):
    """Limpa textos como 'R$ 1.050,50' ou '8,5%' da planilha e transforma em número puro"""
    try:
        texto = str(valor_string).replace('R$', '').replace('%', '').strip()
        if not texto or texto == '-': return 0.0
        # Resolve o padrão brasileiro de milhar e decimal
        if ',' in texto and '.' in texto:
            texto = texto.replace('.', '')
        texto = texto.replace(',', '.')
        return float(texto)
    except:
        return 0.0

def buscar_oportunidades(tipo):
    """Vasculha a planilha real e retorna os ativos que passam no filtros.json"""
    filtros = carregar_filtros()[tipo]
    is_fii = (tipo == 'fii')
    nome_aba = "BD_FIIs" if is_fii else "BD_Acoes"

    try:
        planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
        aba = planilha.worksheet(nome_aba)
        matriz = aba.get_all_values()
        
        oportunidades = []

        for linha in matriz[1:]: # Começa do [1:] para pular a linha de cabeçalho
            try:
                ticker = linha[0].strip()
                if not ticker: continue

                if is_fii:
                    # Mapeamento de FIIs: P/VP (índice 5), DY (índice 6)
                    pvp = converter_numero(linha[5])
                    dy = converter_numero(linha[6])
                    
                    # Ajuste fino: Se no JSON estiver 0.08 e na planilha 8.5
                    dy_min = filtros.get('dy_min', 0)
                    if dy_min < 1 and dy >= 1: dy_min *= 100 

                    if (filtros['pvp_min'] <= pvp <= filtros['pvp_max']) and (dy >= dy_min):
                        oportunidades.append(ticker)
                else:
                    # Mapeamento de Ações: P/L (5), P/VP (6), DY (3), ROE (19)
                    dy = converter_numero(linha[3])
                    pl = converter_numero(linha[5])
                    pvp = converter_numero(linha[6])
                    roe = converter_numero(linha[19])
                    
                    dy_min = filtros.get('dy_min', 0)
                    if dy_min < 1 and dy >= 1: dy_min *= 100
                        
                    roe_min = filtros.get('roe_min', 0)
                    if roe_min < 1 and roe >= 1: roe_min *= 100

                    if (filtros['pl_min'] <= pl <= filtros['pl_max']) and \
                       (filtros['pvp_min'] <= pvp <= filtros['pvp_max']) and \
                       (dy >= dy_min) and (roe >= roe_min):
                        oportunidades.append(ticker)
                        
            except IndexError:
                # Se a linha na planilha estiver vazia pela metade, ignora e segue
                pass 

        return oportunidades
    except Exception as e:
        print(f"Erro no filtro de oportunidades: {e}")
        return []

def processar_novo_filtro(message, tipo):
    try:
        if ":" not in message.text:
            raise ValueError("Formato incorreto")

        chave, valor = message.text.split(':')
        chave = chave.strip()
        valor = float(valor.strip())

        filtros = carregar_filtros()

        if chave in filtros[tipo]:
            filtros[tipo][chave] = valor
            salvar_filtros(filtros)
            bot.reply_to(message, f"✅ {chave.upper()} ({tipo.upper()}) atualizado para {valor}!")
        else:
            bot.reply_to(message, f"❌ Chave '{chave}' não encontrada. Verifique o nome no filtros.json.")

    except Exception as e:
        bot.reply_to(message, "❌ Erro. Use formato: `chave: valor` (ex: `dy_min: 0.08`)")

# ==========================================
# CONFIGURAÇÕES INICIAIS
# ==========================================
drive_manager = GoogleDriveManager()
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
# MOTOR DE LOGOS (Google Drive -> GitHub -> Logo.dev)
# ==========================================
def obter_link_logo(ticker, tipo):
    """
    Tenta buscar a logo em cascata:
    1. Drive (Cache local)
    2. GitHub (Repositório do Wandeson)
    3. Logo.dev (API Premium)
    """
    try:
        # Define a pasta pai (Logos/fiis ou Logos/acoes)
        pasta_tipo_nome = "fiis" if tipo == "fii" else "acoes"
        # O ID da pasta raiz foi definido no main.yml (DRIVE_ROOT_FOLDER_ID)
        # Vamos assumir que criamos uma pasta "Logos" dentro da raiz
        root_id = os.environ.get('DRIVE_ROOT_FOLDER_ID')
        
        # 1. TENTA BUSCAR NO DRIVE (Cache)
        # (Aqui o código buscaria se o arquivo existe na pasta)
        
        # 2. TENTA BAIXAR DO GITHUB
        github_url = f"https://raw.githubusercontent.com/WandesonMarcone/icones-bolsabr/main/{pasta_tipo_nome}/{ticker.upper()}.png"
        resp = requests.get(github_url, timeout=10)

        # 3. SE O GITHUB FALHAR, TENTA NO LOGO.DEV
        if resp.status_code != 200:
            logo_dev_token = os.environ.get("LOGO_DEV_TOKEN")
            if logo_dev_token:
                logo_dev_url = f"https://img.logo.dev/ticker:{ticker.upper()}.SA?token={logo_dev_token}"
                resp = requests.get(logo_dev_url, timeout=10)

        # 4. SE ACHOU A IMAGEM EM ALGUM LUGAR, SALVA NO DRIVE
        if resp.status_code == 200 and 'image' in resp.headers.get('Content-Type', '').lower():
            # Salva no Drive e retorna o link
            link = drive_manager.upload_imagem_logo(
                resp.content, 
                f"{ticker.upper()}.png", 
                root_id
            )
            return link.replace("view?usp=drivesdk", "uc?export=view") # Formata para link direto

    except Exception as e:
        print(f"Erro ao processar logo de {ticker}: {e}")

    return ""

# ==========================================
# O NOVO MOTOR DE DASHBOARD (Arquitetura)
# ==========================================
def _buscar_dados_planilha(ticker, is_fii):
    """Busca dados reais na planilha e retorna um dicionário limpo"""
    try:
        planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
        nome_aba = "BD_FIIs" if is_fii else "BD_Acoes"
        aba = planilha.worksheet(nome_aba)
        
        # Procura a célula na Coluna A (Ticker)
        cell = aba.find(ticker)
        if not cell: return None
        
        # Pega a linha inteira da planilha
        row = aba.row_values(cell.row)
        
        if is_fii:
            # Mapeamento para FIIs (Baseado na sua lista de 16 colunas)
            return {
                "tipo": row[1],    # Coluna B
                "setor": row[2],   # Coluna C
                "preco": row[3],   # Coluna D
                "pvp": row[5],     # Coluna F
                "dy": row[6],      # Coluna G
                "vpa": row[13],    # Coluna N
                "raw": row         # Guarda a linha toda caso precise de detalhes
            }
        else:
            # Mapeamento para Ações (Baseado na sua lista de 32 colunas)
            # Obs: row[0] é o ticker, então o índice na planilha é (lista + 1)
            return {
                "setor": row[1],   # Coluna B
                "preco": row[2],   # Coluna C
                "dy": row[3],      # Coluna D
                "pl": row[5],      # Coluna F
                "pvp": row[6],     # Coluna G
                "roe": row[19],    # Coluna T
                "raw": row         # Guarda a linha toda
            }
    except Exception as e:
        print(f"Erro ao buscar na planilha: {e}")
        return None

def gerar_painel_ativo(ticker, tipo, chat_id, message_id=None):
    """Gera a mensagem principal com os botões interativos e dados em tempo real"""
    is_fii = (tipo == 'fii')
    icone = "🏢 Fundo" if is_fii else "📈 Ação"
    voltar_cmd = "menu_fiis" if is_fii else "menu_acoes"

    # 1. Puxar as Logos e Dados Reais da Planilha
    url_logo = obter_link_logo(ticker, tipo)
    indicadores = _buscar_dados_planilha(ticker, is_fii)

    # Tratamento de erro caso o ativo não esteja na planilha
    if not indicadores:
        msg_erro = f"❌ Erro: Não encontrei dados para **{ticker}** na planilha."
        if message_id:
            bot.edit_message_text(msg_erro, chat_id, message_id, parse_mode="Markdown")
        else:
            bot.send_message(chat_id, msg_erro, parse_mode="Markdown")
        return

    # 2. Resumo da IA (Placeholder - futuramente puxar de module_ia)
    resumo_ia = f"Ativo monitorado do setor {indicadores.get('setor', 'Geral')}. Focado na geração de valor no mercado brasileiro."

    # 3. Montar a tela exata da sua arquitetura
    # O [\u200c] é o link invisível para renderizar a logo no topo
    link_invisivel = f"[\u200c]({url_logo})" if url_logo else ""

    # Formatação condicional baseada no tipo de ativo
    if is_fii:
        texto = (
            f"{link_invisivel}{icone}: **{ticker}**\n"
            f"📝 **Resumo:** _{resumo_ia}_\n\n"
            f"💰 **Preço:** R$ {indicadores.get('preco', 'N/A')}\n"
            f"💸 **Dividend Yield:** {indicadores.get('dy', 'N/A')}\n"
            f"⚖️ **P/VP:** {indicadores.get('pvp', 'N/A')}\n"
            f"💵 **VPA:** {indicadores.get('vpa', 'N/A')}"
        )
    else:
        texto = (
            f"{link_invisivel}{icone}: **{ticker}**\n"
            f"📝 **Resumo:** _{resumo_ia}_\n\n"
            f"💰 **Preço:** R$ {indicadores.get('preco', 'N/A')}\n"
            f"💸 **Dividend Yield:** {indicadores.get('dy', 'N/A')}\n"
            f"📊 **P/L:** {indicadores.get('pl', 'N/A')} | ⚖️ **P/VP:** {indicadores.get('pvp', 'N/A')}\n"
            f"📈 **ROE:** {indicadores.get('roe', 'N/A')}"
        )

    # 4. Criar os Botões (Submenus)
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📎 Dados Importantes", callback_data=f"dados_{ticker}_{tipo}"),
        InlineKeyboardButton("📑 Documentos", callback_data=f"docs_{ticker}_{tipo}")
    )
    markup.add(InlineKeyboardButton("⚠️ Análise de IA", callback_data=f"ia_{ticker}_{tipo}"))
    markup.add(InlineKeyboardButton(f"🔙 Voltar aos {icone.split()[1]}s", callback_data=voltar_cmd))

    # 5. Enviar ou Editar
    if message_id:
        bot.edit_message_text(texto, chat_id, message_id, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=False)
    else:
        bot.send_message(chat_id, texto, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=False)


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
                "O robô monitora e processa dados da CVM e B3.\n\n"
                "📌 *Comandos Rápidos:*\n"
                "`/status` - Saúde do BD SQLite\n"
                "`/relatorios` - Últimos PDFs\n"
                "`/adicionar TICKER` - Insere ativos\n\n"
                "📊 *Nova Arquitetura:*\n"
                "- Resumo IA, Indicadores (P/L, P/VP, DY)\n"
                "- Submenus de Documentos e Análise IA."
            )
            bot.edit_message_text(texto_ajuda, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        elif dados == "ver_logs":
            bot.answer_callback_query(call.id, "A buscar logs...")
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("🔙 Voltar para Ajuda", callback_data="menu_ajuda"))
            bot.edit_message_text("📜 *Histórico de Logs:* \n[Integração futura...]", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        elif dados == "menu_macro":
            bot.answer_callback_query(call.id, "🌍 Coletando dados...")
            resultado = module_macro.obter_dados_macro()
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="voltar_menu"))
            bot.edit_message_text(resultado, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # --- MENU PRINCIPAL FIIs (Dinâmico) ---
        elif dados == "menu_fiis":
            bot.answer_callback_query(call.id, "Carregando FIIs...")
            markup = InlineKeyboardMarkup(row_width=2)
            
            # 1. Botões Estáticos (Sempre presentes)
            markup.add(
                InlineKeyboardButton("⭐ Meus Favoritos", callback_data="favoritos_fiis"),
                InlineKeyboardButton("🔥 Oportunidades", callback_data="oportunidades_fiis")
            )
            
            # 2. Botões Dinâmicos (Setores/Segmentos da Planilha)
            try:
                planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
                aba = planilha.worksheet("BD_FIIs")
                matriz = aba.get_all_values()
                
                # Identifica coluna de setor (assumindo que você usa "Segmento" ou "Tipo")
                cabecalhos = [c.lower().strip() for c in matriz[0]]
                idx = next((i for i, c in enumerate(cabecalhos) if c in ["setor", "segmento", "tipo"]), -1)
                
                if idx != -1:
                    setores = sorted(list(set(linha[idx].strip() for linha in matriz[1:] if linha[idx].strip())))
                    for s in setores:
                        markup.add(InlineKeyboardButton(f"📁 {s}", callback_data=f"setor_fii_{s[:12]}"))
            except Exception as e:
                print(f"Erro ao ler setores: {e}")

            markup.add(InlineKeyboardButton("🔙 Voltar ao Início", callback_data="voltar_menu"))
            bot.edit_message_text("🏢 *Módulo FIIs*\nSelecione uma categoria ou favorito:", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # --- MENU PRINCIPAL AÇÕES (Dinâmico) ---
        elif dados == "menu_acoes":
            bot.answer_callback_query(call.id, "Carregando Ações...")
            markup = InlineKeyboardMarkup(row_width=2)
            
            markup.add(
                InlineKeyboardButton("⭐ Minhas Favoritas", callback_data="favoritos_acoes"),
                InlineKeyboardButton("🔥 Oportunidades", callback_data="oportunidades_acoes")
            )
            
            try:
                planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
                aba = planilha.worksheet("BD_Acoes")
                matriz = aba.get_all_values()
                
                cabecalhos = [c.lower().strip() for c in matriz[0]]
                idx = next((i for i, c in enumerate(cabecalhos) if c in ["setor", "segmento", "tipo"]), -1)
                
                if idx != -1:
                    setores = sorted(list(set(linha[idx].strip() for linha in matriz[1:] if linha[idx].strip())))
                    for s in setores:
                        markup.add(InlineKeyboardButton(f"📁 {s}", callback_data=f"setor_acao_{s[:12]}"))
            except Exception as e:
                print(f"Erro ao ler setores: {e}")

            markup.add(InlineKeyboardButton("🔙 Voltar ao Início", callback_data="voltar_menu"))
            bot.edit_message_text("📈 *Módulo de Ações*\nSelecione um setor ou favorita:", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # ==========================================
        # GERADORES DE BOTÕES DINÂMICOS (FAVORITOS FIXOS)
        # ==========================================
        elif dados == "favoritos_fiis":
            markup = InlineKeyboardMarkup(row_width=3)
            botoes = [InlineKeyboardButton(ticker, callback_data=f"fii_{ticker}") for ticker in config.FIXAS_FIIS]
            markup.add(*botoes)
            markup.add(InlineKeyboardButton("🔙 Voltar", callback_data="menu_fiis"))
            bot.edit_message_text("⭐ *Seus FIIs Favoritos*\nSelecione um ativo:", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        elif dados == "favoritos_acoes":
            markup = InlineKeyboardMarkup(row_width=3)
            botoes = [InlineKeyboardButton(ticker, callback_data=f"acao_{ticker}") for ticker in config.FIXAS_ACOES]
            markup.add(*botoes)
            markup.add(InlineKeyboardButton("🔙 Voltar", callback_data="menu_acoes"))
            bot.edit_message_text("⭐ *Suas Ações Favoritas*\nSelecione um ativo:", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")



        # ==========================================
        # LISTAR ATIVOS DENTRO DE UM SETOR ESPECÍFICO
        # ==========================================
        elif dados.startswith("setor_fii_") or dados.startswith("setor_acao_"):
            bot.answer_callback_query(call.id, "Buscando ativos desta categoria...")
            is_fii = True if "setor_fii_" in dados else False
            nome_aba = "BD_FIIs" if is_fii else "BD_Acoes"
            prefixo_ticker = "fii" if is_fii else "acao"
            menu_voltar = "menu_fiis" if is_fii else "menu_acoes"
            
            # Pega o nome do setor que o usuário clicou (ex: "Tijolo")
            setor_buscado = dados.split("_", 2)[2] 

            try:
                planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
                aba = planilha.worksheet(nome_aba)
                matriz = aba.get_all_values()
                
                # Identifica a coluna do setor de novo
                cabecalhos = [c.lower().strip() for c in matriz[0]]
                indice_setor = next(i for i, col in enumerate(cabecalhos) if col in ["setor", "segmento", "tipo", "classificação"])

                # Puxa todos os Tickers (Coluna A) que batem com o setor clicado
                tickers_encontrados = []
                for linha in matriz[1:]:
                    if len(linha) > indice_setor and linha[indice_setor].strip()[:12] == setor_buscado:
                        tickers_encontrados.append(linha[0].strip())
                
                markup = InlineKeyboardMarkup(row_width=3)
                botoes = [InlineKeyboardButton(tkr, callback_data=f"{prefixo_ticker}_{tkr}") for tkr in tickers_encontrados]
                
                if botoes:
                    markup.add(*botoes)
                    texto = f"📂 *Ativos - {setor_buscado}*\nSelecione para abrir o terminal:"
                else:
                    texto = f"📭 Nenhum ativo encontrado nesta categoria."
                
                markup.add(InlineKeyboardButton("🔙 Voltar", callback_data=menu_voltar))
                bot.edit_message_text(texto, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

            except Exception as e:
                bot.edit_message_text(f"❌ Erro ao ler ativos: {e}", chat_id, msg_id)

        # ==========================================
        # OPORTUNIDADES (Via Filtros Dinâmicos)
        # ==========================================
        elif dados in ["oportunidades_fiis", "oportunidades_acoes"]:
            bot.answer_callback_query(call.id, "Analisando o mercado...")
            
            # Identifica o tipo baseado no botão clicado
            is_fii = (dados == "oportunidades_fiis")
            tipo = "fii" if is_fii else "acao"
            menu_voltar = "menu_fiis" if is_fii else "menu_acoes"
            
            try:
                # 1. Busca os ativos que passaram no filtro atual (filtros.json)
                oportunidades = buscar_oportunidades(tipo)
                
                markup = InlineKeyboardMarkup(row_width=3)
                
                # Se achou oportunidades, cria os botões para cada uma
                if oportunidades:
                    # Limita a 15 botões para não estourar a tela do Telegram
                    top_oportunidades = oportunidades[:15] 
                    
                    # Gera os botões dos tickers (ex: callback "fii_HGLG11" ou "acao_WEGE3")
                    botoes_ativos = [InlineKeyboardButton(tkr, callback_data=f"{tipo}_{tkr}") for tkr in top_oportunidades]
                    markup.add(*botoes_ativos)
                    
                    texto = (
                        f"🔥 *Top Oportunidades ({'FIIs' if is_fii else 'Ações'})*\n\n"
                        f"Estes ativos passaram na sua peneira de filtros. Selecione para ver o terminal completo:"
                    )
                else:
                    texto = "📭 *Nenhuma oportunidade encontrada.*\n\nNenhum ativo atendeu aos critérios rigorosos do seu filtro atual."
                
                # 2. Adiciona os botões de gestão na parte inferior
                markup.row(InlineKeyboardButton("✏️ Editar Filtros", callback_data=f"editar_{tipo}"))
                markup.row(InlineKeyboardButton("🔙 Voltar", callback_data=menu_voltar))
                
                bot.edit_message_text(texto, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")
                
            except Exception as e:
                print(f"Erro ao carregar oportunidades: {e}")
                markup = InlineKeyboardMarkup()
                markup.add(InlineKeyboardButton("🔙 Voltar", callback_data=menu_voltar))
                bot.edit_message_text(f"❌ Erro ao aplicar os filtros do sistema.\nVerifique se o `filtros.json` está correto.", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # ==========================================
        # ABRIR TELA DO ATIVO (GARE11, PETR4, etc)
        # ==========================================
        # =======================================================
        # 1. PAINEL PRINCIPAL DO ATIVO
        # =======================================================
        elif dados.startswith("fii_") or dados.startswith("acao_"):
            partes = dados.split("_")
            tipo = partes[0] 
            ticker = partes[1]
            bot.answer_callback_query(call.id, f"Carregando terminal de {ticker}...")
            # Essa função você já configurou! Ela vai buscar a logo e o resumo.
            gerar_painel_ativo(ticker, tipo, chat_id, msg_id)

        # =======================================================
        # 2. SUBMENU: DADOS COMPLETOS (Puxa da sua Planilha)
        # =======================================================
        elif dados.startswith("dados_"):
            bot.answer_callback_query(call.id, "Buscando indicadores...")
            partes = dados.split("_")
            ticker, tipo = partes[1], partes[2]
            is_fii = (tipo == "fii")
            
            # Puxa os dados reais da sua função recém-criada
            indicadores = _buscar_dados_planilha(ticker, is_fii)
            
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(f"🔙 Voltar para {ticker}", callback_data=f"{tipo}_{ticker}"))
            
            if not indicadores:
                bot.edit_message_text(f"❌ Não encontrei os dados detalhados de **{ticker}** na planilha.", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")
            else:
                # Monta um relatório robusto baseado no tipo do ativo
                if is_fii:
                    texto = (
                        f"📎 **Dados Completos: {ticker}**\n\n"
                        f"🏢 **Setor:** {indicadores.get('setor', 'N/A')}\n"
                        f"💰 **Preço:** R$ {indicadores.get('preco', 'N/A')}\n"
                        f"⚖️ **P/VP:** {indicadores.get('pvp', 'N/A')}\n"
                        f"💸 **DY (12m):** {indicadores.get('dy', 'N/A')}\n"
                        f"💵 **Valor Patrimonial (VPA):** {indicadores.get('vpa', 'N/A')}\n\n"
                        f"_(Você pode mapear mais colunas lá no dicionário da função _buscar_dados_planilha)_"
                    )
                else:
                    texto = (
                        f"📎 **Dados Completos: {ticker}**\n\n"
                        f"📈 **Setor:** {indicadores.get('setor', 'N/A')}\n"
                        f"💰 **Preço:** R$ {indicadores.get('preco', 'N/A')}\n"
                        f"📊 **P/L:** {indicadores.get('pl', 'N/A')}\n"
                        f"⚖️ **P/VP:** {indicadores.get('pvp', 'N/A')}\n"
                        f"💸 **DY (12m):** {indicadores.get('dy', 'N/A')}\n"
                        f"🚀 **ROE:** {indicadores.get('roe', 'N/A')}\n\n"
                        f"_(Você pode mapear mais colunas lá no dicionário da função _buscar_dados_planilha)_"
                    )
                bot.edit_message_text(texto, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # =======================================================
        # 3. SUBMENU: DOCUMENTOS (Links Dinâmicos Inteligentes)
        # =======================================================
        elif dados.startswith("docs_"):
            partes = dados.split("_")
            ticker, tipo = partes[1], partes[2]
            markup = InlineKeyboardMarkup()
            
            # Truque: Como não temos um PDF para cada ativo na planilha ainda,
            # nós geramos links automáticos para o StatusInvest e Fundamentus!
            categoria_status = "fundos-imobiliarios" if tipo == "fii" else "acoes"
            link_statusinvest = f"https://statusinvest.com.br/{categoria_status}/{ticker.lower()}"
            link_fundamentus = f"https://www.fundamentus.com.br/detalhes.php?papel={ticker}"
            
            markup.row(InlineKeyboardButton("📊 Ver no StatusInvest", url=link_statusinvest))
            markup.row(InlineKeyboardButton("📈 Ver no Fundamentus", url=link_fundamentus))
            markup.add(InlineKeyboardButton(f"🔙 Voltar para {ticker}", callback_data=f"{tipo}_{ticker}"))
            
            texto_docs = (
                f"📑 **Central de Documentos: {ticker}**\n\n"
                f"Acesse os portais abaixo para ler os relatórios gerenciais, balanços oficiais e fatos relevantes atualizados do ativo."
            )
            bot.edit_message_text(texto_docs, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)

        # =======================================================
        # 4. SUBMENU: ANÁLISE DE IA (Placeholder de Luxo)
        # =======================================================
        elif dados.startswith("ia_"):
            bot.answer_callback_query(call.id, "Gerando análise avançada...")
            partes = dados.split("_")
            ticker, tipo = partes[1], partes[2]
            
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(f"🔙 Voltar para {ticker}", callback_data=f"{tipo}_{ticker}"))
            
            # Um aviso profissional até você conectar a API do Gemini/OpenAI
            texto_ia = (
                f"⚠️ **Análise de Inteligência Artificial: {ticker}**\n\n"
                f"🤖 _Módulo IA em Fase de Treinamento._\n\n"
                f"Em breve, o bot fará o cruzamento autônomo de:\n"
                f"🔹 Histórico de Dividendos vs Inflação\n"
                f"🔹 Vacância e Qualidade Física dos Imóveis\n"
                f"🔹 Notícias recentes e fatos relevantes\n"
                f"🔹 Risco de Alavancagem da Dívida\n\n"
                f"*(Aguardando integração final)*"
            )
            bot.edit_message_text(texto_ia, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # =======================================================
        # 5. SUBMENU: EDITAR FILTROS
        # =======================================================
        elif dados.startswith("editar_"):
            tipo = dados.split("_")[1] 

            msg = bot.edit_message_text(
                f"📝 *Edição de Filtros ({tipo.upper()})*\n"
                "Envie a alteração no formato: `chave: valor`\n"
                "Exemplos:\n"
                "- Para FIIs: `pvp_max: 1.10`\n"
                "- Para Ações: `pl_max: 15.0`",
                chat_id, msg_id, parse_mode="Markdown"
            )
            # Registra o próximo passo passando o 'tipo' como argumento
            bot.register_next_step_handler(msg, processar_novo_filtro, tipo)
    except Exception as e:
        print(f"Erro no callback: {e}")

# --- MENSAGEM DE REINÍCIO (FIIs E AÇÕES) ---
try:
    # Busca oportunidades de ambos
    opps_fii = buscar_oportunidades('fii')
    opps_acao = buscar_oportunidades('acao')

    # Cria strings legíveis (seguro caso estejam vazias)
    fii_str = ", ".join(opps_fii[:5]) if opps_fii else "Nenhuma encontrada."
    acao_str = ", ".join(opps_acao[:5]) if opps_acao else "Nenhuma encontrada."

    msg = (
        "🚀 *Bot Reiniciado com sucesso!*\n\n"
        f"🏢 *Oportunidades FIIs:* {fii_str}\n\n"
        f"📈 *Oportunidades Ações:* {acao_str}"
    )
    bot.send_message(config.TELEGRAM_CHAT_ID, msg, parse_mode="Markdown")
except Exception as e:
    print(f"Erro ao enviar aviso de reinício: {e}")

# ==========================================
# ROTINA DIÁRIA AUTOMÁTICA (O Despertador Mestre de Documentos)
# ==========================================
def varredura_diaria():
    """Função que o agendador chama todos os dias às 08h00 para buscar PDFs"""
    bot.send_message(config.TELEGRAM_CHAT_ID, "⚙️ *Bom dia! Iniciando a varredura automática de documentos...*", parse_mode="Markdown")
    
    # ------------------------------------------
    # 1. ETAPA FIIs (Fnet / B3)
    # ------------------------------------------
    try:
        bot.send_message(config.TELEGRAM_CHAT_ID, "🏢 Buscando novos Relatórios de FIIs na B3...")
        
        # Chama o nosso Maestro que lê a planilha e baixa tudo!
        qtd_fiis_salvos = rotina_de_atualizacao_em_massa()
        
        bot.send_message(config.TELEGRAM_CHAT_ID, f"✅ B3 finalizada! {qtd_fiis_salvos} novos documentos de FIIs salvos no Google Drive.")
    except Exception as e:
        bot.send_message(config.TELEGRAM_CHAT_ID, f"❌ Erro na varredura da B3: {e}")

    # ------------------------------------------
    # 2. ETAPA AÇÕES (Documentos CVM)
    # ------------------------------------------
    try:
        bot.send_message(config.TELEGRAM_CHAT_ID, "📈 Iniciando coleta de documentos e balanços de Ações na CVM...")
        
        # Aqui chamamos o coletor CORRETO (o arquivista de PDFs)
        # Substitua 'rodar_coleta' pelo nome exato da função que dispara o seu coletor_cvm
        coletor_cvm.rodar_coleta() 
        
        bot.send_message(config.TELEGRAM_CHAT_ID, "✅ CVM finalizada com sucesso! Novos PDFs de ações salvos.")
    except Exception as e:
        bot.send_message(config.TELEGRAM_CHAT_ID, f"❌ Erro na varredura de documentos da CVM: {e}")
        
    # Encerramento
    bot.send_message(config.TELEGRAM_CHAT_ID, "🏁 *Todas as rotinas finalizadas! O cofre de documentos está 100% atualizado para hoje.*", parse_mode="Markdown")

# ==========================================
# LIGANDO O AGENDADOR DE TAREFAS
# ==========================================
fuso_horario = pytz.timezone('America/Sao_Paulo')
scheduler = BackgroundScheduler(timezone=fuso_horario)

# Agenda a função unificada de documentos
scheduler.add_job(varredura_diaria, CronTrigger(day_of_week='mon-fri', hour=8, minute=0))

# Se você quiser adicionar o agendamento do module_cvm (para rodar 4x ao dia), 
# você pode fazer isso criando uma nova função e um novo 'scheduler.add_job' aqui no futuro!

scheduler.start()

if __name__ == '__main__':
    print("Bot rodando e agendador ativado!")
    bot.polling(none_stop=True)