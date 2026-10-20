import logging

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

    # 1. Rotina B3/FNET + fila PENDENTE residual
    try:
        resultado_fnet = rotina_de_atualizacao_em_massa()
        _avisar(resultado_fnet.mensagem_telegram())
        processamento = getattr(resultado_fnet, "processamento", None)
        if processamento is not None:
            _avisar(processamento.mensagem_telegram())
    except Exception as e:
        _avisar(f"❌ Erro na varredura B3: {type(e).__name__}")

    # 2. Rotina CVM (Ações)
    session = None
    try:
        session = SessionDB()
        coletor = AcoesCVMReader(session)
        resultado_cvm = coletor.atualizar_acoes()
        _avisar(resultado_cvm.mensagem_telegram())
    except Exception as e:
        _avisar(f"❌ Erro na varredura CVM: {type(e).__name__}")
    finally:
        if session is not None:
            session.close()

    _avisar("Varredura diaria encerrada (coleta FNET+ITR). IA nao executada neste cron.")
