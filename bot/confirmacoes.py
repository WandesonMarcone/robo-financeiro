import logging

from atualizador_documentos import SessionDB
from bot.loader import bot
from modules import seguranca
from pipeline_dados.banco_dados import DocumentosQualitativos

logger = logging.getLogger(__name__)

# ==========================================
# CONFIRMAÇÃO EXPLÍCITA DE OPERAÇÕES DESTRUTIVAS
# ==========================================
# /resetar_docs exige dupla autorização:
#   1. Comando só responde a SUPERADMIN;
#   2. A execução só acontece após clique em "Confirmar" (verificado novamente).


@bot.callback_query_handler(func=lambda call: call.data == "reset_confirmar")
def confirmar_reset(call):
    user_id = call.from_user.id
    if not seguranca.eh_superadmin(user_id):
        logger.warning(
            "Tentativa de confirmar exclusão em massa por usuário sem privilégio: %s",
            user_id,
        )
        try:
            bot.answer_callback_query(call.id, "Acesso negado.", show_alert=True)
        except Exception:
            pass
        return

    chat_id = call.message.chat.id
    message_id = call.message.message_id
    session = SessionDB()
    try:
        apagados = session.query(DocumentosQualitativos).delete()
        session.commit()
        logger.info("Exclusão em massa confirmada: %s registros apagados (por %s)", apagados, user_id)
        bot.edit_message_text(
            f"✅ **Limpeza concluída!**\n`{apagados}` registros de documentos foram apagados.",
            chat_id,
            message_id,
            parse_mode="Markdown",
        )
    except Exception as e:
        session.rollback()
        logger.error("Erro ao executar exclusão em massa: %s", e)
        bot.edit_message_text(
            f"❌ Erro ao apagar: {e}", chat_id, message_id, parse_mode="Markdown"
        )
    finally:
        session.close()


@bot.callback_query_handler(func=lambda call: call.data == "reset_cancelar")
def cancelar_reset(call):
    try:
        bot.edit_message_text(
            "✅ Exclusão cancelada. Nenhum registro foi alterado.",
            call.message.chat.id,
            call.message.message_id,
        )
    except Exception as e:
        logger.error("Falha ao cancelar exclusão: %s", e)
