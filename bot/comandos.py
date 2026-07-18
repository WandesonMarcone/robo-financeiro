from bot.loader import bot
from atualizador_documentos import SessionDB
from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos

@bot.message_handler(commands=['status'])
def status_banco(message):
    session = SessionDB()
    try:
        total_ativos = session.query(Ativo).count()
        total_docs = session.query(DocumentosQualitativos).count()
        resposta = f"📊 **Painel de Controle**\n\n🏢 Ativos: {total_ativos}\n📄 Docs: {total_docs}"
        bot.reply_to(message, resposta, parse_mode="Markdown")
    finally:
        session.close()

@bot.message_handler(commands=['relatorios', 'docs'])
def enviar_ultimos_relatorios(message):
    session = SessionDB()
    try:
        ultimos_docs = session.query(DocumentosQualitativos, Ativo)\
            .join(Ativo, DocumentosQualitativos.ativo_id == Ativo.id)\
            .order_by(DocumentosQualitativos.data_publicacao.desc())\
            .limit(5).all()
        
        # ... (lógica de formatação dos relatórios) ...
        bot.reply_to(message, "📄 Relatórios carregados...", parse_mode='Markdown')
    finally:
        session.close()
