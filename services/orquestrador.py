import config
from datetime import datetime
from bot.loader import bot
from atualizador_documentos import rotina_de_atualizacao_em_massa, SessionDB
from pipeline_dados.coletor_cvm import AcoesCVMReader

bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN)

def varredura_diaria():
    """Rotina automatizada de coleta de dados."""
    bot.send_message(config.TELEGRAM_CHAT_ID, "⚙️ *Bom dia! Iniciando a varredura automática...*", parse_mode="Markdown")
    
    # 1. Rotina B3/FNET
    try:
        qtd = rotina_de_atualizacao_em_massa()
        bot.send_message(config.TELEGRAM_CHAT_ID, f"✅ B3 finalizada! {qtd} documentos salvos.")
    except Exception as e:
        bot.send_message(config.TELEGRAM_CHAT_ID, f"❌ Erro na varredura B3: {e}")

    # 2. Rotina CVM (Ações)
    try:
        session = SessionDB()
        coletor = AcoesCVMReader(session)
        coletor.atualizar_acoes(datetime.now().year)
        session.close()
        bot.send_message(config.TELEGRAM_CHAT_ID, "✅ Coleta CVM finalizada com sucesso!")
    except Exception as e:
        bot.send_message(config.TELEGRAM_CHAT_ID, f"❌ Erro na varredura CVM: {e}")

    bot.send_message(config.TELEGRAM_CHAT_ID, "🏁 *Cofre de dados 100% atualizado!*", parse_mode="Markdown")
