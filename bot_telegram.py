import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import io
import json
import requests
import os
import re
import time
import config
import threading
import pytz # Para lidar com o fuso horário do Brasil
from sqlalchemy import text # IMPORTANTE: Permite rodar comandos SQL brutos no banco
from flask import Flask, request
from sqlalchemy import func, create_engine
from sqlalchemy.orm import sessionmaker


from services.planilhas import buscar_dados_planilha_com_cache
from services.orquestrador import varredura_diaria
from services.planilhas import buscar_ativo_na_planilha
from services.logo_service import obter_link_logo


# Importações internas dos seus próprios módulos
from atualizador_documentos import rotina_de_atualizacao_em_massa
from modules.utils import conectar_gspread
from pipeline_dados import coletor_cvm
from modules import module_cvm
from modules import module_ia
from config import MAPA_ISCAS_MASTER, TIPOS_DOC
from modules import module_macro
from modules.GoogleDriveManager import GoogleDriveManager
from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos, DadosFinanceirosAcoes
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from pipeline_dados.coletor_cvm import AcoesCVMReader

# Importe o SessionDB do local onde você o definiu originalmente
from atualizador_documentos import SessionDB  
from datetime import datetime

# ==========================================
# ⚙️ CONFIGURAÇÕES INICIAIS E BANCO DE DADOS
# ==========================================
# Instancia o gerenciador que fará a ponte com o Google Drive
drive_manager = GoogleDriveManager()

# Pega o link do banco de dados das variáveis de ambiente do Render (ou usa SQLite local como fallback)
url_banco = os.environ.get('DATABASE_URL', 'sqlite:///pipeline_dados/banco_institucional.db')

# Corrige o prefixo caso o Render mande postgres:// em vez de postgresql:// (Exigência do SQLAlchemy)
if url_banco.startswith("postgres://"):
    url_banco = url_banco.replace("postgres://", "postgresql://", 1)

# Cria o 'motor' de conexão com o banco de dados
engine = create_engine(url_banco)

# Cria a fábrica de sessões (usada para abrir e fechar conversas com o banco)
SessionDB = sessionmaker(bind=engine)

from pipeline_dados.banco_dados import Base # Importe a sua Base declarativa

# Garante que as tabelas sejam criadas na nuvem se não existirem no primeiro deploy
Base.metadata.create_all(engine)
print("✅ Banco de dados verificado e tabelas criadas com sucesso!")

# Verifica se a chave de IA está configurada corretamente no servidor
print(f"DEBUG: Groq Key encontrada: {'SIM' if os.environ.get('GROQ_API_KEY') else 'NÃO'}")

# Inicializa o robô do Telegram (threaded=False evita conflitos com o Flask no Render)
bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN, threaded=False)

# Inicializa o servidor Web Flask (Necessário para manter o bot online no Render via Webhook)
app = Flask(__name__)

# ==========================================
# 🌐 ROTAS DO SERVIDOR WEB (WEBHOOK TELEGRAM)
# ==========================================
# Esta rota recebe as mensagens do Telegram em tempo real e entrega para o bot processar
@app.route('/' + config.TELEGRAM_BOT_TOKEN, methods=['POST'])
def webhook_handler():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "OK", 200
    return "Erro", 403

# Rota raiz de status para o Render saber que a aplicação não "morreu"
@app.route('/')
def index():
    return "Bot Institucional Ativo e Operante!", 200

# ==========================================
# 🛠️ COMANDOS DE MANUTENÇÃO E DEBUG DO BANCO
# ==========================================

@bot.message_handler(commands=['debug_ativo'])
def debug_ativo(message):
    ticker = "PETR4" 
    session = SessionDB()
    try:
        # 1. Verifica se o Ativo existe
        ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()
        if not ativo:
            bot.send_message(message.chat.id, f"❌ O ativo {ticker} nem sequer existe na tabela 'Ativos'.")
            return
        
        # 2. Verifica se existem registros financeiros usando a classe importada corretamente
        qtd = session.query(DadosFinanceirosAcoes).filter(DadosFinanceirosAcoes.ativo_id == ativo.id).count()
        
        # 3. Pega a última data salva
        ultima_data = session.query(func.max(DadosFinanceirosAcoes.data_referencia)).filter(DadosFinanceirosAcoes.ativo_id == ativo.id).scalar()
        
        bot.send_message(message.chat.id, f"🔍 Diagnóstico para {ticker}:\n\n✅ Ativo ID: {ativo.id}\n📊 Registros financeiros encontrados: {qtd}\n📅 Última data salva: {ultima_data}")
        
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Erro no debug: {e}")
    finally:
        session.close()

# ==========================================
# 📡 COMANDOS DE SONDAGEM: FNET / B3
# ==========================================

# Captura apenas o último documento enviado para a B3 e devolve o JSON cru para análise de estrutura
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

# Varre todo o site da B3 para encontrar o "Nome Oficial" de todos os FIIs e salva em um arquivo de texto
@bot.message_handler(commands=['mapear_nomes'])
def comando_mapear_nomes_b3(message):
    import time
    import requests
    import threading # ⬅️ A CHAVE DA SOLUÇÃO (Permite rodar em segundo plano)

    # 1. O bot responde na mesma hora, acalmando o servidor do Telegram
    bot.send_message(message.chat.id, "🕵️‍♂️ Comando recebido! Como a B3 é lenta, enviei essa tarefa para o segundo plano. Pode continuar usando o Telegram normalmente, te enviarei o arquivo TXT assim que estiver pronto.")

    # 2. Definimos a tarefa pesada (A auditoria real que demora minutos)
    def tarefa_pesada():
        url = "https://fnet.bmfbovespa.com.br/fnet/publico/pesquisarGerenciadorDocumentosDados"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'}
        nomes_unicos = set()

        try:
            # Paginação de 50 em 50 documentos na API da B3
            for start in range(0, 5000, 50):
                params = {'d': '1', 's': str(start), 'l': '50', 'tipoFundo': '1'}

                sucesso = False
                for tentativa in range(3): # Tenta 3 vezes caso a B3 bloqueie a conexão
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
                    break # Fim dos dados

                # Extrai o nome de cada fundo e adiciona no cofre sem repetições (Set)
                for item in data:
                    descricao = item.get('descricaoFundo', '').upper().strip()
                    if descricao:
                        nomes_unicos.add(descricao)

                time.sleep(1.5) # Pausa para não ser banido pela B3

            lista_ordenada = sorted(list(nomes_unicos))
            texto_final = "\n".join(lista_ordenada)

            caminho_arquivo = "/tmp/nomes_b3_auditoria.txt"
            
            # Gera o arquivo TXT físico com os resultados
            with open(caminho_arquivo, "w", encoding="utf-8") as f:
                f.write(f"--- CATÁLOGO DE NOMES DA B3 ({len(lista_ordenada)} fundos encontrados) ---\n\n")
                f.write(texto_final)

            # Envia o arquivo finalizado para o usuário no Telegram
            with open(caminho_arquivo, "rb") as f:
                bot.send_document(message.chat.id, f, caption="🎯 Auditoria concluída em segundo plano! Aqui está a lista exata da B3.")

        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Erro crítico na thread de mapeamento: {str(e)}")

    # 3. Dispara a tarefa pesada em uma Thread separada (Background)
    thread = threading.Thread(target=tarefa_pesada)
    thread.start()

# ==========================================
# 🏢 COMANDOS CVM (AÇÕES)
# ==========================================

# Roda o raspador de dados do governo manualmente
@bot.message_handler(commands=['testar_cvm'])
def comando_testar_cvm(message):
    from datetime import datetime # ⬅️ A CORREÇÃO ESTÁ AQUI
    bot.send_message(message.chat.id, "⚙️ Iniciando teste manual do Coletor CVM (Ano Atual)...")

    session = SessionDB() 
    try:
        # Puxa o robô da CVM, envia o ano atual e manda ele buscar balanços
        coletor = AcoesCVMReader(session)
        coletor.atualizar_acoes(datetime.now().year)
        bot.send_message(message.chat.id, "✅ Coletor CVM rodou com sucesso!")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Erro no Coletor CVM: {str(e)}")
    finally:
        session.close() # Sempre fecha a conversa com o banco

# ==========================================
# 📊 COMANDOS DE PLANILHA DO GOOGLE
# ==========================================

# Permite adicionar um novo ativo direto na sua planilha do Drive via Telegram
@bot.message_handler(commands=['adicionar'])
def comando_adicionar(message):
    try:
        # Separa o comando da palavra. Ex: ["/adicionar", "BBAS3"]
        partes = message.text.split()
        if len(partes) < 2:
            bot.reply_to(message, "⚠️ Uso correto: `/adicionar TICKER` (ex: /adicionar BBAS3)", parse_mode="Markdown")
            return

        ticker = partes[1].strip().upper()
        bot.reply_to(message, f"A procurar {ticker} e a injetar na Planilha do Google...")

        # Conecta no Google Sheets
        planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
        
        # Inteligência simples: Se terminar em 11 é FII, se não é Ação.
        is_fii = True if ticker.endswith('11') else False
        nome_aba = "BD_FIIs" if is_fii else "BD_Acoes"
        aba = planilha.worksheet(nome_aba)

        # Encontra a última linha vazia da aba escolhida
        dados = aba.get_all_values()
        proxima_linha = len(dados) + 1
        
        # Insere o dado na planilha oficial
        aba.update(f'A{proxima_linha}', [[ticker]])

        bot.send_message(message.chat.id, f"✅ *{ticker}* adicionado com sucesso na aba `{nome_aba}`!", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Erro ao adicionar ativo: {e}")

# ==========================================
# ⚙️ COMANDOS DE MONITORAMENTO E STATUS
# ==========================================

# Comando /status: Fornece um "Raio-X" da integridade do banco de dados na nuvem
@bot.message_handler(commands=['status'])
def status_banco(message):
    session = SessionDB() # Abre conexão com PostgreSQL
    try:
        total_ativos = session.query(Ativo).count()
        total_docs = session.query(DocumentosQualitativos).count()
        # Busca os últimos 5 ativos cadastrados para conferência visual
        ultimos = session.query(Ativo.ticker).order_by(Ativo.id.desc()).limit(5).all()
        lista_tickers = ", ".join([a[0] for a in ultimos])
        # Busca a data mais recente no banco para saber quando foi a última varredura
        ultima_data = session.query(func.max(DocumentosQualitativos.data_publicacao)).scalar()

        resposta = (
            f"📊 **Painel de Controle do Motor de Dados**\n\n"
            f"🏢 **Ativos monitorados:** {total_ativos}\n"
            f"📄 **Documentos salvos:** {total_docs}\n"
            f"📅 **Última atualização:** {ultima_data}\n\n"
            f"🚀 **Últimos ativos:**\n{lista_tickers}"
        )
        bot.reply_to(message, resposta)
    except Exception as e:
        bot.reply_to(message, f"❌ Erro ao consultar banco: {e}")
    finally:
        session.close() # Libera a conexão com o banco

# Comando /relatorios: Exibe uma lista formatada dos 10 documentos mais recentes no Drive
@bot.message_handler(commands=['relatorios', 'docs'])
def enviar_ultimos_relatorios(message):
    bot.reply_to(message, "🔎 Buscando os últimos documentos no cofre...")
    session = SessionDB()
    try:
        # Faz JOIN entre a tabela de Ativos e a de Documentos para exibir o nome do Fundo/Ação
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

# Comando /reciclar: Reativa documentos que foram descartados incorretamente no passado
@bot.message_handler(commands=['reciclar_rejeitados'])
def comando_reciclar_rejeitados(message):
    bot.send_message(message.chat.id, "♻️ Buscando documentos rejeitados no banco...")
    session = SessionDB()
    try:
        # Muda o status de rejeitado para pendente para uma nova tentativa de IA
        rejeitados = session.query(DocumentosQualitativos).filter(
            DocumentosQualitativos.status_processamento == 'REJEITADO_DUPLO_FATOR'
        ).all()

        contador = 0
        for doc in rejeitados:
            doc.status_processamento = 'PENDENTE' 
            contador += 1

        session.commit()
        bot.send_message(message.chat.id, f"✅ {contador} documentos foram devolvidos para a fila!")
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

# ----------FORÇAR CVM------------
@bot.message_handler(commands=['forcar_cvm'])
def rodar_cvm(message):
    bot.send_message(message.chat.id, "⏳ Iniciando download de balanços da CVM. Isso pode demorar alguns minutos...")
    try:
        from coletor_cvm import AcoesCVMReader
        session = SessionDB()
        coletor = AcoesCVMReader(session)
        
        # Você pode mudar o ano aqui futuramente ou deixar dinâmico
        coletor.atualizar_acoes(2026) 
        
        session.close()
        bot.send_message(message.chat.id, "✅ Coleta CVM concluída! Balanços salvos no banco de dados.")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Erro na CVM: {str(e)}")

# ==========================================
# O NOVO MOTOR DE DASHBOARD (Arquitetura)
# ==========================================

def gerar_painel_ativo(ticker, tipo, chat_id, message_id=None):
    """Gera a mensagem principal com os botões interativos e dados em tempo real"""
    is_fii = (tipo == 'fii')
    icone = "🏢 Fundo" if is_fii else "📈 Ação"
    voltar_cmd = "menu_fiis" if is_fii else "menu_acoes"

    # 1. Puxar as Logos e Dados Reais da Planilha
    url_logo = obter_link_logo(ticker, tipo, driver_manager)
    indicadores = buscar_dados_planilha(ticker, is_fii)

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
# ⚠️ PAINEL CENTRAL DE REVISÃO (O "APP" DE AUDITORIA)
# ==========================================
import re # Usado para encontrar o ID do Drive no meio do link

def extrair_file_id(url):
    """Extrai apenas o ID alfanumérico do link longo do Google Drive"""
    match = re.search(r'/d/([a-zA-Z0-9_-]+)', str(url))
    return match.group(1) if match else None

# Comando /revisao: Abre o painel para auditar documentos que a IA não teve certeza
@bot.message_handler(commands=['revisao'])
def comando_painel_revisao(message):
    enviar_painel_tickers(message.chat.id)

def enviar_painel_tickers(chat_id, message_id=None):
    """Busca no banco todos os documentos marcados como suspeitos e agrupa por Fundo"""
    session = SessionDB()
    pendentes = session.query(DocumentosQualitativos).filter_by(status_processamento="AGUARDANDO_REVISAO").all()

    if not pendentes:
        msg = "🎉 Excelente! A sua mesa está limpa. Não há documentos aguardando revisão."
        if message_id: bot.edit_message_text(msg, chat_id, message_id)
        else: bot.send_message(chat_id, msg)
        session.close()
        return

    # Agrupa a fila de trabalho por Ticker (Fundo)
    tickers = sorted(list(set([doc.ativo.ticker for doc in pendentes])))
    markup = InlineKeyboardMarkup()

    for t in tickers:
        qtd = len([d for d in pendentes if d.ativo.ticker == t])
        markup.add(InlineKeyboardButton(text=f"📁 {t} ({qtd} docs)", callback_data=f"rev_t_{t}"))

    msg = "⚠️ **Central de Revisão**\n\nEstes FIIs possuem documentos suspeitos ou em formato de imagem. Selecione um para analisar:"
    if message_id:
        bot.edit_message_text(msg, chat_id, message_id, reply_markup=markup, parse_mode="Markdown")
    else:
        bot.send_message(chat_id, msg, reply_markup=markup, parse_mode="Markdown")
    session.close()

# 🧠 O CÉREBRO DA REVISÃO (Lida com todos os cliques dos botões de revisão)
@bot.callback_query_handler(func=lambda call: call.data.startswith('rev_'))
def processar_revisao(call):
    partes = call.data.split('_')
    acao = partes[1]
    session = SessionDB()

    try:
        # AÇÃO: Voltar ao menu inicial de revisão
        if acao == 'start':
            enviar_painel_tickers(call.message.chat.id, call.message.message_id)

        # AÇÃO: Mostrar lista de documentos suspeitos de um fundo específico
        elif acao == 't':
            ticker = partes[2]
            pendentes = session.query(DocumentosQualitativos).join(Ativo).filter(
                Ativo.ticker == ticker, 
                DocumentosQualitativos.status_processamento == "AGUARDANDO_REVISAO"
            ).all()

            markup = InlineKeyboardMarkup()
            for doc in pendentes:
                btn_text = f"📄 {doc.assunto} | ID: {doc.id_b3}"
                markup.add(InlineKeyboardButton(text=btn_text, callback_data=f"rev_d_{doc.id}"))
            markup.add(InlineKeyboardButton(text="🔙 Voltar aos FIIs", callback_data="rev_start"))

            bot.edit_message_text(f"📑 **Análise: {ticker}**\n\nQual documento você quer olhar?", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

        # AÇÃO: Abrir as opções (Visualizar, Salvar, Apagar) de um documento específico
        elif acao == 'd':
            doc_id = partes[2]
            doc = session.query(DocumentosQualitativos).get(doc_id)

            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(text="🔗 Visualizar PDF (Google Drive)", url=doc.url_pdf))
            markup.add(
                InlineKeyboardButton(text="✅ Classificar e Salvar", callback_data=f"rev_app_{doc.id}"),
                InlineKeyboardButton(text="🗑️ Jogar no Lixo", callback_data=f"rev_del_{doc.id}")
            )
            markup.add(InlineKeyboardButton(text="🔙 Voltar", callback_data=f"rev_t_{doc.ativo.ticker}"))

            txt = f"🔍 **Inspecionando Documento**\n\n**Fundo:** {doc.ativo.ticker}\n**Data:** {doc.assunto}\n**Leitura da B3:** {doc.tipo_documento}\n\nO que deseja fazer?"
            bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

        # AÇÃO: Usuário decidiu salvar, abre o catálogo de tipos de documento
        elif acao == 'app':
            doc_id = partes[2]
            doc = session.query(DocumentosQualitativos).get(doc_id)

            markup = InlineKeyboardMarkup()
            for id_tipo, nome_tipo in TIPOS_DOC.items():
                markup.add(InlineKeyboardButton(text=f"📂 {nome_tipo}", callback_data=f"rev_typ_{doc.id}_{id_tipo}"))
            markup.add(InlineKeyboardButton(text="🔙 Cancelar", callback_data=f"rev_d_{doc.id}"))

            bot.edit_message_text(f"**Renomear Arquivo**\n\nO que é este documento do `{doc.ativo.ticker}` na verdade?", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

        # AÇÃO: A MÁGICA - Renomeia no Drive, move de pasta e atualiza o Banco de Dados
        elif acao == 'typ':
            doc_id = partes[2]
            tipo_id = partes[3]
            tipo_nome_limpo = TIPOS_DOC[tipo_id]

            bot.answer_callback_query(call.id, "Organizando no Drive...")

            doc = session.query(DocumentosQualitativos).get(doc_id)
            file_id = extrair_file_id(doc.url_pdf)

            # Define a pasta do mês. Ex: 2026-04
            mes_ref = datetime.now().strftime("%Y-%m")
            if doc.assunto and '-' in doc.assunto:
                p = doc.assunto.split('-')
                if len(p) == 3: mes_ref = f"{p[2]}-{p[1]}"

            novo_nome_pdf = f"{tipo_nome_limpo}_{doc.assunto}_{doc.id_b3}.pdf"

            # Chama a função do GoogleDriveManager para executar a ação na nuvem
            novo_link = drive_manager.mover_e_renomear_arquivo(file_id, doc.ativo.ticker, mes_ref, novo_nome_pdf)

            if novo_link:
                doc.status_processamento = "SALVO_DRIVE"
                doc.tipo_documento = tipo_nome_limpo
                doc.url_pdf = novo_link
                session.commit()

                m = InlineKeyboardMarkup().add(InlineKeyboardButton(text="🔙 Voltar ao Painel", callback_data="rev_start"))
                bot.edit_message_text(f"✅ **Arquivo Guardado!**\n\nNome: `{novo_nome_pdf}`\nPasta: `{doc.ativo.ticker}`", call.message.chat.id, call.message.message_id, reply_markup=m, parse_mode="Markdown")
            else:
                bot.answer_callback_query(call.id, "❌ Erro ao mover no Drive!")

        # AÇÃO: Usuário decidiu que o documento era lixo (ex: Falso Positivo)
        elif acao == 'del':
            doc_id = partes[2]
            bot.answer_callback_query(call.id, "Apagando do Drive...")
            doc = session.query(DocumentosQualitativos).get(doc_id)
            file_id = extrair_file_id(doc.url_pdf)

            if drive_manager.deletar_arquivo(file_id):
                doc.status_processamento = "REJEITADO_MANUAL"
                session.commit()
                m = InlineKeyboardMarkup().add(InlineKeyboardButton(text="🔙 Voltar ao Painel", callback_data="rev_start"))
                bot.edit_message_text(f"🗑️ Documento apagado com sucesso.", call.message.chat.id, call.message.message_id, reply_markup=m)
            else:
                bot.answer_callback_query(call.id, "❌ Erro ao apagar no Drive!")

    except Exception as e:
        print(f"Erro no painel de revisão: {e}")
    finally:
        session.close()

# ==========================================
# 🧭 MENUS DE NAVEGAÇÃO E INTERFACE (UI)
# ==========================================
# Ponto de partida do Bot
@bot.message_handler(commands=['menu', 'start'])
def enviar_menu(message):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("🏢 FIIs (Imobiliários)", callback_data="menu_fiis"),
               InlineKeyboardButton("📈 Ações (Empresas)", callback_data="menu_acoes"))
    markup.row(InlineKeyboardButton("🌍 Visão Macro & Notícias", callback_data="menu_macro"))
    markup.row(InlineKeyboardButton("ℹ️ Ajuda / Sobre", callback_data="menu_ajuda"))
    bot.send_message(message.chat.id, "🤖 *Terminal Institucional* 🤖\nSelecione o módulo de análise abaixo:", reply_markup=markup, parse_mode="Markdown")

# Cérebro de Navegação: Capta todos os cliques dos menus
@bot.callback_query_handler(func=lambda call: True)
def callback_geral(call):
    try:
        dados = call.data
        chat_id = call.message.chat.id
        msg_id = call.message.message_id

        # --- NAVEGAÇÃO BÁSICA ---
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
                "`/status` - Saúde do BD PostgreSQL\n"
                "`/relatorios` - Últimos PDFs\n"
                "`/adicionar TICKER` - Insere ativos\n\n"
                "📊 *Nova Arquitetura:*\n"
                "- Resumo IA, Indicadores (P/L, P/VP, DY)\n"
                "- Submenus de Documentos e Análise IA."
            )
            bot.edit_message_text(texto_ajuda, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # --- MENUS DINÂMICOS (Consultam a Planilha) ---
        elif dados == "menu_fiis":
            bot.answer_callback_query(call.id, "Carregando FIIs...")
            markup = InlineKeyboardMarkup(row_width=2)
            markup.add(
                InlineKeyboardButton("⭐ Meus Favoritos", callback_data="favoritos_fiis"),
                InlineKeyboardButton("🔥 Oportunidades", callback_data="oportunidades_fiis")
            )

            try:
                # ⚠️ PONTO DE ATENÇÃO: Conexão direta com Google Sheets a cada clique.
                planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
                aba = planilha.worksheet("BD_FIIs")
                matriz = aba.get_all_values()

                cabecalhos = [c.lower().strip() for c in matriz[0]]
                idx = next((i for i, c in enumerate(cabecalhos) if c in ["setor", "segmento", "tipo"]), -1)

                # Gera botões automáticos baseados nos setores digitados na planilha
                if idx != -1:
                    setores = sorted(list(set(linha[idx].strip() for linha in matriz[1:] if linha[idx].strip())))
                    for s in setores:
                        markup.add(InlineKeyboardButton(f"📁 {s}", callback_data=f"setor_fii_{s[:12]}"))
            except Exception as e:
                print(f"Erro ao ler setores: {e}")

            markup.add(InlineKeyboardButton("🔙 Voltar ao Início", callback_data="voltar_menu"))
            bot.edit_message_text("🏢 *Módulo FIIs*\nSelecione uma categoria ou favorito:", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # (A Lógica para "menu_acoes" e "setor_acao" segue a exata mesma estrutura descrita acima)
        elif dados == "menu_acoes":
            bot.answer_callback_query(call.id, "Carregando Ações...")
            markup = InlineKeyboardMarkup(row_width=2)
            
            # Adicionando botões de atalho
            markup.add(
                InlineKeyboardButton("⭐ Minhas Favoritas", callback_data="favoritos_acoes"),
                InlineKeyboardButton("🔥 Oportunidades", callback_data="oportunidades_acoes")
            )

            try:
                # Conecta ao Sheets
                planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
                # Tenta buscar a aba
                try:
                    aba = planilha.worksheet("BD_Acoes")
                except:
                    bot.send_message(chat_id, "❌ Erro: Aba 'BD_Acoes' não encontrada na planilha.")
                    return

                matriz = aba.get_all_values()
                if not matriz:
                    bot.send_message(chat_id, "❌ A aba 'BD_Acoes' está vazia.")
                    return

                # Identifica cabeçalhos e encontra o setor
                cabecalhos = [c.lower().strip() for c in matriz[0]]
                idx = next((i for i, c in enumerate(cabecalhos) if c in ["setor", "segmento", "tipo"]), -1)

                if idx != -1:
                    setores = sorted(list(set(linha[idx].strip() for linha in matriz[1:] if linha[idx].strip())))
                    for s in setores:
                        markup.add(InlineKeyboardButton(f"📁 {s}", callback_data=f"setor_acao_{s[:12]}"))
                else:
                    bot.send_message(chat_id, "⚠️ Cabeçalho 'Setor/Segmento' não localizado na planilha.")

            except Exception as e:
                logger.error(f"Erro fatal no menu_acoes: {e}")
                bot.send_message(chat_id, f"❌ Erro ao acessar planilha: {str(e)}")
                return

            markup.add(InlineKeyboardButton("🔙 Voltar ao Início", callback_data="voltar_menu"))
            bot.edit_message_text("📈 *Módulo de Ações*\nSelecione um setor ou favorita:", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

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
        # 🟢 ABRIR TELA DO ATIVO (Destino Final)
        # ==========================================
        elif dados.startswith("fii_") or dados.startswith("acao_"):
            partes = dados.split("_")
            tipo = partes[0] 
            ticker = partes[1]
            bot.answer_callback_query(call.id, f"Carregando terminal de {ticker}...")
            # Envia a requisição para gerar o "Dashboard" do ativo com Logo e Indicadores
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
            indicadores = buscar_dados_planilha(ticker, is_fii)
            
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
                        f"_(Você pode mapear mais colunas lá no dicionário da função buscar_dados_planilha)_"
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
                        f"_(Você pode mapear mais colunas lá no dicionário da função buscar_dados_planilha)_"
                    )
                bot.edit_message_text(texto, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # ==============================================================
        # NÍVEL 1: MENU DE MESES (Quando clica em "Documentos")
        # ==============================================================
        elif dados.startswith("docs_"):
            # CORREÇÃO 1: Ordem exata -> docs_TICKER_TIPO
            partes = dados.split("_")
            ticker = partes[1]
            tipo = partes[2]
            
            markup = InlineKeyboardMarkup()
            session = SessionDB()

            ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()
            encontrou_dados = False

            if ativo:
                if tipo == "fii":
                    # Puxa todos os documentos do FII
                    docs = session.query(DocumentosQualitativos).filter(DocumentosQualitativos.ativo_id == ativo.id).all()
                    if docs:
                        encontrou_dados = True
                        # Pega apenas os meses únicos (Ex: '2026-04') e ordena do mais novo pro mais velho
                        meses_unicos = sorted(list(set([d.data_publicacao.strftime("%Y-%m") for d in docs if d.data_publicacao])), reverse=True)

                        for mes in meses_unicos[:10]:
                            qtd = len([d for d in docs if d.data_publicacao and d.data_publicacao.strftime("%Y-%m") == mes])
                            ano, mes_num = mes.split('-')
                            # CORREÇÃO 2: Botão do Mês padronizado (mes_TICKER_TIPO_PERIODO)
                            markup.add(InlineKeyboardButton(f"📁 {mes_num}/{ano} ({qtd} arquivos)", callback_data=f"mes_{ticker}_{tipo}_{mes}"))

                elif tipo == "acao":
                    from pipeline_dados.banco_dados import DadosFinanceirosAcoes
                    # Puxa todos os balanços processados pelo módulo CVM
                    balancos = session.query(DadosFinanceirosAcoes).filter(DadosFinanceirosAcoes.ativo_id == ativo.id).all()
                    if balancos:
                        encontrou_dados = True
                        # Pega as datas de referência únicas
                        datas_unicas = sorted(list(set([b.data_referencia.strftime("%Y-%m-%d") for b in balancos if b.data_referencia])), reverse=True)

                        for dt in datas_unicas[:5]:
                            ano, mes_num, dia = dt.split('-')
                            markup.add(InlineKeyboardButton(f"📊 Balanço CVM ({mes_num}/{ano})", callback_data=f"mes_{ticker}_{tipo}_{dt}"))

            session.close()

            # Botões padrão de fundo
            cat_status = "fundos-imobiliarios" if tipo == "fii" else "acoes"
            markup.row(InlineKeyboardButton("📈 Ver no StatusInvest", url=f"https://statusinvest.com.br/{cat_status}/{ticker.lower()}"))
            
            # CORREÇÃO 3: Botão de voltar consertado (Aponta direto para fii_MXRF11 ou acao_PETR4)
            markup.add(InlineKeyboardButton(f"🔙 Voltar para {ticker}", callback_data=f"{tipo}_{ticker}"))

            if encontrou_dados:
                txt = f"📅 **Histórico de {ticker}**\n\nEscolha o período que você deseja analisar:"
            else:
                txt = f"📭 **Nenhum dado encontrado para {ticker}**\nO robô ainda não processou arquivos ou balanços para este ativo."

            bot.edit_message_text(txt, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # ==============================================================
        # NÍVEL 2: MOSTRANDO OS ARQUIVOS OU RELATÓRIO CVM
        # ==============================================================
        elif dados.startswith("mes_"):
            # CORREÇÃO 4: Lendo na nova ordem padronizada
            partes = dados.split("_")
            ticker = partes[1]
            tipo = partes[2]
            periodo = partes[3]
            
            markup = InlineKeyboardMarkup()
            session = SessionDB()

            ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()

            if tipo == "fii":
                docs = session.query(DocumentosQualitativos).filter(DocumentosQualitativos.ativo_id == ativo.id).all()
                docs_do_mes = [d for d in docs if d.data_publicacao and d.data_publicacao.strftime("%Y-%m") == periodo]

                ano, mes_num = periodo.split('-')
                txt = f"📂 **Arquivos de {ticker} ({mes_num}/{ano})**\n\nEstes são os documentos salvos no Drive:"

                for doc in docs_do_mes:
                    markup.add(InlineKeyboardButton(f"📄 {doc.tipo_documento}", url=doc.url_pdf))

            elif tipo == "acao":
                from pipeline_dados.banco_dados import DadosFinanceirosAcoes
                balanco = session.query(DadosFinanceirosAcoes).filter(
                    DadosFinanceirosAcoes.ativo_id == ativo.id, 
                    DadosFinanceirosAcoes.data_referencia == periodo
                ).first()

                ano, mes_num, dia = periodo.split('-')
                txt = f"📊 **Relatório Financeiro: {ticker} ({mes_num}/{ano})**\n_Dados oficiais extraídos da CVM_\n\n"

                def formata_rs(valor):
                    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if valor else "Não divulgado"

                txt += f"💰 **Receita:** {formata_rs(balanco.receita)}\n"
                txt += f"💸 **Lucro Líquido:** {formata_rs(balanco.lucro_liquido)}\n"
                txt += f"🏦 **Caixa:** {formata_rs(balanco.caixa)}\n"
                txt += f"📉 **Passivo Total:** {formata_rs(balanco.passivo_total)}\n"

            session.close()

            # CORREÇÃO 5: O Botão de voltar consertado para retornar ao menu de meses
            markup.add(InlineKeyboardButton("🔙 Voltar aos Meses", callback_data=f"docs_{ticker}_{tipo}"))

            bot.edit_message_text(txt, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

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
