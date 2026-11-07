"""Registro resiliente de auditoria para a Central de Controle.

As funções nunca interrompem uma coleta ou uma mensagem caso o registro de
auditoria esteja temporariamente indisponível.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def iniciar_evento(tipo: str, *, origem: str = "SISTEMA", ticker: str | None = None,
                   mensagem: str | None = None, detalhes: dict | None = None) -> int | None:
    try:
        from atualizador_documentos import SessionDB
        from pipeline_dados.banco_dados import EventoOperacional
        session = SessionDB()
        try:
            evento = EventoOperacional(
                tipo=tipo, origem=origem, ticker=ticker, status="EM_ANDAMENTO",
                mensagem=mensagem,
                detalhes=json.dumps(detalhes, ensure_ascii=False) if detalhes else None,
            )
            session.add(evento)
            session.commit()
            return evento.id
        finally:
            session.close()
    except Exception:
        logger.debug("Não foi possível iniciar evento de auditoria.", exc_info=True)
        return None


def concluir_evento(evento_id: int | None, *, sucesso: bool, mensagem: str | None = None,
                    erro: str | None = None) -> None:
    if not evento_id:
        return
    try:
        from atualizador_documentos import SessionDB
        from pipeline_dados.banco_dados import EventoOperacional
        session = SessionDB()
        try:
            evento = session.get(EventoOperacional, evento_id)
            if evento:
                evento.status = "CONCLUIDA" if sucesso else "FALHOU"
                evento.concluido_em = datetime.now()
                if mensagem:
                    evento.mensagem = mensagem
                if erro:
                    evento.erro = erro[:1000]
                session.commit()
        finally:
            session.close()
    except Exception:
        logger.debug("Não foi possível concluir evento de auditoria.", exc_info=True)


def registrar_progresso(evento_id: int | None, mensagem: str) -> None:
    """Acrescenta uma linha curta de progresso, preservando no máximo 30."""
    if not evento_id:
        return
    try:
        from atualizador_documentos import SessionDB
        from pipeline_dados.banco_dados import EventoOperacional
        session = SessionDB()
        try:
            evento = session.get(EventoOperacional, evento_id)
            if evento:
                try:
                    detalhes = json.loads(evento.detalhes or "{}")
                except (TypeError, ValueError):
                    detalhes = {}
                linhas = list(detalhes.get("progress") or [])[-29:]
                linhas.append({"at": datetime.now().isoformat(), "message": str(mensagem)[:500]})
                detalhes["progress"] = linhas
                evento.detalhes = json.dumps(detalhes, ensure_ascii=False)
                session.commit()
        finally:
            session.close()
    except Exception:
        logger.debug("Não foi possível registrar progresso.", exc_info=True)


def registrar_resultado(evento_id: int | None, resultado: dict) -> None:
    """Anexa resultado estruturado, limitado, de uma operação administrativa."""
    if not evento_id:
        return
    try:
        from atualizador_documentos import SessionDB
        from pipeline_dados.banco_dados import EventoOperacional
        session = SessionDB()
        try:
            evento = session.get(EventoOperacional, evento_id)
            if evento:
                try:
                    detalhes = json.loads(evento.detalhes or "{}")
                except (TypeError, ValueError):
                    detalhes = {}
                detalhes["resultado"] = resultado
                evento.detalhes = json.dumps(detalhes, ensure_ascii=False)
                session.commit()
        finally:
            session.close()
    except Exception:
        logger.debug("Não foi possível registrar resultado estruturado.", exc_info=True)


def registrar_notificacao(tipo: str, *, ticker: str | None = None,
                          destinatario: str | int | None = None,
                          resumo: str | None = None, enviada: bool = False,
                          erro: str | None = None) -> None:
    try:
        from atualizador_documentos import SessionDB
        from pipeline_dados.banco_dados import HistoricoNotificacao
        session = SessionDB()
        try:
            session.add(HistoricoNotificacao(
                tipo=tipo, ticker=ticker, destinatario=str(destinatario) if destinatario else None,
                status="ENVIADA" if enviada else "FALHOU",
                resumo=(resumo or "")[:1500] or None, erro=(erro or "")[:1000] or None,
                enviado_em=datetime.now() if enviada else None,
            ))
            session.commit()
        finally:
            session.close()
    except Exception:
        logger.debug("Não foi possível registrar notificação.", exc_info=True)
