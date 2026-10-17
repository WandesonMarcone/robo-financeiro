"""Favoritos individuais por usuário (Etapa 3).

Interface do bot para gerenciar os ativos acompanhados de cada usuário,
persistidos na tabela existente ``ativos_acompanhados`` via
``pipeline_dados.repositorio_favoritos``.

Regras de projeto respeitadas:

* somente usuários aprovados no banco podem usar os favoritos;
* a identidade é sempre resolvida pelo Telegram ID (nunca por dados do
  callback/parametros) e o ``usuario_id`` persistente vem da tabela ``usuarios``;
* um usuário só enxerga e altera os próprios favoritos;
* falhas de banco ou de autorização bloqueiam a operação (falha segura);
* nenhuma tabela/ativo é criado e o banco de produção não é alterado;
* os handlers são registrados com filtros específicos e devem ser importados
  antes de ``bot.callbacks_menus`` (que registra um handler genérico) para que
  os callbacks de favoritos não sejam capturados pelo genérico.
"""

import logging

from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
from bot.loader import bot
from bot.telegram_utils import TEXTO_ACESSO_NEGADO
from bot import permissoes
from pipeline_dados.repositorio_favoritos import (
    AtivoNaoCadastradoError,
    RepositorioFavoritos,
)
from pipeline_dados.repositorio_usuarios import RepositorioUsuarios

logger = logging.getLogger("robo.favoritos")

# Callbacks existentes (botões "⭐ Meus Favoritos" nos menus de FIIs/Ações).
TIPO_POR_CALLBACK = {
    "favoritos_fiis": "fii",
    "favoritos_acoes": "acao",
}

PREFIXO_LISTAR_ADICIONAR = "favadd_"
PREFIXO_ADICIONAR = "favnew_"
PREFIXO_REMOVER = "favrem_"

TAMANHO_PAGINA = 12

VOLTAR_MENU = {"fii": "menu_fiis", "acao": "menu_acoes"}
ROTULO_TIPO = {"fii": "FIIs", "acao": "Ações"}

TEXTO_ERRO_BANCO = "⚠️ Não foi possível acessar seus favoritos agora. Tente novamente."
TEXTO_SEM_CONTA = (
    "🔒 Seus favoritos exigem uma conta aprovada. "
    "Envie /start para iniciar o cadastro."
)


def _id_do_autor(message_or_call):
    """Telegram ID do autor a partir de uma ``Message`` ou ``CallbackQuery``."""
    from_user = getattr(message_or_call, "from_user", None)
    if from_user is not None:
        return getattr(from_user, "id", None)
    chat = getattr(message_or_call, "chat", None)
    return getattr(chat, "id", None)


def _chat_e_message(message_or_call):
    message = getattr(message_or_call, "message", None)
    if message is not None:
        chat = getattr(message, "chat", None)
        return (
            getattr(chat, "id", None) if chat is not None else None,
            getattr(message, "message_id", None),
        )
    chat = getattr(message_or_call, "chat", None)
    return (getattr(chat, "id", None) if chat is not None else None, None)


def _resolver_usuario_autorizado(message_or_call):
    """Resolve o ``usuario_id`` do banco a partir do Telegram ID autenticado.

    Retorna ``(usuario_id, None)`` em caso de sucesso ou ``(None, texto)`` com a
    razão da negativa. Nunca aceita um ``usuario_id`` fornecido pelo cliente.
    Qualquer falha (banco indisponível, conta não registrada ou não aprovada)
    resulta em negativa.
    """
    telegram_id = _id_do_autor(message_or_call)
    if telegram_id is None:
        return None, TEXTO_ACESSO_NEGADO

    # Autorização geral (admin/usuário autorizado). Falha segura -> negado.
    try:
        papel = permissoes.obter_papel(telegram_id)
    except Exception:
        logger.warning("FAVORITOS - falha ao verificar autorizacao", exc_info=True)
        return None, TEXTO_ERRO_BANCO
    if papel is None:
        return None, TEXTO_ACESSO_NEGADO

    # Conta persistente: favoritos exigem um registro real em `usuarios`, pois
    # as associacoes dependem do `usuario_id`.
    try:
        dto = RepositorioUsuarios().obter_por_telegram_id(telegram_id)
    except Exception:
        logger.warning("FAVORITOS - falha ao resolver usuario", exc_info=True)
        return None, TEXTO_ERRO_BANCO
    if dto is None:
        return None, TEXTO_SEM_CONTA

    # O administrador autorizado pela configuracao (papel ja validado pelo
    # sistema de permissoes em `obter_papel`) nao e barrado pelo estado do
    # cadastro: o acesso administrativo nao depende de `status_cadastro` e o
    # registro acima basta para suas associacoes de favoritos. A decisao usa
    # SOMENTE o papel resolvido por `permissoes` -- nunca um papel armazenado no
    # banco (ex.: 'SUPERADMIN'). Usuarios comuns seguem exigindo cadastro
    # aprovado e conta ativa.
    if papel != permissoes.PAPEL_ADMIN and (not dto.esta_aprovado() or not dto.ativo):
        return None, TEXTO_SEM_CONTA
    return dto.id, None


def _e_admin(message_or_call):
    """True se o autor é o administrador (papel resolvido por ``permissoes``)."""
    try:
        return (
            permissoes.obter_papel(_id_do_autor(message_or_call))
            == permissoes.PAPEL_ADMIN
        )
    except Exception:
        logger.warning("FAVORITOS - falha ao verificar papel", exc_info=True)
        return False


def _destino_voltar(tipo, admin):
    """Destino do botão Voltar.

    O administrador volta aos módulos gerais de FIIs/Ações; o usuário comum não
    tem acesso a eles (consulta geral é exclusiva do admin) e volta ao submenu
    de gerenciamento de favoritos.
    """
    return VOLTAR_MENU[tipo] if admin else "gerenciar_favoritos"


def _limite_do_tipo(tipo):
    """Limite máximo configurado para o tipo (``None`` = sem limite).

    Os valores vêm de ``config.FAVORITOS_LIMITES`` (por tipo, via ambiente).
    Nenhum número definitivo é assumido aqui.
    """
    limites = getattr(config, "FAVORITOS_LIMITES", None) or {}
    return limites.get(tipo)


def _responder_callback(call, texto):
    try:
        bot.answer_callback_query(call.id, text=texto)
    except Exception:
        logger.debug("FAVORITOS - falha ao responder callback", exc_info=True)


def _render(call, texto, markup):
    chat_id, msg_id = _chat_e_message(call)
    if chat_id is None:
        return
    try:
        if msg_id is not None:
            bot.edit_message_text(
                texto, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown"
            )
        else:
            bot.send_message(chat_id, texto, reply_markup=markup, parse_mode="Markdown")
    except Exception:
        logger.warning("FAVORITOS - falha ao exibir tela", exc_info=True)


def _markup_favoritos(favoritos, tipo, admin=False):
    markup = InlineKeyboardMarkup(row_width=2)
    for favorito in favoritos:
        if admin:
            # Administrador gerencia os próprios favoritos diretamente.
            acao = InlineKeyboardButton(
                "❌",
                callback_data=f"{PREFIXO_REMOVER}{favorito.ticker}_{tipo}",
            )
        else:
            # Usuário comum não altera favorito ativo diretamente: pede troca
            # (exige aprovação do administrador).
            acao = InlineKeyboardButton(
                "🔁 Trocar",
                callback_data=f"troca_ini_{favorito.ticker}_0",
            )
        markup.row(
            InlineKeyboardButton(
                f"📊 {favorito.ticker}",
                callback_data=f"painel_{favorito.ticker}_{tipo}",
            ),
            acao,
        )
    markup.row(
        InlineKeyboardButton(
            "➕ Adicionar", callback_data=f"{PREFIXO_LISTAR_ADICIONAR}{tipo}_0"
        )
    )
    markup.row(
        InlineKeyboardButton("🔙 Voltar", callback_data=_destino_voltar(tipo, admin))
    )
    return markup


def _texto_favoritos(favoritos, tipo, admin=False):
    rotulo = ROTULO_TIPO[tipo]
    if not favoritos:
        return (
            f"⭐ *Seus Ativos Favoritos ({rotulo})*\n\n"
            "📭 Você ainda não acompanha nenhum ativo. "
            "Toque em ➕ Adicionar para escolher."
        )
    linhas = "\n".join(f"• {favorito.ticker}" for favorito in favoritos)
    return (
        f"⭐ *Seus Ativos Favoritos ({rotulo})*\n\n"
        f"{linhas}\n\n"
        + (
            "Toque em um ativo para abrir o painel, ou em ❌ para remover:"
            if admin
            else "Toque em um ativo para abrir o painel, ou em 🔁 Trocar para "
            "pedir a substituição (sujeita à aprovação do administrador):"
        )
    )


def _mostrar_favoritos(call, tipo, usuario_id, aviso=None):
    admin = _e_admin(call)
    try:
        favoritos = RepositorioFavoritos().listar(usuario_id, tipo)
    except Exception:
        logger.warning("FAVORITOS - falha ao listar", exc_info=True)
        _responder_callback(call, TEXTO_ERRO_BANCO)
        _render(
            call,
            TEXTO_ERRO_BANCO,
            InlineKeyboardMarkup().add(
                InlineKeyboardButton(
                    "🔙 Voltar", callback_data=_destino_voltar(tipo, admin)
                )
            ),
        )
        return
    if aviso:
        _responder_callback(call, aviso)
    _render(
        call,
        _texto_favoritos(favoritos, tipo, admin),
        _markup_favoritos(favoritos, tipo, admin),
    )


def _mostrar_disponiveis(call, tipo, usuario_id, pagina):
    try:
        disponiveis = RepositorioFavoritos().listar_disponiveis(usuario_id, tipo)
    except Exception:
        logger.warning("FAVORITOS - falha ao listar disponiveis", exc_info=True)
        _responder_callback(call, TEXTO_ERRO_BANCO)
        _render(
            call,
            TEXTO_ERRO_BANCO,
            InlineKeyboardMarkup().add(
                InlineKeyboardButton(
                    "🔙 Voltar", callback_data=f"favoritos_{'fiis' if tipo == 'fii' else 'acoes'}"
                )
            ),
        )
        return

    total = len(disponiveis)
    total_paginas = max(1, (total + TAMANHO_PAGINA - 1) // TAMANHO_PAGINA)
    pagina = max(0, min(pagina, total_paginas - 1))
    inicio = pagina * TAMANHO_PAGINA
    fatia = disponiveis[inicio : inicio + TAMANHO_PAGINA]

    markup = InlineKeyboardMarkup(row_width=3)
    if fatia:
        botoes = [
            InlineKeyboardButton(
                ticker, callback_data=f"{PREFIXO_ADICIONAR}{ticker}_{tipo}"
            )
            for ticker in fatia
        ]
        markup.add(*botoes)
        lista_tickers = " · ".join(fatia)
        texto = (
            f"➕ *Adicionar aos Favoritos ({ROTULO_TIPO[tipo]})*\n\n"
            f"Página {pagina + 1}/{total_paginas}. Toque em um ativo para acompanhá-lo.\n\n"
            f"{lista_tickers}"
        )
    else:
        texto = (
            f"➕ *Adicionar aos Favoritos ({ROTULO_TIPO[tipo]})*\n\n"
            "📭 Nenhum ativo disponível para adicionar."
        )

    navegacao = []
    if pagina > 0:
        navegacao.append(
            InlineKeyboardButton(
                "⬅️", callback_data=f"{PREFIXO_LISTAR_ADICIONAR}{tipo}_{pagina - 1}"
            )
        )
    if pagina < total_paginas - 1:
        navegacao.append(
            InlineKeyboardButton(
                "➡️", callback_data=f"{PREFIXO_LISTAR_ADICIONAR}{tipo}_{pagina + 1}"
            )
        )
    if navegacao:
        markup.row(*navegacao)

    voltar_callback = "favoritos_" + ("fiis" if tipo == "fii" else "acoes")
    markup.row(InlineKeyboardButton("🔙 Voltar", callback_data=voltar_callback))
    _render(call, texto, markup)


@bot.callback_query_handler(func=lambda call: call.data in TIPO_POR_CALLBACK)
def mostrar_favoritos(call):
    """Lista os favoritos do próprio usuário (botões ⭐ dos menus)."""
    tipo = TIPO_POR_CALLBACK[call.data]
    usuario_id, erro = _resolver_usuario_autorizado(call)
    if usuario_id is None:
        _responder_callback(call, erro or TEXTO_ACESSO_NEGADO)
        return
    _mostrar_favoritos(call, tipo, usuario_id)


@bot.callback_query_handler(
    func=lambda call: call.data and call.data.startswith(PREFIXO_LISTAR_ADICIONAR)
)
def listar_para_adicionar(call):
    """Exibe os ativos disponíveis (do tipo) para adicionar aos favoritos."""
    partes = call.data.split("_")
    if len(partes) != 3 or partes[1] not in VOLTAR_MENU:
        _responder_callback(call, TEXTO_ACESSO_NEGADO)
        return
    tipo = partes[1]
    try:
        pagina = int(partes[2])
    except (TypeError, ValueError):
        pagina = 0

    usuario_id, erro = _resolver_usuario_autorizado(call)
    if usuario_id is None:
        _responder_callback(call, erro or TEXTO_ACESSO_NEGADO)
        return
    _mostrar_disponiveis(call, tipo, usuario_id, pagina)


@bot.callback_query_handler(
    func=lambda call: call.data and call.data.startswith(PREFIXO_ADICIONAR)
)
def adicionar_favorito(call):
    """Adiciona um ativo existente aos favoritos do próprio usuário."""
    partes = call.data.split("_")
    if len(partes) != 3 or partes[2] not in VOLTAR_MENU:
        _responder_callback(call, TEXTO_ACESSO_NEGADO)
        return
    ticker, tipo = partes[1].upper(), partes[2]

    usuario_id, erro = _resolver_usuario_autorizado(call)
    if usuario_id is None:
        _responder_callback(call, erro or TEXTO_ACESSO_NEGADO)
        return

    # Limite máximo por tipo (configurável; None = sem limite). Vale para o
    # usuário comum; o administrador não é limitado nos próprios favoritos.
    limite = _limite_do_tipo(tipo)
    if limite is not None and not _e_admin(call):
        try:
            repositorio = RepositorioFavoritos()
            resolvido = repositorio.resolver_ativo(ticker)
            atuais = repositorio.listar(usuario_id, tipo)
        except Exception:
            logger.warning("FAVORITOS - falha ao validar limite", exc_info=True)
            _responder_callback(call, TEXTO_ERRO_BANCO)
            return
        ja_favorito = resolvido is not None and any(
            f.ticker == resolvido[1] for f in atuais
        )
        if not ja_favorito and len(atuais) >= limite:
            _responder_callback(
                call,
                f"🚫 Limite de {limite} {ROTULO_TIPO[tipo]} atingido. "
                "Para mudar, use 🔁 Trocar (requer aprovação).",
            )
            _mostrar_favoritos(call, tipo, usuario_id)
            return

    try:
        _dto, criado = RepositorioFavoritos().adicionar(usuario_id, ticker)
    except AtivoNaoCadastradoError:
        _responder_callback(call, f"❌ {ticker} não está cadastrado no sistema.")
        _mostrar_disponiveis(call, tipo, usuario_id, 0)
        return
    except Exception:
        logger.warning("FAVORITOS - falha ao adicionar", exc_info=True)
        _responder_callback(call, TEXTO_ERRO_BANCO)
        return

    aviso = f"✅ {ticker} adicionado." if criado else f"ℹ️ {ticker} já estava nos favoritos."
    _mostrar_favoritos(call, tipo, usuario_id, aviso=aviso)


@bot.callback_query_handler(
    func=lambda call: call.data and call.data.startswith(PREFIXO_REMOVER)
)
def remover_favorito(call):
    """Remove um ativo dos favoritos do próprio usuário."""
    partes = call.data.split("_")
    if len(partes) != 3 or partes[2] not in VOLTAR_MENU:
        _responder_callback(call, TEXTO_ACESSO_NEGADO)
        return
    ticker, tipo = partes[1].upper(), partes[2]

    usuario_id, erro = _resolver_usuario_autorizado(call)
    if usuario_id is None:
        _responder_callback(call, erro or TEXTO_ACESSO_NEGADO)
        return

    # Remoção direta de favorito ativo é exclusiva do administrador. O usuário
    # comum só altera favoritos por solicitação de troca aprovada. Revalidado
    # aqui, independentemente dos botões exibidos (callback_data pode ser forjado).
    if not _e_admin(call):
        _responder_callback(
            call,
            "🔒 Para alterar um favorito, use 🔁 Trocar (requer aprovação do administrador).",
        )
        _mostrar_favoritos(call, tipo, usuario_id)
        return

    try:
        removido = RepositorioFavoritos().remover(usuario_id, ticker)
    except Exception:
        logger.warning("FAVORITOS - falha ao remover", exc_info=True)
        _responder_callback(call, TEXTO_ERRO_BANCO)
        return

    aviso = f"🗑️ {ticker} removido." if removido else f"ℹ️ {ticker} não estava nos favoritos."
    _mostrar_favoritos(call, tipo, usuario_id, aviso=aviso)
