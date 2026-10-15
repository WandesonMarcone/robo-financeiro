"""Autocadastro de usuários e aprovação pelo administrador (Fase 2 / Etapa 2).

Fluxo:

1. Um usuário desconhecido envia ``/start``. Ele é identificado pelo
   ``telegram_user_id`` e uma solicitação ``pendente`` é criada (sem duplicar
   contas existentes). O ``telegram_chat_id`` é registrado para entrega das
   respostas.
2. O administrador recebe a solicitação com botões de aprovar/rejeitar.
3. A decisão é aplicada de forma idempotente e o usuário é notificado.

Regras de projeto respeitadas:

* não altera o schema, não executa migrações e não cria o administrador;
* usuários já autorizados por ``config`` continuam entrando direto no menu;
* toda decisão administrativa é revalidada no servidor (o papel nunca vem do
  callback);
* nenhum token, credencial ou URL de banco é registrado em log.
"""

import logging

from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
from bot import permissoes
from bot.loader import bot
from bot.telegram_utils import (
    TEXTO_ACESSO_NEGADO,
    TEXTO_MENU_INICIAL,
    construir_menu_inicial,
)
from pipeline_dados.modelos_usuarios import (
    STATUS_APROVADO,
    STATUS_PENDENTE,
    STATUS_REJEITADO,
    STATUS_SUSPENSO,
)
from pipeline_dados.repositorio_usuarios import RepositorioUsuarios

logger = logging.getLogger("robo.cadastro")
# Trilha de auditoria das decisoes administrativas de cadastro. A tabela
# `auditoria_acesso` existe no banco, mas o seu esquema nao esta declarado neste
# repositorio; para nao inventar colunas nem alterar o Neon, as decisoes sao
# registradas nesta trilha estruturada de logs (ver `_registrar_auditoria`).
logger_auditoria = logging.getLogger("robo.auditoria")

PREFIXO_CALLBACK = "cad_"
ACAO_APROVAR = "aprovar"
ACAO_REJEITAR = "rejeitar"

TEXTO_PENDENTE = (
    "⏳ Solicitação recebida!\n\n"
    "Seu cadastro está aguardando aprovação do administrador. "
    "Você será avisado assim que for liberado."
)
TEXTO_REJEITADO = "🚫 Seu acesso foi recusado pelo administrador."
TEXTO_SUSPENSO = "⛔ Seu acesso está suspenso. Fale com o administrador."
TEXTO_CADASTRO_INDISPONIVEL = (
    "⚠️ Não foi possível concluir o cadastro agora. Tente novamente mais tarde."
)
TEXTO_APROVADO = "✅ Seu acesso foi liberado! Bem-vindo(a)."


def _id_do_autor(message_or_call):
    """Telegram ID do autor a partir de uma ``Message`` ou ``CallbackQuery``.

    Diferente de ``permissoes.usuario_id_do_update`` (que recebe um ``Update``),
    os handlers recebem o objeto já desmembrado. Em um callback, o autor é
    ``from_user`` (nunca o ``from_user`` da mensagem, que é o próprio bot).
    """
    from_user = getattr(message_or_call, "from_user", None)
    if from_user is not None:
        return getattr(from_user, "id", None)
    chat = getattr(message_or_call, "chat", None)
    return getattr(chat, "id", None)


def _chat_id_da_mensagem(message):
    chat = getattr(message, "chat", None)
    return getattr(chat, "id", None) if chat is not None else None


def _nome_de_exibicao(message):
    from_user = getattr(message, "from_user", None)
    if from_user is None:
        return None
    partes = [
        getattr(from_user, "first_name", None),
        getattr(from_user, "last_name", None),
    ]
    nome = " ".join(p for p in partes if p).strip()
    if nome:
        return nome
    username = getattr(from_user, "username", None)
    return f"@{username}" if username else None


def _enviar_texto(chat_id, texto, **kwargs):
    if chat_id is None:
        return
    try:
        bot.send_message(chat_id, texto, **kwargs)
    except Exception:
        logger.warning(
            "CADASTRO - falha ao enviar mensagem ao usuario (chat oculto)",
            exc_info=True,
        )


def _enviar_menu(chat_id):
    if chat_id is None:
        return
    try:
        bot.send_message(
            chat_id,
            TEXTO_MENU_INICIAL,
            reply_markup=construir_menu_inicial(),
            parse_mode="Markdown",
        )
    except Exception:
        logger.warning("CADASTRO - falha ao enviar menu", exc_info=True)


def _responder_status(chat_id, dto):
    if dto is None:
        _enviar_texto(chat_id, TEXTO_CADASTRO_INDISPONIVEL)
        return
    if dto.status == STATUS_APROVADO:
        _enviar_menu(chat_id)
    elif dto.status == STATUS_REJEITADO:
        _enviar_texto(chat_id, TEXTO_REJEITADO)
    elif dto.status == STATUS_SUSPENSO:
        _enviar_texto(chat_id, TEXTO_SUSPENSO)
    else:
        _enviar_texto(chat_id, TEXTO_PENDENTE)


def _registrar_auditoria(autor_id, solicitacao_id, acao, resultado):
    """Registra a decisao administrativa numa trilha de auditoria verificavel.

    A tabela ``auditoria_acesso`` existe no banco de producao, mas seu esquema
    (colunas) nao esta declarado neste repositorio. Para nao presumir colunas
    inexistentes nem tocar o Neon, a decisao e registrada na infraestrutura de
    auditoria compatível disponivel no codigo: a trilha estruturada de logs.
    Nenhum token ou credencial e registrado; apenas identificadores de Telegram
    (ja presentes nos logs de permissao do projeto) e o id interno da
    solicitacao.
    """
    logger_auditoria.info(
        "AUDITORIA_CADASTRO autor=%s solicitacao=%s acao=%s resultado=%s",
        autor_id,
        solicitacao_id,
        acao,
        resultado,
    )


def _chat_do_administrador():
    """Chat de destino das solicitacoes: admin configurado no ambiente.

    Prioriza ``config.TELEGRAM_ADMIN_ID`` (administrador explicito) e recorre a
    ``config.TELEGRAM_CHAT_ID`` como compatibilidade com a configuracao atual.
    """
    return getattr(config, "TELEGRAM_ADMIN_ID", None) or getattr(
        config, "TELEGRAM_CHAT_ID", None
    )


def _notificar_admin(dto, nome):
    chat_admin = _chat_do_administrador()
    if chat_admin is None:
        return
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton(
            "✅ Aprovar", callback_data=f"{PREFIXO_CALLBACK}{ACAO_APROVAR}_{dto.id}"
        ),
        InlineKeyboardButton(
            "🚫 Rejeitar", callback_data=f"{PREFIXO_CALLBACK}{ACAO_REJEITAR}_{dto.id}"
        ),
    )
    identificacao = nome or "Usuario sem nome"
    texto = (
        "🔔 *Nova solicitação de acesso*\n\n"
        f"📄 Solicitação #{dto.id}\n"
        f"👤 {identificacao}\n"
        "Deseja liberar o acesso a este usuário?"
    )
    try:
        bot.send_message(chat_admin, texto, reply_markup=markup, parse_mode="Markdown")
    except Exception:
        logger.warning("CADASTRO - falha ao notificar o administrador", exc_info=True)


def _notificar_usuario(dto):
    if dto is None:
        return
    destino = dto.telegram_chat_id or dto.telegram_user_id
    if destino is None:
        return
    if dto.status == STATUS_APROVADO:
        _enviar_texto(destino, TEXTO_APROVADO + "\n\nEnvie /start para começar.")
    elif dto.status == STATUS_REJEITADO:
        _enviar_texto(destino, TEXTO_REJEITADO)
    elif dto.status == STATUS_SUSPENSO:
        _enviar_texto(destino, TEXTO_SUSPENSO)


def _parse_decisao(dados):
    """Extrai ``(acao, usuario_id)`` de um callback ``cad_<acao>_<id>``."""
    partes = (dados or "").split("_")
    if len(partes) != 3 or partes[0] != "cad":
        return None, None
    acao = partes[1]
    if acao not in (ACAO_APROVAR, ACAO_REJEITAR):
        return None, None
    try:
        return acao, int(partes[2])
    except (TypeError, ValueError):
        return None, None


@bot.message_handler(commands=[permissoes.COMANDO_CADASTRO])
def iniciar_cadastro(message):
    """Ponto de entrada público de autocadastro (``/start``)."""
    usuario_id = _id_do_autor(message)
    chat_id = _chat_id_da_mensagem(message)
    if usuario_id is None:
        _enviar_texto(chat_id, TEXTO_CADASTRO_INDISPONIVEL)
        return

    papel = permissoes.obter_papel(usuario_id)
    if papel is not None:
        _enviar_menu(chat_id)
        return

    try:
        repositorio = RepositorioUsuarios()
        dto, criado = repositorio.criar_solicitacao(
            usuario_id,
            chat_id,
            nome=_nome_de_exibicao(message),
        )
        if dto is not None and not criado:
            dto = repositorio.atualizar_chat_id(dto.id, chat_id) or dto
    except Exception:
        logger.warning("CADASTRO - falha ao registrar solicitacao", exc_info=True)
        _enviar_texto(chat_id, TEXTO_CADASTRO_INDISPONIVEL)
        return

    if criado:
        _notificar_admin(dto, _nome_de_exibicao(message))
    _responder_status(chat_id, dto)


@bot.callback_query_handler(
    func=lambda call: bool(call.data) and call.data.startswith(PREFIXO_CALLBACK)
)
def processar_decisao(call):
    """Aprovação/rejeição pelo administrador, revalidada no servidor."""
    autor_id = _id_do_autor(call)
    if permissoes.obter_papel(autor_id) != config.PAPEL_ADMIN:
        logger.warning("CADASTRO - decisao negada (autor nao admin)")
        _registrar_auditoria(autor_id, None, "decisao_negada", "autor_nao_admin")
        try:
            bot.answer_callback_query(call.id, text=TEXTO_ACESSO_NEGADO)
        except Exception:
            logger.debug("CADASTRO - falha ao responder negacao", exc_info=True)
        return

    acao, usuario_id = _parse_decisao(call.data)
    if acao is None or usuario_id is None:
        _registrar_auditoria(autor_id, None, "decisao_negada", "callback_invalido")
        try:
            bot.answer_callback_query(call.id, text=TEXTO_ACESSO_NEGADO)
        except Exception:
            logger.debug("CADASTRO - falha ao responder negacao", exc_info=True)
        return

    try:
        repositorio = RepositorioUsuarios()
        if acao == ACAO_APROVAR:
            dto, mudou = repositorio.aprovar(usuario_id)
            rotulo = "aprovado"
            texto_resultado = "✅ Solicitação APROVADA."
        else:
            dto, mudou = repositorio.rejeitar(usuario_id)
            rotulo = "rejeitado"
            texto_resultado = "🚫 Solicitação REJEITADA."
    except Exception:
        logger.warning("CADASTRO - falha ao aplicar decisao", exc_info=True)
        _registrar_auditoria(autor_id, usuario_id, acao, "falha_banco")
        try:
            bot.answer_callback_query(call.id, text=TEXTO_CADASTRO_INDISPONIVEL)
        except Exception:
            logger.debug("CADASTRO - falha ao responder erro", exc_info=True)
        return

    if dto is None:
        _registrar_auditoria(autor_id, usuario_id, acao, "solicitacao_inexistente")
        try:
            bot.answer_callback_query(call.id, text=TEXTO_CADASTRO_INDISPONIVEL)
        except Exception:
            logger.debug("CADASTRO - falha ao responder erro", exc_info=True)
        return

    _registrar_auditoria(
        autor_id, usuario_id, acao, "aplicada" if mudou else "ja_constava"
    )

    feedback = texto_resultado if mudou else f"ℹ️ Já constava como {rotulo}."
    try:
        bot.answer_callback_query(call.id, text=feedback)
    except Exception:
        logger.debug("CADASTRO - falha ao responder callback", exc_info=True)

    _atualizar_mensagem_admin(call, texto_resultado)

    if mudou:
        _notificar_usuario(dto)


def _atualizar_mensagem_admin(call, texto_resultado):
    message = getattr(call, "message", None)
    if message is None:
        return
    chat = getattr(message, "chat", None)
    chat_id = getattr(chat, "id", None)
    msg_id = getattr(message, "message_id", None)
    if chat_id is None or msg_id is None:
        return
    try:
        bot.edit_message_text(texto_resultado, chat_id, msg_id)
    except Exception:
        logger.debug("CADASTRO - falha ao editar mensagem do admin", exc_info=True)
