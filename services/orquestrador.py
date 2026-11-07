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

    from services.historico_operacional import iniciar_evento, concluir_evento, registrar_resultado
    # 1. Rotina B3/FNET + fila PENDENTE residual
    evento_fnet = iniciar_evento("VARREDURA_FNET", origem="RENDER_CRON", mensagem="Varredura FNET automática iniciada.")
    try:
        resultado_fnet = rotina_de_atualizacao_em_massa()
        detalhes = resultado_fnet.detalhes_painel() if callable(getattr(resultado_fnet, "detalhes_painel", None)) else {}
        registrar_resultado(evento_fnet, detalhes)
        concluir_evento(evento_fnet, sucesso=getattr(resultado_fnet, "status", "erro") != "erro", mensagem=resultado_fnet.mensagem_telegram())
        _avisar(resultado_fnet.mensagem_telegram())
        processamento = getattr(resultado_fnet, "processamento", None)
        if processamento is not None:
            _avisar(processamento.mensagem_telegram())
    except Exception as e:
        concluir_evento(evento_fnet, sucesso=False, erro=type(e).__name__, mensagem="Falha na varredura FNET automática.")
        _avisar(f"❌ Erro na varredura B3: {type(e).__name__}")

    # 2. Rotina CVM (Ações)
    evento_acoes = iniciar_evento("VARREDURA_DOCUMENTOS_ACOES", origem="RENDER_CRON", mensagem="Varredura documental CVM/IPE de ações iniciada.")
    session = None
    try:
        session = SessionDB()
        coletor = AcoesCVMReader(session)
        resultado_cvm = coletor.atualizar_acoes()
        registrar_resultado(evento_acoes, {"mensagem": resultado_cvm.mensagem_telegram()})
        concluir_evento(evento_acoes, sucesso=True, mensagem=resultado_cvm.mensagem_telegram())
        _avisar(resultado_cvm.mensagem_telegram())
    except Exception as e:
        concluir_evento(evento_acoes, sucesso=False, erro=type(e).__name__, mensagem="Falha na varredura CVM de ações.")
        _avisar(f"❌ Erro na varredura CVM: {type(e).__name__}")
    finally:
        if session is not None:
            session.close()

    _avisar("Varredura diaria encerrada (coleta FNET+ITR). IA nao executada neste cron.")


def coleta_informes_fiis():
    """Cron mensal: informes mensais de FIIs da CVM (equivalente a /forcar_fiis)."""
    _avisar("Iniciando coleta mensal de informes de FIIs (CVM).")
    try:
        from pipeline_dados.coletor_fiis import processar_informes_fiis_cvm

        resultado = processar_informes_fiis_cvm()
        _avisar(resultado.mensagem_telegram())
    except Exception as e:
        _avisar(f"Erro na coleta mensal de FIIs: {type(e).__name__}")


def coleta_docs_acoes():
    """Cron semanal: PDFs de acoes na CVM (equivalente a /forcar_docs_acoes)."""
    from services.historico_operacional import iniciar_evento, concluir_evento, registrar_resultado
    evento_id = iniciar_evento("VARREDURA_DOCUMENTOS_ACOES", origem="RENDER_CRON", mensagem="Varredura IPE/CVM de ações iniciada.")
    _avisar("Iniciando varredura semanal de PDFs de acoes (CVM).")
    try:
        from pipeline_dados.coletor_docs_acoes import RelatoriosAcoesCVM

        resultado = RelatoriosAcoesCVM().vasculhar_documentos()
        registrar_resultado(evento_id, resultado.detalhes_painel())
        concluir_evento(evento_id, sucesso=resultado.status != "erro", mensagem=resultado.mensagem_telegram())
        _avisar(resultado.mensagem_telegram())
    except Exception as e:
        concluir_evento(evento_id, sucesso=False, erro=type(e).__name__, mensagem="Falha na varredura IPE/CVM de ações.")
        _avisar(f"Erro na varredura de PDFs de acoes: {type(e).__name__}")


def processar_ia_acoes(ticker: str | None = None):
    """Cron semanal: classifica a fila PENDENTE_ACAO, inteira ou de um ativo."""
    alvo = f" de {ticker.upper()}" if ticker else ""
    _avisar(f"Iniciando classificacao por IA de documentos de acoes{alvo}.")
    try:
        from atualizador_documentos import rotina_processar_acoes

        resultado = rotina_processar_acoes(ticker=ticker)
        _avisar(resultado.mensagem_telegram())
    except Exception as e:
        _avisar(f"Erro no processamento IA de acoes: {type(e).__name__}")


def alimentar_ia():
    """Cron diario: extrai texto RAG de gerencial/fato/release/apresenta/informe."""
    _avisar("Iniciando alimentacao de IA (textos RAG pendentes).")
    try:
        from atualizador_documentos import (
            alimentar_textos_pendentes,
            mensagem_alimentacao_ia,
        )

        resumo = alimentar_textos_pendentes()
        _avisar(mensagem_alimentacao_ia(resumo))
    except Exception as e:
        _avisar(f"Erro na alimentacao de IA: {type(e).__name__}")


def auditar_drive():
    """Cron semanal: duplicatas e PDFs mortos no Drive (equivalente a /auditar_drive)."""
    _avisar("Iniciando auditoria semanal do Drive.")
    try:
        from atualizador_documentos import (
            auditar_documentos_drive,
            mensagem_auditoria_drive,
        )

        resumo = auditar_documentos_drive()
        _avisar(mensagem_auditoria_drive(resumo))
    except Exception as e:
        _avisar(f"Erro na auditoria do Drive: {type(e).__name__}")


def snapshot_eod():
    """Cron noturno: snapshot EOD apos fechamento, com data do pregao."""
    try:
        from datetime import datetime

        import pytz

        from modules.eod_snapshots import tentar_persistir_eod
        from modules.utils import conectar_gspread

        gc = conectar_gspread()
        planilha = gc.open_by_url(config.SPREADSHEET_URL)
        agora_dt = datetime.now(pytz.timezone("America/Sao_Paulo"))
        resumo = tentar_persistir_eod(planilha, agora_dt)
        if resumo:
            logger.info("EOD snapshots gravados: %s", resumo)
        else:
            logger.info("EOD snapshots omitidos (flag, horario ou falha).")
    except Exception as e:
        logger.error("EOD snapshots: falha no cron (%s)", type(e).__name__)
