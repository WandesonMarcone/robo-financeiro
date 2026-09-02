"""Publicação de eventos do Financial Intelligence Core — Fase 7, Etapa 7.7 (aditivo).

Formaliza a fronteira ``EVENTOS/ALERTAS -> NOTIFICAÇÕES`` do Financial Core:

    FONTES -> DATA PIPELINE -> FINANCIAL CORE -> EVENTOS/ALERTAS -> NOTIFICAÇÕES / API

O motor de alertas (``pipeline_dados.motor_alertas``) detecta e persiste o
``AlertaEvento`` (o "Core") e publica o evento através desta pequena interface,
sem depender da implementação do espelhamento 5C (``espelhamento_mercado_5c``).
A integração legada 5C continua consumindo exatamente os mesmos resultados via
``processar_indicadores_ativo`` — nada do fluxo 5C é alterado.

Garantias:
- Erros de publicação são isolados: uma falha aqui nunca derruba o pipeline de
  detecção nem o fluxo 5C.
- Idempotência preservada: reprocessar o mesmo evento não duplica notificações
  (chave ``(evento_id, usuario, tipo, canal)`` do motor ``services.notificacoes``).
- Nenhuma alteração em regras de indicadores, usuários, RBAC, planos ou
  Telegram: este serviço apenas publica eventos para a camada de notificações.
- Import local para evitar ciclo de importação (mesmo padrão do projeto).
"""
import logging

logger = logging.getLogger(__name__)


def publicar_evento(evento, session=None, log=None) -> dict:
    """Publica um evento do Core no motor individual de notificações (Fase 6).

    Encapsula a chamada a ``services.notificacoes.processar_evento`` — o motor
    central que valida o evento, decide a elegibilidade (permissão, vínculo com
    o ativo, preferência, limite do plano e canais) e persiste as notificações
    individualizadas de forma idempotente. Nenhum envio é realizado aqui (a
    entrega é do dispatcher).

    Isola erros: retorna um resumo observável em vez de levantar, para que uma
    falha de publicação nunca interrompa a detecção de alertas nem o fluxo 5C.

    Retorna::

        {
            "publicado": bool,
            "elegiveis": int,
            "geradas": int,
            "ignoradas": int,
            "erro": str | None,
        }

    ``erro`` fica ``None`` quando a publicação é bem-sucedida; ``elegiveis``/
    ``geradas``/``ignoradas`` refletem o resumo do motor de notificações.
    """
    logger_efetivo = log or logger
    evento_id = evento.get("evento_id") if isinstance(evento, dict) else None
    tipo = evento.get("tipo") if isinstance(evento, dict) else None
    try:
        from services.notificacoes import processar_evento

        resumo = processar_evento(evento, session=session)
        logger_efetivo.info(
            "FASE7 publicar_evento tipo=%s evento_id=%s elegiveis=%s geradas=%s "
            "ignoradas=%s",
            resumo["evento"].get("tipo"),
            resumo["evento"].get("evento_id"),
            resumo["elegiveis"],
            resumo["geradas"],
            resumo["ignoradas"],
        )
        return {
            "publicado": True,
            "elegiveis": resumo["elegiveis"],
            "geradas": resumo["geradas"],
            "ignoradas": resumo["ignoradas"],
            "erro": None,
        }
    except Exception as e:
        logger_efetivo.warning(
            "FASE7 publicar_evento falhou sem impedir o fluxo tipo=%s "
            "evento_id=%s: %s",
            tipo, evento_id, e,
        )
        return {
            "publicado": False,
            "elegiveis": 0,
            "geradas": 0,
            "ignoradas": 0,
            "erro": str(e),
        }
