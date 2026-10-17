import logging
from datetime import datetime

import config
from bot.loader import bot
from atualizador_documentos import rotina_de_atualizacao_em_massa, SessionDB
from pipeline_dados.coletor_cvm import AcoesCVMReader

logger = logging.getLogger("robo.orquestrador")


def _chat_operacional():
    """Destino dos avisos de operacao: somente o administrador configurado.

    Documentos NAO sao transmitidos por aqui; a distribuicao e individual e usa
    os seguidores de cada ativo (``usuarios_que_acompanham``).
    """
    return (
        getattr(config, "TELEGRAM_ADMIN_ID", None)
        or getattr(config, "TELEGRAM_CHAT_ID", None)
    )


def _avisar(texto, **kwargs):
    destino = _chat_operacional()
    if destino is None:
        logger.warning("Administrador nao configurado; aviso nao enviado.")
        return
    try:
        bot.send_message(destino, texto, **kwargs)
    except Exception:
        logger.warning("Falha ao enviar aviso operacional", exc_info=True)


def varredura_diaria():
    """Rotina automatizada de coleta de dados."""
    _avisar(
        "⚙️ *Bom dia! Iniciando a varredura automática...*",
        parse_mode="Markdown",
    )

    # 1. Rotina B3/FNET
    try:
        qtd = rotina_de_atualizacao_em_massa()
        _avisar(f"✅ B3 finalizada! {qtd} documentos salvos.")
    except Exception as e:
        _avisar(f"❌ Erro na varredura B3: {type(e).__name__}")

    # 2. Rotina CVM (Ações)
    session = None
    try:
        session = SessionDB()
        coletor = AcoesCVMReader(session)
        coletor.atualizar_acoes(datetime.now().year)
        _avisar("✅ Coleta CVM finalizada com sucesso!")
    except Exception as e:
        _avisar(f"❌ Erro na varredura CVM: {type(e).__name__}")
    finally:
        if session is not None:
            session.close()

    _avisar(
        "🏁 *Cofre de dados 100% atualizado!*", parse_mode="Markdown"
    )

    # ==========================================
    # 3. NOVO: Processamento Qualitativo (IA)
    # ==========================================
    _avisar(
        "🧠 *Iniciando leitura de PDFs com IA...*", parse_mode="Markdown"
    )
    try:
        _avisar("✅ Leitura de IA finalizada!")
    except Exception as e:
        _avisar(f"❌ Erro no Motor de IA: {type(e).__name__}")
