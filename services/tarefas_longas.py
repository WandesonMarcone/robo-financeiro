"""Tarefas demoradas do Telegram com estado persistente no Neon.

A thread do processo web pode desaparecer quando o Render reinicia. Este módulo
registra a tarefa antes de iniciá-la e a repete com segurança no próximo boot.
O coletor de documentos usa a URL como chave lógica, portanto a retomada não
cria duplicatas.
"""

import json
import logging
import threading
from datetime import datetime

from atualizador_documentos import SessionDB
from pipeline_dados.banco_dados import TarefaLonga

logger = logging.getLogger("robo.tarefas_longas")

TIPO_DOCS_ACOES = "DOCS_ACOES"
STATUS_EM_ANDAMENTO = "EM_ANDAMENTO"
STATUS_CONCLUIDA = "CONCLUIDA"
STATUS_FALHA = "FALHA"


def iniciar_tarefa_docs_acoes(ano, chat_id):
    """Cria uma tarefa única; retorna None se já houver uma ativa."""
    session = SessionDB()
    try:
        ativa = (
            session.query(TarefaLonga)
            .filter(
                TarefaLonga.tipo == TIPO_DOCS_ACOES,
                TarefaLonga.status == STATUS_EM_ANDAMENTO,
            )
            .order_by(TarefaLonga.id.desc())
            .first()
        )
        if ativa is not None:
            return None
        tarefa = TarefaLonga(
            tipo=TIPO_DOCS_ACOES,
            ano=int(ano),
            chat_id=str(chat_id),
            status=STATUS_EM_ANDAMENTO,
            iniciado_em=datetime.now(),
            atualizado_em=datetime.now(),
        )
        session.add(tarefa)
        session.commit()
        return tarefa.id
    finally:
        session.close()


def _atualizar_tarefa(tarefa_id, **campos):
    session = SessionDB()
    try:
        tarefa = session.query(TarefaLonga).filter_by(id=tarefa_id).first()
        if tarefa is None:
            return None
        for nome, valor in campos.items():
            setattr(tarefa, nome, valor)
        tarefa.atualizado_em = datetime.now()
        session.commit()
        return tarefa
    finally:
        session.close()


def _dados_tarefa(tarefa_id):
    session = SessionDB()
    try:
        tarefa = session.query(TarefaLonga).filter_by(id=tarefa_id).first()
        if tarefa is None:
            return None
        return {
            "id": tarefa.id,
            "ano": tarefa.ano,
            "chat_id": tarefa.chat_id,
            "status": tarefa.status,
        }
    finally:
        session.close()


def executar_tarefa_docs_acoes(tarefa_id):
    """Executa ou retoma a varredura e garante uma resposta final."""
    dados = _dados_tarefa(tarefa_id)
    if not dados:
        logger.error("Tarefa de documentos inexistente: %s", tarefa_id)
        return

    chat_id = int(dados["chat_id"])
    ano = int(dados["ano"])
    try:
        from pipeline_dados.coletor_docs_acoes import (
            RelatoriosAcoesCVM,
            STATUS_GRAVADO,
        )

        logger.info("Tarefa DOCS_ACOES iniciada id=%s ano=%s", tarefa_id, ano)
        _atualizar_tarefa(tarefa_id, status=STATUS_EM_ANDAMENTO)
        session = SessionDB()
        try:
            resultado = RelatoriosAcoesCVM(session).vasculhar_documentos(ano)
        finally:
            session.close()

        texto = resultado.mensagem_telegram()
        _atualizar_tarefa(
            tarefa_id,
            status=STATUS_CONCLUIDA,
            resultado=json.dumps(
                {
                    "mensagem": texto,
                    "gravados": resultado.gravados,
                    "ja_existentes": resultado.ja_existentes,
                    "sem_ativo": resultado.sem_ativo,
                    "falhas_persistencia": resultado.falhas_persistencia,
                },
                ensure_ascii=False,
            ),
            concluido_em=datetime.now(),
        )

        from bot.loader import bot

        bot.send_message(chat_id, texto)
        logger.info(
            "Tarefa DOCS_ACOES concluida id=%s gravados=%s existentes=%s",
            tarefa_id,
            resultado.gravados,
            resultado.ja_existentes,
        )

        # Mantém o comportamento anterior: a IA é iniciada depois da coleta.
        # A conclusão da coleta já foi enviada antes desta etapa mais longa.
        if resultado.status == STATUS_GRAVADO and resultado.gravados > 0:
            bot.send_message(
                chat_id,
                "Documentos novos gravados; iniciando classificacao por IA.",
            )
            from atualizador_documentos import rotina_processar_acoes

            resultado_ia = rotina_processar_acoes()
            bot.send_message(chat_id, resultado_ia.mensagem_telegram())
    except Exception as erro:
        logger.exception("Tarefa DOCS_ACOES falhou id=%s", tarefa_id)
        _atualizar_tarefa(
            tarefa_id,
            status=STATUS_FALHA,
            erro=type(erro).__name__,
            resultado=str(erro),
        )
        try:
            from bot.loader import bot

            bot.send_message(
                chat_id,
                f"Varredura de PDFs de acoes ({ano}): falha de processamento "
                f"ou persistencia ({type(erro).__name__}).",
            )
        except Exception:
            logger.exception("Falha ao enviar erro da tarefa id=%s", tarefa_id)


def _iniciar_thread(tarefa_id):
    thread = threading.Thread(
        target=executar_tarefa_docs_acoes,
        args=(tarefa_id,),
        daemon=True,
    )
    thread.start()
    return thread


def retomar_tarefas_interrompidas():
    """Retoma tarefas EM_ANDAMENTO depois de um boot do serviço."""
    try:
        session = SessionDB()
        try:
            tarefas = (
                session.query(TarefaLonga)
                .filter_by(
                    tipo=TIPO_DOCS_ACOES,
                    status=STATUS_EM_ANDAMENTO,
                )
                .all()
            )
            ids = [tarefa.id for tarefa in tarefas]
        finally:
            session.close()
        for tarefa_id in ids:
            logger.warning(
                "Retomando tarefa persistente interrompida id=%s", tarefa_id
            )
            _iniciar_thread(tarefa_id)
    except Exception:
        # Antes da migração, a tabela ainda pode não existir. O boot não deve
        # ser interrompido; a migração será aplicada antes do deploy desta branch.
        logger.warning("Nao foi possivel verificar tarefas persistentes", exc_info=True)
