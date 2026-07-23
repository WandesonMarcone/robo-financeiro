import threading
import time
import requests
import config
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import func

from bot.loader import bot
from atualizador_documentos import SessionDB 
from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos
from modules.utils import conectar_gspread

from modules.scraper_fiis import rodar_garimpo_fiis # <--- Importe o arquivo que corrigimos

# ==========================================
# 🧭 MENUS DE NAVEGAÇÃO E INTERFACE (UI)
# ==========================================
@bot.message_handler(commands=['menu', 'start'])
def enviar_menu(message):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("🏢 FIIs (Imobiliários)", callback_data="menu_fiis"),
               InlineKeyboardButton("📈 Ações (Empresas)", callback_data="menu_acoes"))
    markup.row(InlineKeyboardButton("🌍 Visão Macro & Notícias", callback_data="menu_macro"))
    markup.row(InlineKeyboardButton("ℹ️ Ajuda / Sobre", callback_data="menu_ajuda"))
    bot.send_message(message.chat.id, "🤖 *Terminal Institucional* 🤖\nSelecione o módulo de análise abaixo:", reply_markup=markup, parse_mode="Markdown")

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
            f"🏢 **Ativos monitorados:** {total_ativos}\n"
            f"📄 **Documentos salvos:** {total_docs}\n"
            f"📅 **Última atualização:** {ultima_data}\n\n"
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
# 📊 COMANDOS DE PLANILHA DO GOOGLE E GESTÃO
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

@bot.message_handler(commands=['reciclar_rejeitados'])
def comando_reciclar_rejeitados(message):
    bot.send_message(message.chat.id, "♻️ Buscando documentos rejeitados no banco...")
    session = SessionDB()
    try:
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

@bot.message_handler(commands=['forcar_varredura'])
def acionar_varredura_manual(message):
    bot.reply_to(message, "⚙️ *Iniciando varredura completa (FIIs + Documentos)...*\nIsso pode levar alguns minutos. Aguarde o aviso de conclusão!", parse_mode="Markdown")

    def tarefa_pesada_background():
        try:
            # 1. Rotina de Documentos (PDFs/CVM)
            from atualizador_documentos import rotina_de_atualizacao_em_massa
            relatorios_baixados = rotina_de_atualizacao_em_massa()
            
            # 2. Rotina de FIIs (Motor JSON para a Planilha)
            from datetime import datetime
            import pytz
            from modules.utils import conectar_gspread
            from services.planilhas import CACHE_PLANILHA
            
            sp_tz = pytz.timezone('America/Sao_Paulo')
            agora = datetime.now(sp_tz)
            
            client = conectar_gspread()
            planilha = client.open_by_url(config.SPREADSHEET_URL)
            
            batch_updates, msg_out, aba_fiis = rodar_garimpo_fiis(planilha, agora, agora.strftime("%H:%M"), sp_tz)
            
            # --- CORREÇÃO DA LÓGICA DE AVISO ---
            if batch_updates:
                planilha.batch_update(batch_updates)
                
                # Limpa o cache da planilha
                CACHE_PLANILHA["BD_FIIs"]["dados"] = None
                CACHE_PLANILHA["BD_FIIs"]["timestamp"] = 0
                
                msg_planilha = f"\n\n{msg_out}"
            else:
                msg_planilha = "\n\n📊 *Planilha:* Nenhuma atualização de cotação necessária agora."

            # O bot agora SEMPRE avisa quantos relatórios baixou
            resposta_final = (
                f"✅ *Varredura Concluída!*\n\n"
                f"📥 **Docs processados (B3):** {relatorios_baixados}"
                f"{msg_planilha}"
            )
            bot.send_message(message.chat.id, resposta_final, parse_mode="Markdown")
            
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Erro na varredura: {str(e)[:200]}") 

    thread = threading.Thread(target=tarefa_pesada_background)
    thread.start()

@bot.message_handler(commands=['forcar_cvm'])
def rodar_cvm(message):
    bot.send_message(message.chat.id, "⏳ *Iniciando motor CVM...*\nBaixando e processando milhares de balanços em segundo plano. Isso pode levar alguns minutos!", parse_mode="Markdown")
    
    def tarefa_cvm_background():
        try:
            from pipeline_dados.coletor_cvm import AcoesCVMReader
            from datetime import datetime
            
            # Pega o ano atual automaticamente
            ano_atual = datetime.now().year
            
            session = SessionDB()
            coletor = AcoesCVMReader(session)
            
            # Executa a coleta pesada
            coletor.atualizar_acoes(ano_atual) 
            session.close()
            
            bot.send_message(message.chat.id, f"✅ *Coleta CVM ({ano_atual}) Concluída!*\nTodos os balanços foram salvos no banco de dados.", parse_mode="Markdown")
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Erro na CVM: {str(e)}")
            
    # Inicia a tarefa em segundo plano (não congela o bot!)
    import threading
    thread_cvm = threading.Thread(target=tarefa_cvm_background)
    thread_cvm.start()

@bot.message_handler(commands=['mapear_nomes'])
def comando_mapear_nomes_b3(message):
    bot.send_message(message.chat.id, "🕵️‍♂️ Comando recebido! Como a B3 é lenta, enviei essa tarefa para o segundo plano. Pode continuar usando o Telegram normalmente, te enviarei o arquivo TXT assim que estiver pronto.")

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

    thread = threading.Thread(target=tarefa_pesada)
    thread.start()