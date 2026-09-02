"""Seed idempotente do primeiro SUPERADMIN (Fase 5, Etapa 5).

Garante, na inicialização, que o administrador de referência exista na tabela
``usuarios`` com papel ``SUPERADMIN``. A referência é, nesta ordem:

1. ``PRIMEIRO_ADMIN_TELEGRAM_ID`` (configuração explícita da Fase 5);
2. ``TELEGRAM_CHAT_ID`` (dono/operador legado da V1.0.1).

Propriedades (todas cobertas por testes):

- Idempotente: executar mais de uma vez não duplica nem altera o usuário.
- Não sobrescreve usuários existentes: apenas eleva o papel quando o vínculo
  de Telegram já pertence a um usuário com papel inferior (nunca demove e
  nunca altera nome/email/senha/ativação).
- Nunca persiste senha/token/segredo; criação/promoção são registradas na
  auditoria (``SEED_SUPERADMIN`` + eventos padrão do serviço de usuários).
- Uma falha de banco NUNCA é propagada: o seed retorna o status ``erro`` e o
  fluxo principal (bot, webhook, agendador) continua normalmente.
"""
import logging

import config
from atualizador_documentos import SessionDB
from services import auditoria, usuarios

logger = logging.getLogger(__name__)

# Nome padrão atribuído ao SUPERADMIN criado pelo seed. Email e senha ficam
# vazios (o vínculo é via Telegram); o operador pode preenchê-los depois.
NOME_PADRAO_SUPERADMIN = "Administrador"

# Ação de auditoria específica do seed, distinguível dos eventos de usuário.
ACAO_SEED = "SEED_SUPERADMIN"


def obter_telegram_id_superadmin():
    """Telegram ID de referência para o primeiro SUPERADMIN.

    Prioriza ``PRIMEIRO_ADMIN_TELEGRAM_ID``; sem ele, usa o
    ``TELEGRAM_CHAT_ID`` legado (dono/operador). Retorna ``None`` quando
    nenhum ID numérico válido está configurado.
    """
    raw = str(config.PRIMEIRO_ADMIN_TELEGRAM_ID or config.TELEGRAM_CHAT_ID or "").strip()
    return int(raw) if raw.isdigit() else None


def _registrar_seed(session, telegram_id, status, usuario_id, ip):
    """Registra o evento do seed na auditoria (nunca segredos)."""
    auditoria.registrar_evento(
        acao=ACAO_SEED,
        alvo=f"telegram:{telegram_id}",
        detalhe=f"status={status}",
        usuario_id=usuario_id,
        ip=ip,
        session=session,
    )


def garantir_superadmin_inicial(session=None, ip=None):
    """Cria/eleva o primeiro SUPERADMIN de forma idempotente.

    Retorna um dicionário com ``status``:

    - ``criado``: um novo usuário SUPERADMIN foi criado.
    - ``promovido``: um usuário existente com papel inferior foi elevado.
    - ``existente``: o usuário já era SUPERADMIN (seed repetido, nada a fazer).
    - ``sem_alvo``: nenhum Telegram ID de administrador está configurado.
    - ``erro``: falha de banco/inesperada (registrada em log, sem segredos).

    ``session`` é opcional (testes com SQLite em memória); sem ela usa
    ``SessionDB`` padrão do projeto. ``ip`` é registrado na auditoria quando
    informado. Nenhuma exceção é propagada ao chamador.
    """
    try:
        telegram_id = obter_telegram_id_superadmin()
        if telegram_id is None:
            logger.info(
                "Seed do SUPERADMIN ignorado: nenhum Telegram ID de administrador configurado."
            )
            return {"status": "sem_alvo", "usuario_id": None, "telegram_id": None}

        sessao_propria = session is None
        s = session if not sessao_propria else SessionDB()
        try:
            usuario = usuarios.buscar_usuario_por_telegram(telegram_id, session=s)
            if usuario is not None:
                if usuario.papel == usuarios.SUPERADMIN:
                    logger.info(
                        "SUPERADMIN já existe (telegram_user_id=%s); nada a fazer.",
                        telegram_id,
                    )
                    return {"status": "existente", "usuario_id": usuario.id, "telegram_id": telegram_id}
                usuarios.alterar_papel(usuario, usuarios.SUPERADMIN, session=s, ip=ip)
                _registrar_seed(s, telegram_id, "promovido", usuario.id, ip)
                logger.info(
                    "Usuário %s promovido a SUPERADMIN (telegram_user_id=%s).",
                    usuario.id,
                    telegram_id,
                )
                return {"status": "promovido", "usuario_id": usuario.id, "telegram_id": telegram_id}

            try:
                usuario = usuarios.criar_usuario(
                    nome=NOME_PADRAO_SUPERADMIN,
                    papel=usuarios.SUPERADMIN,
                    telegram_user_id=telegram_id,
                    telegram_chat_id=telegram_id,
                    session=s,
                    ip=ip,
                )
            except ValueError:
                # Corrida entre a consulta e a inserção: alguém já criou o
                # vínculo. Reconsulta e trata como existente/promovido.
                usuario = usuarios.buscar_usuario_por_telegram(telegram_id, session=s)
                if usuario is None:
                    return {"status": "erro", "usuario_id": None, "telegram_id": telegram_id}
                if usuario.papel != usuarios.SUPERADMIN:
                    usuarios.alterar_papel(usuario, usuarios.SUPERADMIN, session=s, ip=ip)
                    _registrar_seed(s, telegram_id, "promovido", usuario.id, ip)
                    return {"status": "promovido", "usuario_id": usuario.id, "telegram_id": telegram_id}
                return {"status": "existente", "usuario_id": usuario.id, "telegram_id": telegram_id}

            _registrar_seed(s, telegram_id, "criado", usuario.id, ip)
            logger.info(
                "SUPERADMIN criado (usuario_id=%s, telegram_user_id=%s).",
                usuario.id,
                telegram_id,
            )
            return {"status": "criado", "usuario_id": usuario.id, "telegram_id": telegram_id}
        finally:
            if sessao_propria:
                s.close()
    except Exception as e:
        logger.error(
            "Falha no seed do SUPERADMIN (%s); o sistema continua sem o seed.",
            type(e).__name__,
        )
        return {"status": "erro", "usuario_id": None, "telegram_id": None}
