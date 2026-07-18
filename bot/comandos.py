from sqlalchemy import func
from bot.loader import bot
from atualizador_documentos import SessionDB 
from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos

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
