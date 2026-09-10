"""Integração consolidada entre usuários e Telegram (Fase 5/10).

A identidade do Telegram é sempre um ``Usuario`` existente: não há uma segunda
conta. O vínculo administrativo continua exigindo ``telegram.administrar``; o
autoatendimento (Etapa 10.2) prova a sessão web/API já emitida e grava o
``telegram_user_id`` no mesmo registro.

Nenhuma senha, token ou segredo é persistido ou registrado.
"""
import hmac
import logging

import config
from services import auditoria, autorizacao, escopo, sessoes, usuarios

logger = logging.getLogger(__name__)

FLUXO_PUBLICO = "publico"
FLUXO_USUARIO = "usuario"
FLUXO_OPERACIONAL = "operacional"

HEADER_WEBHOOK_SECRET = "X-Telegram-Bot-Api-Secret-Token"

ACAO_VINCULO_SESSAO_NEGADO = "TELEGRAM_VINCULO_SESSAO_NEGADO"

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


def payload_comando_start(texto):
    """Extrai o payload de ``/start`` (token de sessão), ou string vazia.

    Não interpreta o payload: o token só é validado em
    ``vincular_telegram_por_sessao``. Aceita ``/start@Bot payload``.
    """
    if not isinstance(texto, str) or not texto.strip():
        return ""
    partes = texto.strip().split(maxsplit=1)
    comando = partes[0].split("@", 1)[0]
    if comando != "/start":
        return ""
    if len(partes) < 2:
        return ""
    return partes[1].strip()


def fluxo_do_telegram(telegram_user_id, session=None):
    """Classifica o Telegram em PUBLICO, USUARIO ou OPERACIONAL.

    USUARIO/OPERACIONAL exigem ``Usuario`` vinculado e ativo. Sem vínculo, só o
    operador legado (``modules.seguranca.eh_admin``) entra em OPERACIONAL.
    Desativado e VISITOR permanecem PUBLICO. Não cria usuário nem sessão.
    """
    usuario = usuario_do_telegram(telegram_user_id, session=session)
    if usuario is not None:
        papel = autorizacao.papel_de(usuario)
        if papel in (autorizacao.SUPERADMIN, autorizacao.ADMIN):
            return FLUXO_OPERACIONAL, usuario
        if papel == autorizacao.USER:
            return FLUXO_USUARIO, usuario
        return FLUXO_PUBLICO, usuario
    try:
        from modules import seguranca

        if seguranca.eh_admin(telegram_user_id):
            return FLUXO_OPERACIONAL, None
    except Exception as e:
        logger.warning(
            "Falha ao resolver operador legado (%s); tratando como publico.",
            type(e).__name__,
        )
    return FLUXO_PUBLICO, None


def comando_permitido(telegram_user_id, fluxo_minimo, session=None):
    """True quando o Telegram atende o fluxo mínimo (sem enumerar usuários)."""
    fluxo, _usuario = fluxo_do_telegram(telegram_user_id, session=session)
    if fluxo_minimo == FLUXO_PUBLICO:
        return True
    if fluxo_minimo == FLUXO_USUARIO:
        return fluxo in (FLUXO_USUARIO, FLUXO_OPERACIONAL)
    if fluxo_minimo == FLUXO_OPERACIONAL:
        return fluxo == FLUXO_OPERACIONAL
    return False


def recurso_visivel_para_telegram(
    telegram_user_id, recurso, permissao_administrativa=None, session=None
):
    """Devolve ``recurso`` só se o Usuario vinculado puder acessá-lo.

    Sem vínculo, recurso inexistente ou acesso negado: ``None`` (anti-IDOR).
    Reutiliza ``services.escopo``.
    """
    usuario = usuario_do_telegram(telegram_user_id, session=session)
    if usuario is None:
        return None
    if not escopo.usuario_pode_acessar(usuario, recurso, permissao_administrativa):
        return None
    return recurso


def vincular_telegram_por_sessao(
    token, telegram_user_id, telegram_chat_id=None, session=None, ip=None
):
    """Vincula o Telegram ao Usuario da sessão web/API já autenticada.

    Falhas (token inválido, sessão expirada, Telegram/usuário já vinculados a
    outra conta) retornam ``None`` com a mesma auditoria genérica — sem revelar
    qual etapa falhou e sem registrar o token. Não cria Usuario. Não usa a
    permissão administrativa: o dono da sessão só vincula a si mesmo.
    """
    def _negar(motivo, usuario_id=None):
        auditoria.registrar_evento(
            acao=ACAO_VINCULO_SESSAO_NEGADO,
            detalhe=f"motivo={motivo}",
            usuario_id=usuario_id,
            ip=ip,
            sucesso=False,
            session=session,
        )
        return None

    if telegram_user_id is None:
        return _negar("telegram_ausente")
    usuario = sessoes.validar_sessao(token, session=session)
    if usuario is None:
        return _negar("sessao_invalida")

    existente = usuarios.buscar_usuario_por_telegram(telegram_user_id, session=session)
    if existente is not None and existente.id != usuario.id:
        return _negar("telegram_em_uso", usuario_id=usuario.id)

    vinculado = getattr(usuario, "telegram_user_id", None)
    if vinculado is not None and vinculado != telegram_user_id:
        return _negar("usuario_ja_vinculado", usuario_id=usuario.id)

    try:
        usuarios.vincular_telegram(
            usuario,
            telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            session=session,
            ip=ip,
        )
    except ValueError:
        return _negar("vinculo_rejeitado", usuario_id=usuario.id)
    return usuario


def webhook_secret_configurado():
    """True quando ``TELEGRAM_WEBHOOK_SECRET`` está definido no ambiente."""
    return bool((getattr(config, "TELEGRAM_WEBHOOK_SECRET", None) or "").strip())


def webhook_secret_valido(header_value):
    """Compara o header do Telegram com o segredo do ambiente (constant-time).

    Sem segredo configurado, retorna True (compatibilidade com o webhook legado
    autenticado só pelo path). Nunca registra o valor recebido ou o esperado.
    """
    esperado = (getattr(config, "TELEGRAM_WEBHOOK_SECRET", None) or "").strip()
    if not esperado:
        return True
    recebido = header_value if isinstance(header_value, str) else ""
    try:
        return hmac.compare_digest(recebido, esperado)
    except (TypeError, ValueError):
        return False


def webhook_autorizado(content_type, secret_header):
    """True somente para JSON com secret_token válido (quando configurado)."""
    if content_type != "application/json":
        return False
    return webhook_secret_valido(secret_header)


def parametros_set_webhook(url):
    """Kwargs de ``set_webhook``: inclui ``secret_token`` só se configurado."""
    params = {"url": url}
    secret = (getattr(config, "TELEGRAM_WEBHOOK_SECRET", None) or "").strip()
    if secret:
        params["secret_token"] = secret
    return params

