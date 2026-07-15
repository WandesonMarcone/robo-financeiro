import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import io
import json
import requests
import os
from flask import Flask, request
from sqlalchemy import func, create_engine
from sqlalchemy.orm import sessionmaker
import dropbox # Necessário para tratar exceções da Logo

import config
from modules.utils import conectar_gspread
from modules import module_cvm
from modules import module_ia
from modules import module_macro
from modules.dropbox_manager import autenticar_dropbox # Importando o seu motor blindado
from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos

# ==========================================
# CONFIGURAÇÃO FILTRO OPORTUNIDADE🚀
# ==========================================
import json

def carregar_filtros():
    with open('filtros.json', 'r') as f:
        return json.load(f)

def salvar_filtros(filtros):
    with open('filtros.json', 'w') as f:
        json.dump(filtros, f, indent=4)

def buscar_oportunidades(tipo):
    """tipo deve ser 'fii' ou 'acao'"""
    filtros = carregar_filtros()[tipo]
    # Aqui entra o seu código que carrega o DataFrame (df)
    # Exemplo: df = carregar_planilha_para_dataframe(tipo)
    
    if tipo == 'fii':
        return df[
            (df['P/VP'] >= filtros['pvp_min']) & (df['P/VP'] <= filtros['pvp_max']) &
            (df['Dividend Yield'] >= filtros['dy_min']) &
            (df['Liquidez'] >= filtros['liq_min']) &
            (df['Vacância Média'] <= filtros['vac_max'])
        ].index.tolist()
    else: # Ação
        return df[
            (df['P/L'] >= filtros['pl_min']) & (df['P/L'] <= filtros['pl_max']) &
            (df['P/VP'] >= filtros['pvp_min']) & (df['P/VP'] <= filtros['pvp_max']) &
            (df['Div.Yield'] >= filtros['dy_min']) &
            (df['ROE'] >= filtros['roe_min'])
        ].index.tolist()

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
# MOTOR DE LOGOS (Dropbox -> GitHub -> Logo.dev)
# ==========================================
def obter_link_logo(ticker, tipo):
    """
    Tenta buscar a logo em cascata:
    1. Dropbox (Cache local super rápido)
    2. GitHub (Repositório do Wandeson)
    3. Logo.dev (API Premium)
    Se encontrar no Github ou Logo.dev, salva no Dropbox para a próxima vez.
    """
    try:
        dbx = autenticar_dropbox()
        if not dbx: return ""

        pasta_tipo = "fiis" if tipo == "fii" else "acoes"
        caminho_dropbox = f"/Terminal_Institucional/Logos/{pasta_tipo}/{ticker.upper()}.png"
        
        # 1. TENTA BUSCAR DO DROPBOX (O Cache)
        try:
            links = dbx.sharing_list_shared_links(path=caminho_dropbox, direct_only=True).links
            if links:
                return links[0].url.replace("?dl=0", "?raw=1")
        except:
            pass # Se não existe, a gente segue para o passo 2
            
        # 2. TENTA BAIXAR DO GITHUB
        github_url = f"https://raw.githubusercontent.com/WandesonMarcone/icones-bolsabr/main/{pasta_tipo}/{ticker.upper()}.png"
        resp = requests.get(github_url, timeout=10)
        
        # 3. SE O GITHUB FALHAR (Erro 404), TENTA NO LOGO.DEV
        if resp.status_code != 200:
            logo_dev_token = os.environ.get("LOGO_DEV_TOKEN")
            if logo_dev_token:
                # O formato padrão para ativos da B3 em APIs globais costuma usar o sufixo .SA
                logo_dev_url = f"https://img.logo.dev/ticker:{ticker.upper()}.SA?token={logo_dev_token}"
                resp = requests.get(logo_dev_url, timeout=10)
                
        # 4. SE ACHOU A IMAGEM EM ALGUM LUGAR, SALVA NO DROPBOX E GERA O LINK
        if resp.status_code == 200 and 'image' in resp.headers.get('Content-Type', '').lower():
            dbx.files_upload(resp.content, caminho_dropbox, mode=dropbox.files.WriteMode("overwrite"))
            link = dbx.sharing_create_shared_link_with_settings(caminho_dropbox)
            return link.url.replace("?dl=0", "?raw=1")
            
    except Exception as e:
        print(f"Erro ao processar logo de {ticker}: {e}")
        
    return "" # Se a logo não existir em nenhuma das 3 fontes, retorna vazio


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
        # OPORTUNIDADES (Via Scrapers)
        # ==========================================
        elif dados in ["oportunidades_fiis", "oportunidades_acoes"]:
            bot.answer_callback_query(call.id, "Rodando filtros do Scraper...")
            # TODO: Conectar com o seu módulo de scraper_fiis/acoes no futuro
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("🔙 Voltar", callback_data="menu_fiis" if "fiis" in dados else "menu_acoes"))
            bot.edit_message_text("🔥 *Módulo de Oportunidades*\n_Integração com os filtros do scraper em construção._", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # ==========================================
        # ABRIR TELA DO ATIVO (GARE11, PETR4, etc)
        # ==========================================
        elif dados.startswith("fii_") or dados.startswith("acao_"):
            partes = dados.split("_")
            tipo = partes[0] 
            ticker = partes[1]
            bot.answer_callback_query(call.id, f"Carregando terminal de {ticker}...")
            gerar_painel_ativo(ticker, tipo, chat_id, msg_id)

        # ... (Mantém os submenus "dados_", "docs_" e "ia_") ...
        elif dados.startswith("dados_"):
            partes = dados.split("_")
            ticker, tipo = partes[1], partes[2]
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(f"🔙 Voltar para {ticker}", callback_data=f"{tipo}_{ticker}"))
            bot.edit_message_text(f"📎 **Dados Completos: {ticker}**\n\n_(Aqui o bot puxará toda a linha do Google Sheets)_", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        elif dados.startswith("docs_"):
            partes = dados.split("_")
            ticker, tipo = partes[1], partes[2]
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("📄 Relatório Gerencial (Julho)", url="https://dropbox.com/link_aqui"))
            markup.add(InlineKeyboardButton(f"🔙 Voltar para {ticker}", callback_data=f"{tipo}_{ticker}"))
            bot.edit_message_text(f"📑 **Central de Documentos: {ticker}**", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        elif dados.startswith("ia_"):
            bot.answer_callback_query(call.id, "Gerando análise avançada...")
            partes = dados.split("_")
            ticker, tipo = partes[1], partes[2]
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(f"🔙 Voltar para {ticker}", callback_data=f"{tipo}_{ticker}"))
            texto_ia = f"⚠️ **Análise de Risco: {ticker}**\n\n🔹 **Alavancagem:** (Conectar IA)"
            bot.edit_message_text(texto_ia, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

    except Exception as e:
        print(f"Erro no callback: {e}")

# ==========================================
# 4. HANDLERS ISOLADOS (Edição de Filtros)
# ==========================================
# --- ACIONAR EDIÇÃO (Botões: editar_fii ou editar_acao) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("editar_"))
def editar_filtros(call):
    # Extrai o tipo baseado no callback (ex: editar_fii -> tipo = 'fii')
    tipo = call.data.split("_")[1] 
    
    msg = bot.edit_message_text(
        f"📝 *Edição de Filtros ({tipo.upper()})*\n"
        "Envie a alteração no formato: `chave: valor`\n"
        "Exemplos:\n"
        "- Para FIIs: `pvp_max: 1.10`\n"
        "- Para Ações: `pl_max: 15.0`",
        call.message.chat.id, call.message.message_id, parse_mode="Markdown"
    )
    # Registra o próximo passo passando o 'tipo' como argumento
    bot.register_next_step_handler(msg, processar_novo_filtro, tipo)

def processar_novo_filtro(message, tipo):
    try:
        # Validação simples
        if ":" not in message.text:
            raise ValueError("Formato incorreto")

        chave, valor = message.text.split(':')
        chave = chave.strip()
        valor = float(valor.strip())

        # Carrega, altera e salva
        filtros = carregar_filtros()
        
        # Verifica se a chave existe antes para evitar erros de digitação
        if chave in filtros[tipo]:
            filtros[tipo][chave] = valor
            salvar_filtros(filtros)
            bot.reply_to(message, f"✅ {chave.upper()} ({tipo.upper()}) atualizado para {valor}!")
        else:
            bot.reply_to(message, f"❌ Chave '{chave}' não encontrada. Verifique o nome no filtros.json.")
            
    except Exception as e:
        bot.reply_to(message, "❌ Erro. Use formato: `chave: valor` (ex: `dy_min: 0.08`)")

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

if __name__ == '__main__':
    bot.polling(none_stop=True)