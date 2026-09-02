"""Serviço centralizado de auditoria de acesso (Fase 5, Etapa 2).

Registra eventos de segurança e acesso na tabela ``auditoria_acesso`` de forma
aditiva: respeita ``AUDITORIA_ATIVA``, nunca persiste senha, token, chave de
API ou qualquer segredo (sanitização mínima do ``detalhe``) e uma falha de
gravação jamais derruba o fluxo principal da aplicação.
"""
import logging
import re

import config
from atualizador_documentos import SessionDB
from pipeline_dados.banco_dados import AuditoriaAcesso

logger = logging.getLogger(__name__)

_MASCARA = "[OCULTO]"

# Sanitização mínima: mascara pares chave=valor, valores "bearer" e tokens
# JWT-like que tenham vazado acidentalmente para o detalhe livre.
_PADROES_SEGREDOS = (
    re.compile(r"(?i)((?:senha|password|passwd|token|api[_-]?key|secret)\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(\bbearer\s+)\S+"),
    re.compile(r"\beyJ[a-zA-Z0-9_-]{8,}\.[a-zA-Z0-9_-]{8,}\.[a-zA-Z0-9_-]{8,}\b"),
)


def _mascarar_match(m):
    """Reconstrói o texto mantendo o rótulo e substituindo o valor por máscara."""
    prefixo = m.group(1) if m.lastindex else ""
    return prefixo + _MASCARA


def _sanitizar_detalhe(detalhe):
    """Mascara dados sensíveis que tenham vazado para o detalhe livre.

    Retorna o texto com os valores sensíveis substituídos por ``[OCULTO]``.
    Textos sem segredos passam inalterados.
    """
    if not detalhe:
        return detalhe
    texto = str(detalhe)
    for padrao in _PADROES_SEGREDOS:
        texto = padrao.sub(_mascarar_match, texto)
    return texto


def registrar_evento(acao, alvo=None, detalhe=None, usuario_id=None, ip=None, sucesso=True, session=None):
    """Registra um evento de acesso na trilha de auditoria.

    A auditoria só grava quando ``AUDITORIA_ATIVA`` está habilitada. O serviço
    nunca persiste senha, token, chave de API ou qualquer segredo: ``detalhe``
    passa por sanitização mínima antes de ser salvo. Uma falha na abertura da
    sessão ou na gravação é apenas registrada em log e retorna ``None`` — nunca
    é propagada para o fluxo principal da aplicação.

    Parâmetros:
        acao: rótulo da ação (ex.: "LOGIN", "API_ACESSO", "COMANDO_NEGADO").
        alvo: recurso/alvo opcional afetado pela ação.
        detalhe: texto livre opcional (sanitizado).
        usuario_id: id do usuário; None para eventos sem autenticação.
        ip: endereço IP opcional de origem.
        sucesso: True para sucesso, False para fracasso.
        session: sessão SQLAlchemy opcional. Quando omitida, abre e fecha uma
            sessão própria (padrão do projeto). Sempre faz commit do evento.

    Retorna o registro ``AuditoriaAcesso`` persistido, ou ``None`` quando a
    auditoria está desativada ou ocorre uma falha de gravação.
    """
    if not config.AUDITORIA_ATIVA:
        return None

    evento = AuditoriaAcesso(
        usuario_id=usuario_id,
        acao=acao,
        alvo=alvo,
        detalhe=_sanitizar_detalhe(detalhe),
        ip=ip,
        sucesso=bool(sucesso),
    )

    sessao_propria = False
    if session is None:
        try:
            session = SessionDB()
            sessao_propria = True
        except Exception as e:
            logger.error("Falha ao abrir sessão de auditoria: %s", e)
            return None

    try:
        session.add(evento)
        session.commit()
        return evento
    except Exception as e:
        logger.error("Falha ao registrar evento de auditoria: %s", e)
        try:
            session.rollback()
        except Exception:
            pass
        return None
    finally:
        if sessao_propria:
            try:
                session.close()
            except Exception:
                pass
