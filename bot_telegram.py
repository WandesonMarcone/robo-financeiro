import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import io
import json
import requests
import os
import time
import config
import threading
import pytz # Para lidar com o fuso horário do Brasil
from sqlalchemy import text # IMPORTANTE: Adicione essa linha no topo!
from flask import Flask, request
from sqlalchemy import func, create_engine
from sqlalchemy.orm import sessionmaker
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
from pipeline_dados.coletor_cvm import AcoesCVMReader
# Importe o SessionDB do local onde você o definiu originalmente (ex: atualizador_documentos ou o arquivo de config)
from atualizador_documentos import SessionDB  

# ==========================================
# CONFIGURAÇÕES INICIAIS
# ==========================================
drive_manager = GoogleDriveManager()
import os
from sqlalchemy import create_engine

# Pega o banco das variáveis do sistema 
url_banco = os.environ.get('DATABASE_URL', 'sqlite:///pipeline_dados/banco_institucional.db')

# Corrige o prefixo caso o Render mande postgres:// em vez de postgresql://
if url_banco.startswith("postgres://"):
    url_banco = url_banco.replace("postgres://", "postgresql://", 1)

engine = create_engine(url_banco)

SessionDB = sessionmaker(bind=engine)

# Logo abaixo de SessionDB = sessionmaker(bind=engine)
from pipeline_dados.banco_dados import Base # Importe a sua Base declarativa

# Garante que as tabelas sejam criadas se não existirem
Base.metadata.create_all(engine)
print("✅ Banco de dados verificado e tabelas criadas com sucesso!")

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

@bot.message_handler(commands=['inspecionar_banco'])
def comando_inspecionar(message):
    import sqlite3
    caminho_db = "pipeline_dados/banco_institucional.db"
    try:
        conn = sqlite3.connect(caminho_db)
        cursor = conn.cursor()
        # Pega os nomes das colunas da tabela
        cursor.execute("PRAGMA table_info(documentos_qualitativos)")
        colunas = cursor.fetchall()
        
        nomes = [c[1] for c in colunas]
        bot.send_message(message.chat.id, f"🔍 Colunas encontradas no banco:\n{', '.join(nomes)}")
        conn.close()
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Erro: {str(e)}")


@bot.message_handler(commands=['migrar_db'])
def migrar_db(message):
    try:
        # Executa o comando de alteração diretamente no PostgreSQL
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE documentos_qualitativos ALTER COLUMN tipo_documento TYPE VARCHAR(255);"))
            conn.commit()
        bot.send_message(message.chat.id, "✅ Sucesso! Coluna 'tipo_documento' expandida para 255 caracteres.")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Erro ao migrar: {str(e)}")

# ==========================================
# COMANDO: FNET/B3  (/auditar) (/mapear_nomes)
# ==========================================
import requests
import json

@bot.message_handler(commands=['auditar'])
def comando_auditoria_fnet(message):
    bot.send_message(message.chat.id, "⏳ Iniciando sondagem profunda na API da B3...")
    
    url = "https://fnet.bmfbovespa.com.br/fnet/publico/pesquisarGerenciadorDocumentosDados"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'
    }
    params = {
        'd': '1', 's': '0', 'l': '1', # Pegando só o 1º documento mais recente
        'tipoFundo': '1'
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        dados = response.json().get('data', [])
        
        if dados:
            # Transforma o JSON em texto bonito com indentação
            json_formatado = json.dumps(dados[0], indent=2, ensure_ascii=False)
            
            # O Telegram tem limite de 4096 caracteres por mensagem, então cortamos se for gigante
            if len(json_formatado) > 4000:
                json_formatado = json_formatado[:3900] + "\n... [CORTADO POR TAMANHO]"
                
            resposta_telegram = f"🚨 **JSON COMPLETO (Sondagem FNET)** 🚨\n\n```json\n{json_formatado}\n```"
            bot.send_message(message.chat.id, resposta_telegram, parse_mode="Markdown")
        else:
            bot.send_message(message.chat.id, "❌ Nenhum dado retornado pela B3.")
            
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Erro na auditoria: {str(e)}")

@bot.message_handler(commands=['mapear_nomes'])
def comando_mapear_nomes_b3(message):
    import time
    import requests
    import threading # ⬅️ A CHAVE DA SOLUÇÃO (Permite rodar em segundo plano)
    
    # 1. O bot responde na mesma hora, acalmando o servidor do Telegram
    bot.send_message(message.chat.id, "🕵️‍♂️ Comando recebido! Como a B3 é lenta, enviei essa tarefa para o segundo plano. Pode continuar usando o Telegram normalmente, te enviarei o arquivo TXT assim que estiver pronto.")
    
    # 2. Definimos a tarefa pesada (A auditoria real)
    def tarefa_pesada():
        url = "https://fnet.bmfbovespa.com.br/fnet/publico/pesquisarGerenciadorDocumentosDados"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'}
        nomes_unicos = set()
        
        try:
            for start in range(0, 5000, 50):
                params = {'d': '1', 's': str(start), 'l': '50', 'tipoFundo': '1'}
                
                sucesso = False
                for tentativa in range(3):
                    try:
                        res = requests.get(url, params=params, headers=headers, timeout=45)
                        res.raise_for_status() 
                        data = res.json().get('data', [])
                        sucesso = True
                        break 
                    except Exception as e:
                        time.sleep(2) 
                
                if not sucesso:
                    bot.send_message(message.chat.id, f"⚠️ Aviso: A B3 travou na página {start}. O arquivo será gerado com o que consegui até agora.")
                    break
                    
                if not data:
                    break
                    
                for item in data:
                    descricao = item.get('descricaoFundo', '').upper().strip()
                    if descricao:
                        nomes_unicos.add(descricao)
                        
                time.sleep(1.5) 
                
            lista_ordenada = sorted(list(nomes_unicos))
            texto_final = "\n".join(lista_ordenada)
            
            caminho_arquivo = "/tmp/nomes_b3_auditoria.txt"
            with open(caminho_arquivo, "w", encoding="utf-8") as f:
                f.write(f"--- CATÁLOGO DE NOMES DA B3 ({len(lista_ordenada)} fundos encontrados) ---\n\n")
                f.write(texto_final)
                
            with open(caminho_arquivo, "rb") as f:
                bot.send_document(message.chat.id, f, caption="🎯 Auditoria concluída em segundo plano! Aqui está a lista exata da B3.")
                
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Erro crítico na thread de mapeamento: {str(e)}")

    # 3. Dispara a tarefa pesada em uma Thread separada (Background)
    thread = threading.Thread(target=tarefa_pesada)
    thread.start()

@bot.message_handler(commands=['atualizar_banco'])
def comando_reforma_banco(message):
    import sqlite3
    
    bot.send_message(message.chat.id, "🏗️ Iniciando REFORMA GERAL para a arquitetura FNET...")
    caminho_db = "pipeline_dados/banco_institucional.db"
    
    try:
        conn = sqlite3.connect(caminho_db)
        cursor = conn.cursor()
        
        # 1. Renomeia a tabela velha
        cursor.execute("ALTER TABLE documentos_qualitativos RENAME TO documentos_qualitativos_old")
        
        # 2. Cria a nova tabela com TODAS as colunas novas (e url_pdf aceitando NULL)
        cursor.execute("""
            CREATE TABLE documentos_qualitativos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ativo_id INTEGER NOT NULL,
                data_publicacao DATE NOT NULL,
                tipo_documento VARCHAR(50) NOT NULL,
                url_pdf VARCHAR(500), 
                assunto VARCHAR(255),
                id_b3 VARCHAR(50),
                status_processamento VARCHAR(20) DEFAULT 'SALVO' NOT NULL,
                hash_sha256 VARCHAR(64),
                resumo_ia TEXT,
                log_erro TEXT,
                data_atualizacao DATETIME,
                FOREIGN KEY(ativo_id) REFERENCES ativos(id)
            )
        """)
        
        # 3. Copia os dados que já existiam para a casa nova
        try:
            cursor.execute("""
                INSERT INTO documentos_qualitativos (id, ativo_id, data_publicacao, tipo_documento, url_pdf, assunto)
                SELECT id, ativo_id, data_publicacao, tipo_documento, url_pdf, assunto FROM documentos_qualitativos_old
            """)
        except:
            pass # Se estiver vazia, não faz mal
            
        # 4. Destrói a tabela velha
        cursor.execute("DROP TABLE documentos_qualitativos_old")
        
        conn.commit()
        conn.close()
        
        bot.send_message(message.chat.id, "✅ Reforma Concluída com Sucesso! Todas as 12 colunas estão prontas. Por favor, reinicie o Render e rode o /forcar_varredura.")
        
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Erro na reforma: {str(e)}")

# ==========================================
# COMANDO: CVM (/testar_cvm)
# ==========================================
@bot.message_handler(commands=['testar_cvm'])
def comando_testar_cvm(message):
    from datetime import datetime # ⬅️ A CORREÇÃO ESTÁ AQUI
    bot.send_message(message.chat.id, "⚙️ Iniciando teste manual do Coletor CVM (Ano Atual)...")
    
    session = SessionDB() 
    try:
        coletor = AcoesCVMReader(session)
        coletor.atualizar_acoes(datetime.now().year)
        bot.send_message(message.chat.id, "✅ Coletor CVM rodou com sucesso!")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Erro no Coletor CVM: {str(e)}")
    finally:
        session.close() 

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

@bot.message_handler(commands=['reciclar_rejeitados'])
def comando_reciclar_rejeitados(message):
    bot.send_message(message.chat.id, "♻️ Buscando documentos rejeitados no banco...")
    session = SessionDB()
    try:
        # Busca todos que foram rejeitados pela regra antiga
        rejeitados = session.query(DocumentosQualitativos).filter(
            DocumentosQualitativos.status_processamento == 'REJEITADO_DUPLO_FATOR'
        ).all()
        
        contador = 0
        for doc in rejeitados:
            doc.status_processamento = 'PENDENTE' # Devolve para a fila!
            contador += 1
            
        session.commit()
        bot.send_message(message.chat.id, f"✅ {contador} documentos foram devolvidos para a fila de processamento!\n\nAgora sim, pode rodar o /forcar_varredura novamente!")
        
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Erro ao reciclar: {str(e)}")
    finally:
        session.close()

# ==========================================
# COMANDO SECRETO PARA TESTAR A VARREDURA
# ==========================================
@bot.message_handler(commands=['forcar_varredura'])
def acionar_varredura_manual(message):
    # 1. Responde instantaneamente para o Telegram e pro Render não darem Timeout
    bot.reply_to(message, "⚙️ *Iniciando varredura na B3 em segundo plano...*\nIsso pode levar alguns minutos. Pode continuar usando o bot normalmente, eu te aviso quando terminar!", parse_mode="Markdown")
    
    # 2. Cria a função pesada isolada
    def tarefa_pesada_background():
        try:
            from atualizador_documentos import rotina_de_atualizacao_em_massa
            relatorios_baixados = rotina_de_atualizacao_em_massa()
            
            # Quando terminar, envia uma nova mensagem avisando
            bot.send_message(message.chat.id, f"✅ *Varredura Concluída!*\n\n📥 Documentos inéditos salvos no Drive: **{relatorios_baixados}**", parse_mode="Markdown")
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ *Erro na varredura:* {e}", parse_mode="Markdown")

    # 3. Dá a ordem para o Python rodar isso em uma trilha separada (Thread)
    thread = threading.Thread(target=tarefa_pesada_background)
    thread.start()

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
                "vpa": row[14],    # Coluna N
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

def converter_numero(valor_string):
    """Limpa textos como 'R$ 1.050,50' ou '8,5%' da planilha e transforma em número puro"""
    try:
        texto = str(valor_string).replace('R$', '').replace('%', '').strip()
        if not texto or texto == '-': return 0.0
        if ',' in texto and '.' in texto:
            texto = texto.replace('.', '')
        texto = texto.replace(',', '.')
        return float(texto)
    except:
        return 0.0

def buscar_oportunidades(tipo):
    """Vasculha a planilha usando regras fixas hardcoded"""
    is_fii = (tipo == 'fii')
    nome_aba = "BD_FIIs" if is_fii else "BD_Acoes"

    # 🚨 REGRAS FIXAS DEFINIDAS AQUI 🚨
    FILTROS_FIXOS = {
        "fii": {"pvp_min": 0.50, "pvp_max": 1.15, "dy_min": 0.08},
        "acao": {"pl_min": 2.0, "pl_max": 15.0, "pvp_min": 0.50, "pvp_max": 2.50, "dy_min": 0.06, "roe_min": 0.10}
    }
    
    filtro_atual = FILTROS_FIXOS[tipo]

    try:
        planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
        aba = planilha.worksheet(nome_aba)
        matriz = aba.get_all_values()

        oportunidades = []

        for linha in matriz[1:]:
            try:
                ticker = linha[0].strip()
                if not ticker: continue

                if is_fii:
                    pvp = converter_numero(linha[5])
                    dy = converter_numero(linha[6])

                    dy_min = filtro_atual['dy_min']
                    if dy_min < 1 and dy >= 1: dy_min *= 100 

                    if (filtro_atual['pvp_min'] <= pvp <= filtro_atual['pvp_max']) and (dy >= dy_min):
                        oportunidades.append(ticker)
                else:
                    dy = converter_numero(linha[3])
                    pl = converter_numero(linha[5])
                    pvp = converter_numero(linha[6])
                    roe = converter_numero(linha[19])

                    dy_min = filtro_atual['dy_min']
                    if dy_min < 1 and dy >= 1: dy_min *= 100
                    roe_min = filtro_atual['roe_min']
                    if roe_min < 1 and roe >= 1: roe_min *= 100

                    if (filtro_atual['pl_min'] <= pl <= filtro_atual['pl_max']) and \
                       (filtro_atual['pvp_min'] <= pvp <= filtro_atual['pvp_max']) and \
                       (dy >= dy_min) and (roe >= roe_min):
                        oportunidades.append(ticker)

            except IndexError:
                pass 

        return oportunidades
    except Exception as e:
        print(f"Erro no filtro de oportunidades: {e}")
        return []

# ==========================================
# PAINEL DE APROVAÇÃO MANUAL (HUMAN-IN-THE-LOOP)
# ==========================================
@bot.callback_query_handler(func=lambda call: call.data.startswith('rev_'))
def processar_botao_revisao(call):
    # O call.data chega assim: rev_C_15_1abc123456789...
    partes = call.data.split('_', 3)
    acao = partes[1]    # 'C' (Confirmar) ou 'A' (Apagar)
    doc_id = partes[2]  # ID do documento no banco
    file_id = partes[3] # ID do arquivo no Google Drive
    
    bot.answer_callback_query(call.id, "Processando sua ordem no Drive...")
    
    session = SessionDB()
    try:
        doc_db = session.query(DocumentosQualitativos).get(doc_id)
        if not doc_db:
            bot.edit_message_text("❌ Este documento não existe mais no banco de dados.", call.message.chat.id, call.message.message_id)
            return
            
        ticker = doc_db.ativo.ticker
        
        # Reconstrói a pasta do mês (ex: 2026-04) a partir da data_ref salva no assunto
        mes_ref = datetime.now().strftime("%Y-%m")
        if doc_db.assunto and '-' in doc_db.assunto:
            partes_data = doc_db.assunto.split('-')
            if len(partes_data) == 3:
                mes_ref = f"{partes_data[2]}-{partes_data[1]}"
                
        if acao == 'C':
            # 1. Move o arquivo lá no Google Drive
            novo_link = drive_manager.mover_arquivo(file_id, ticker, mes_ref)
            if novo_link:
                # 2. Atualiza o banco
                doc_db.status_processamento = "SALVO_DRIVE"
                doc_db.url_pdf = novo_link
                session.commit()
                # 3. Muda a mensagem do Telegram
                bot.edit_message_text(f"✅ **Aprovado!**\nO arquivo foi movido para a pasta oficial do `{ticker}`.", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
            else:
                bot.edit_message_text("❌ Falha ao mover arquivo no Drive. Verifique os logs.", call.message.chat.id, call.message.message_id)
                
        elif acao == 'A':
            # 1. Deleta do Google Drive
            sucesso = drive_manager.deletar_arquivo(file_id)
            if sucesso:
                # 2. Atualiza o banco
                doc_db.status_processamento = "REJEITADO_MANUAL"
                session.commit()
                # 3. Muda a mensagem do Telegram
                bot.edit_message_text(f"🗑️ **Lixeira!**\nO arquivo suspeito do `{ticker}` foi apagado do Drive e do sistema.", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
            else:
                bot.edit_message_text("❌ Falha ao apagar arquivo no Drive. Verifique os logs.", call.message.chat.id, call.message.message_id)
                
    except Exception as e:
        print(f"Erro na revisão manual: {e}")
    finally:
        session.close()

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
        # SUBMENU: DOCUMENTOS (Lendo do Banco/Google Drive)
        # =======================================================
        elif dados.startswith("docs_"):
            partes = dados.split("_")
            ticker, tipo = partes[1], partes[2]
            markup = InlineKeyboardMarkup()

            # 1. Abre conexão com o banco para buscar os PDFs salvos
            session = SessionDB()
            ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()
            
            docs_encontrados = False

            if ativo:
                # Busca os últimos 5 documentos deste ativo, ordenados do mais novo pro mais velho
                documentos = session.query(DocumentosQualitativos)\
                                    .filter(DocumentosQualitativos.ativo_id == ativo.id)\
                                    .order_by(DocumentosQualitativos.data_publicacao.desc())\
                                    .limit(5).all()

                for doc in documentos:
                    docs_encontrados = True
                    # Cria um botão para cada documento usando o nome da categoria salvo pelo Drive!
                    texto_botao = f"📄 {doc.tipo_documento}"
                    markup.row(InlineKeyboardButton(texto_botao, url=doc.url_pdf))

            session.close()

            # 2. Mantém o link do StatusInvest como um apoio útil
            categoria_status = "fundos-imobiliarios" if tipo == "fii" else "acoes"
            link_statusinvest = f"https://statusinvest.com.br/{categoria_status}/{ticker.lower()}"
            markup.row(InlineKeyboardButton("📊 Ver no StatusInvest", url=link_statusinvest))
            markup.add(InlineKeyboardButton(f"🔙 Voltar para {ticker}", callback_data=f"{tipo}_{ticker}"))

            # 3. Mensagem dinâmica dependendo se achou PDFs ou não
            if docs_encontrados:
                texto_docs = (
                    f"📑 **Central de Documentos: {ticker}**\n\n"
                    f"Aqui estão os arquivos oficiais mais recentes que o robô organizou no seu *Google Drive*:"
                )
            else:
                texto_docs = (
                    f"📑 **Central de Documentos: {ticker}**\n\n"
                    f"⚠️ O robô ainda não baixou nenhum PDF para este ativo no Drive.\n\n"
                    f"Você pode consultar o portal abaixo provisoriamente:"
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
    except Exception as e:
        print(f"Erro no callback: {e}")

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

# ==========================================
# INICIALIZAÇÃO DO SERVIDOR WEBHOOK (RENDER)
# ==========================================

# 1. Remove qualquer "polling" ou webhook antigo que tenha ficado preso no Telegram
bot.remove_webhook()
time.sleep(1)

# 2. Configura a nova URL do Render (A casa nova!)
nova_url_render = "https://robo-fii-v2.onrender.com/" + config.TELEGRAM_BOT_TOKEN
bot.set_webhook(url=nova_url_render)
# ANTIGA URL "robo-financeiro-7wkd.onrender.com"
print(f"✅ Webhook configurado com sucesso para: {nova_url_render[:35]}...")

# 3. Inicia o servidor Flask (Se for rodar direto, o Gunicorn assume se estiver no Render)
if __name__ == "__main__":
    porta = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=porta)