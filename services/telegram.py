"""Integração consolidada entre usuários e Telegram (Fase 5, Etapa 8).

Permite que o Telegram reconheça corretamente um ``Usuario`` cadastrado no
banco, sem quebrar o comportamento legado. Esta etapa apenas consolida a
identidade e a gestão administrativa do vínculo; a autenticação de mensagens
continua sendo resolvida por ``modules/seguranca.py`` (DB-first com fallback
legado) e nenhuma sessão é criada por mensagem.

Regras (sem criar regras paralelas — tudo passa pelo motor central):
- Apenas quem possui a permissão ``telegram.administrar`` (SUPERADMIN via ``*``
  ou ADMIN pela matriz) pode vincular/desvincular;
- ADMIN não pode alterar um usuário protegido (SUPERADMIN);
- USER/VISITOR não podem vincular nenhum usuário;
- Tentativas sem permissão ou de escalonamento são auditadas e negadas.

As funções ``vincular_telegram``, ``desvincular_telegram`` e
``buscar_usuario_por_telegram`` de ``services/usuarios.py`` são reutilizadas —
nada é duplicado aqui. Nenhuma senha, token ou segredo é persistido ou
registrado.
"""
import logging

from services import auditoria, autorizacao, usuarios

logger = logging.getLogger(__name__)

# Permissão da matriz central exigida para vincular/desvincular Telegram.
PERMISSAO_VINCULO = "telegram.administrar"

# Eventos de auditoria para tentativas negadas (aplicados apenas no momento da
# negação; nunca contêm segredos).
ACAO_VINCULO_NEGADO = "TELEGRAM_VINCULO_NEGADO"
ACAO_ESCALONAMENTO_NEGADO = "ESCALONAMENTO_NEGADO"


def _alvo(usuario):
    """Rótulo de alvo para auditoria (email quando disponível, senão o id)."""
    if usuario is None:
        return None
    email = getattr(usuario, "email", None)
    return email if email else f"usuario:{usuario.id}"


def usuario_do_telegram(telegram_user_id, session=None):
    """Retorna o ``Usuario`` vinculado ao ``telegram_user_id``, ou ``None``.

    Ponte de identidade: permite que o Telegram represente corretamente um
    usuário cadastrado no banco. Não cria usuários automaticamente e não toca em
    sessões. A validação de ``ativo`` é das camadas de autorização: a central
    (``autorizacao.papel_de``) retorna ``None`` para desativados e o legado
    (``modules/seguranca``) nega funções protegidas.
    """
    if telegram_user_id is None:
        return None
    return usuarios.buscar_usuario_por_telegram(telegram_user_id, session=session)


def _autorizar_vincular(autor, usuario, session, ip):
    """Valida permissão e proteção de SUPERADMIN, auditando tentativas negadas.

    Levanta ``PermissaoNegadaError`` (motor central) quando o ``autor`` não pode
    vincular/desvincular o ``usuario`` alvo. Antes de negar, registra o evento
    correspondente na auditoria (``TELEGRAM_VINCULO_NEGADO`` ou
    ``ESCALONAMENTO_NEGADO``), sem expor segredos.
    """
    try:
        autorizacao.requer_permissao(autor, PERMISSAO_VINCULO)
    except autorizacao.PermissaoNegadaError:
        auditoria.registrar_evento(
            acao=ACAO_VINCULO_NEGADO,
            alvo=_alvo(usuario),
            detalhe="motivo=sem_permissao",
            usuario_id=getattr(autor, "id", None),
            ip=ip,
            sucesso=False,
            session=session,
        )
        raise

    if autorizacao.usuario_protegido(usuario) and not autorizacao.eh_superadmin(autor):
        auditoria.registrar_evento(
            acao=ACAO_ESCALONAMENTO_NEGADO,
            alvo=_alvo(usuario),
            detalhe="motivo=superadmin_protegido",
            usuario_id=getattr(autor, "id", None),
            ip=ip,
            sucesso=False,
            session=session,
        )
        raise autorizacao.PermissaoNegadaError(
            permissao=PERMISSAO_VINCULO,
            papel=autorizacao.papel_de(autor),
            usuario_id=getattr(autor, "id", None),
        )


def vincular_telegram_usuario(
    autor, usuario, telegram_user_id, telegram_chat_id=None, session=None, ip=None
):
    """Vincula um ``telegram_user_id`` a um usuário existente.

    ``autor`` é o ``Usuario`` executando a operação (exige a permissão
    ``telegram.administrar``). Reutiliza ``usuarios.vincular_telegram``, que
    rejeita vínculo duplicado com ``ValueError``, usa ``telegram_user_id`` como
    identidade principal e ``telegram_chat_id`` para comunicação, e registra
    ``TELEGRAM_VINCULADO`` na auditoria. Retorna ``True`` em caso de sucesso.
    """
    _autorizar_vincular(autor, usuario, session, ip)
    return usuarios.vincular_telegram(
        usuario,
        telegram_user_id,
        telegram_chat_id=telegram_chat_id,
        session=session,
        ip=ip,
    )


def desvincular_telegram_usuario(autor, usuario, session=None, ip=None):
    """Remove o vínculo Telegram de um usuário existente.

    Mesmas regras de autorização do vínculo. Reutiliza
    ``usuarios.desvincular_telegram``, que registra ``TELEGRAM_DESVINCULADO``.
    Retorna ``True`` em caso de sucesso.
    """
    _autorizar_vincular(autor, usuario, session, ip)
    return usuarios.desvincular_telegram(usuario, session=session, ip=ip)


# ==========================================
# ENTREGA INDIVIDUAL (Fase 6, Etapa 7)
# ==========================================


def _formatar_notificacao(titulo, mensagem):
    """Texto simples da notificação (sem Markdown frágil, sem segredos)."""
    return f"[NOTIFICACAO] {titulo}\n\n{mensagem}"


def enviar_notificacao(usuario, titulo, mensagem, session=None):
    """Envia uma notificação individual via Telegram para o ``usuario``.

    Usa EXCLUSIVAMENTE o vínculo existente ``Usuario.telegram_user_id`` +
    ``Usuario.telegram_chat_id`` — nenhum chat id é aceito do chamador/cliente.
    Sem vínculo válido, retorna ``False`` sem lançar (o dispatcher decide o
    estado da notificação). Reutiliza o bot existente
    (``bot.loader.enviar_mensagem``): broadcasts, comandos, ``TELEGRAM_CHAT_ID``
    e o comportamento legado permanecem inalterados. Nunca registra chat id,
    token do bot ou qualquer segredo.
    """
    if usuario is None:
        return False
    if getattr(usuario, "telegram_user_id", None) is None:
        return False
    if getattr(usuario, "telegram_chat_id", None) is None:
        return False
    try:
        from bot.loader import enviar_mensagem as _enviar
    except Exception as e:  # pragma: no cover - import do bot indisponível
        logger.warning("Bot indisponível para entrega individual: %s", type(e).__name__)
        return False
    try:
        enviado = _enviar(
            usuario.telegram_chat_id, _formatar_notificacao(titulo, mensagem)
        )
        return enviado is not None
    except Exception:
        logger.warning(
            "Falha transitória na entrega Telegram para o usuário %s.",
            getattr(usuario, "id", None),
        )
        return False
