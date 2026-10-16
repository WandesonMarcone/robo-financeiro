"""Funções auxiliares do bot do Telegram.

Este módulo deve permanecer leve (sem importar o pipeline, o banco ou serviços
externos) para que a lógica de autorização, descrição de updates e tratamento de
falhas seja testável de forma isolada.
"""

import logging

import telebot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

import config

logger = logging.getLogger("robo.telegram")

TEXTO_MENU_INICIAL = (
    "🤖 *Terminal Institucional* 🤖\n"
    "Selecione o módulo de análise abaixo:"
)

TITULO_PAINEL = "🛡️ *ROBÔ FINANCEIRO | ESTRATÉGIA FARDADA*"

NOME_PADRAO = "investidor(a)"
TEXTO_SEM_FAVORITOS = (
    "📭 Você ainda não acompanha nenhum ativo. "
    "Toque em ⭐ Gerenciar favoritos para escolher."
)
TEXTO_CATEGORIA_VAZIA = "— nenhum ativo ainda"


def escapar_markdown(texto):
    """Neutraliza caracteres com significado no Markdown legado do Telegram.

    O menu é enviado com ``parse_mode="Markdown"``. Nomes de usuário podem conter
    ``_``, ``*``, ``[`` ou `` ` ``, que quebrariam a formatação (erro 400 da API).
    Aqui esses caracteres são escapados com barra invertida, sem alterar o texto
    visível.
    """
    if texto is None:
        return ""
    return (
        str(texto)
        .replace("\\", "\\\\")
        .replace("*", "\\*")
        .replace("_", "\\_")
        .replace("[", "\\[")
        .replace("`", "\\`")
    )


def nome_de_exibicao_do_telegram(from_user):
    """Nome de exibição vindo do Telegram (``first`` + ``last``, senão username).

    Retorna ``None`` quando nenhum dado legível está disponível, para que o
    chamador aplique o fallback. Função pura: não acessa banco nem configuração.
    """
    if from_user is None:
        return None
    partes = [
        getattr(from_user, "first_name", None),
        getattr(from_user, "last_name", None),
    ]
    nome = " ".join(str(p).strip() for p in partes if p).strip()
    if nome:
        return nome
    username = getattr(from_user, "username", None)
    if username:
        return f"@{str(username).strip().lstrip('@')}"
    return None


def montar_painel_inicial(nome, favoritos_fii=None, favoritos_acao=None, incluir_admin=False):
    """Monta o texto e o teclado do painel inicial personalizado.

    Retorna ``(texto, markup)``. Função pura (sem banco/serviços) para poder ser
    testada isoladamente. Reconhece o nome do usuário, lista apenas os favoritos
    recebidos (que o chamador resolve por usuário) e oferece atalhos para os
    módulos que realmente existem no projeto.

    ``favoritos_fii``/``favoritos_acao`` aceitam tanto objetos com atributo
    ``ticker`` (``FavoritoDTO``) quanto strings de ticker.
    """
    nome_limpo = nome_de_exibicao(nome)
    itens_fii = _normalizar_favoritos(favoritos_fii)
    itens_acao = _normalizar_favoritos(favoritos_acao)

    linhas = [
        TITULO_PAINEL,
        "",
        f"Olá, {escapar_markdown(nome_limpo)}! 👋",
        "",
        "Aqui está seu painel de investimentos.",
        "",
        "📊 *SEUS ATIVOS FAVORITOS*",
        "",
        "🏢 *Fundos Imobiliários*",
        ", ".join(escapar_markdown(t) for t in itens_fii)
        if itens_fii
        else TEXTO_CATEGORIA_VAZIA,
        "",
        "📈 *Ações*",
        ", ".join(escapar_markdown(t) for t in itens_acao)
        if itens_acao
        else TEXTO_CATEGORIA_VAZIA,
    ]
    if not itens_fii and not itens_acao:
        linhas += ["", TEXTO_SEM_FAVORITOS]
    linhas += ["", "━━━━━━━━━━━━━━", "📌 *MENU PRINCIPAL*"]
    texto = "\n".join(linhas)

    markup = InlineKeyboardMarkup()
    _adicionar_favoritos(markup, itens_fii, "fii")
    _adicionar_favoritos(markup, itens_acao, "acao")

    markup.row(
        InlineKeyboardButton("📄 Novos documentos", callback_data="novos_documentos")
    )
    markup.row(
        InlineKeyboardButton("📊 Minha carteira", callback_data="minha_carteira"),
        InlineKeyboardButton("🔔 Alertas", callback_data="meus_alertas"),
    )
    markup.row(
        InlineKeyboardButton("⭐ Gerenciar favoritos", callback_data="gerenciar_favoritos")
    )
    markup.row(
        InlineKeyboardButton(
            "📈 Consultar indicadores", callback_data="consultar_indicadores"
        )
    )
    markup.row(
        InlineKeyboardButton("⚙️ Minha conta", callback_data="minha_conta"),
        InlineKeyboardButton("❓ Ajuda", callback_data="menu_ajuda"),
    )
    if incluir_admin:
        markup.row(
            InlineKeyboardButton("⚙️ Central de Controles", callback_data="adm_home")
        )
    return texto, markup


def nome_de_exibicao(nome):
    """Normaliza o nome de saudação (fallback seguro quando vazio)."""
    if nome is None:
        return NOME_PADRAO
    texto = " ".join(str(nome).split())
    return texto or NOME_PADRAO


def _normalizar_favoritos(favoritos):
    """Extrai os tickers (em maiúsculas, sem duplicatas, ordenados)."""
    if not favoritos:
        return []
    tickers = []
    for item in favoritos:
        ticker = getattr(item, "ticker", item)
        if not ticker:
            continue
        ticker = str(ticker).strip().upper()
        if ticker and ticker not in tickers:
            tickers.append(ticker)
    return sorted(tickers)


def _adicionar_favoritos(markup, tickers, tipo):
    """Adiciona, em linhas de até 3, os botões dos favoritos de um tipo."""
    linha = []
    for ticker in tickers:
        linha.append(
            InlineKeyboardButton(
                f"📊 {ticker}", callback_data=f"painel_{ticker}_{tipo}"
            )
        )
        if len(linha) == 3:
            markup.row(*linha)
            linha = []
    if linha:
        markup.row(*linha)


def construir_menu_inicial(incluir_admin=False):
    """Monta o teclado do menu principal.

    Extraído de ``bot/comandos.py`` para ser reutilizado tanto pelo comando
    ``/menu`` quanto pelo fluxo de cadastro (``bot/cadastro.py``) sem acoplar o
    cadastro aos imports pesados de ``bot.comandos``.

    Quando ``incluir_admin`` é verdadeiro, acrescenta o atalho administrativo
    "⚙️ Central de Controles". O chamador é responsável por habilitá-lo somente
    para o administrador autorizado; o callback ainda é revalidado no servidor
    (``bot.permissoes`` e ``bot.central_controles``).
    """
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("🏢 FIIs (Imobiliários)", callback_data="menu_fiis"),
        InlineKeyboardButton("📈 Ações (Empresas)", callback_data="menu_acoes"),
    )
    markup.row(InlineKeyboardButton("ℹ️ Ajuda / Sobre", callback_data="menu_ajuda"))
    if incluir_admin:
        markup.row(
            InlineKeyboardButton("⚙️ Central de Controles", callback_data="adm_home")
        )
    return markup


# Comandos disponíveis para todo usuário autorizado. Lista única (fonte de
# verdade da Ajuda) para não divergir entre o comando ``/help`` e o callback
# ``ajuda_comandos``.
COMANDOS_AJUDA_USUARIO = (
    ("/menu", "Abre o painel principal."),
    ("/start", "Inicia ou reinicia seu cadastro."),
    ("/relatorios", "Últimos documentos capturados."),
    ("/docs", "Atalho para os últimos documentos."),
    ("/help", "Mostra este guia de comandos."),
)

# Comandos exclusivos do administrador. Só aparecem para quem tem o papel
# ``admin``; continuam sendo validados pelo controle central de permissões.
COMANDOS_AJUDA_ADMIN = (
    ("/status", "Saúde do banco de dados."),
    ("/adicionar TICKER", "Adiciona um ativo ao monitoramento."),
    ("/forcar_varredura", "Varredura manual na B3/CVM."),
    ("/forcar_docs_acoes [ANO]", "Baixa PDFs de ações na CVM."),
    ("/processar_acoes_ia", "Processa PDFs de ações com a IA."),
    ("/forcar_cvm [ANO]", "Coleta balanços da CVM."),
    ("/forcar_fiis", "Coleta informes mensais de FIIs."),
    ("/alimentar_ia", "Extrai texto de PDFs antigos."),
    ("/mapear_nomes", "Cataloga os nomes de fundos da B3."),
    ("/resetar_docs", "Apaga registros de documentos (irreversível)."),
    ("/revisao", "Abre a fila de revisão manual."),
    ("/controles", "Abre a Central de Controles."),
)


def montar_guia_comandos(papel=None):
    """Monta o texto do guia de comandos, restrito ao papel do usuário.

    Usuários comuns veem apenas os comandos que realmente podem executar; a
    seção administrativa só é incluída quando ``papel`` é o de administrador.
    Função pura (sem banco/serviços) para poder ser testada isoladamente.
    """
    linhas = ["ℹ️ *Guia de Comandos*", "", "🔹 *Consulta*"]
    for comando, descricao in COMANDOS_AJUDA_USUARIO:
        linhas.append(f"`{comando}` — {descricao}")
    if papel == getattr(config, "PAPEL_ADMIN", "admin"):
        linhas += ["", "🔧 *Administração (somente admin)*"]
        for comando, descricao in COMANDOS_AJUDA_ADMIN:
            linhas.append(f"`{comando}` — {descricao}")
    linhas += [
        "",
        "Dica: use os menus dinâmicos para navegar pelos setores sem digitar comandos.",
    ]
    return "\n".join(linhas)


TEXTO_CALLBACK_DESCONHECIDO = (
    "⚠️ Este botão não é mais válido. Envie /menu para recomeçar."
)
TEXTO_ACESSO_NEGADO = (
    "⛔ Você não tem permissão para executar esta operação."
)
TEXTO_FALHA_COMANDO = (
    "❌ Não foi possível concluir o comando. Tente novamente ou envie /menu."
)
TEXTO_FALHA_CALLBACK = (
    "⚠️ Erro ao processar este botão. Envie /menu para recomeçar."
)


def chat_id_do_update(update):
    """Extrai o chat_id de um update de mensagem ou de callback (ou None)."""
    if update is None:
        return None

    message = getattr(update, "message", None)
    if message is not None:
        return message.chat.id

    callback = getattr(update, "callback_query", None)
    if callback is not None and callback.message is not None:
        return callback.message.chat.id

    return None


def chat_autorizado(update, chats_autorizados=None):
    """Retorna True se o update vier de um chat autorizado.

    Updates sem mensagem/callback (outros tipos) continuam sendo aceitos, para
    preservar o comportamento original. A lista autorizada vem de
    ``config.CHATS_AUTORIZADOS`` e não deve ser alterada aqui.
    """
    ids = config.CHATS_AUTORIZADOS if chats_autorizados is None else chats_autorizados
    chat_id = chat_id_do_update(update)
    if chat_id is None:
        return True
    return str(chat_id) in ids


def descrever_update(update):
    """Gera uma descrição curta e sem dados sensíveis, para logs verificáveis."""
    if update is None:
        return "desconhecido"

    message = getattr(update, "message", None)
    if message is not None:
        texto = getattr(message, "text", None)
        if texto:
            trecho = texto.strip().splitlines()[0][:80]
            return f"message chat_id={message.chat.id} text={trecho!r}"
        return (
            f"message chat_id={message.chat.id} "
            f"tipo={getattr(message, 'content_type', 'nao-texto')}"
        )

    callback = getattr(update, "callback_query", None)
    if callback is not None:
        chat_id = callback.message.chat.id if callback.message is not None else None
        return f"callback chat_id={chat_id} data={getattr(callback, 'data', None)!r}"

    return f"tipo={getattr(update, 'content_type', 'desconhecido')}"


def responder_callback_desconhecido(bot_api, callback_query_id, logger=logger):
    """Responde a um callback que não corresponde a nenhum fluxo conhecido."""
    try:
        bot_api.answer_callback_query(
            callback_query_id,
            text=TEXTO_CALLBACK_DESCONHECIDO,
        )
        return True
    except Exception:
        logger.debug(
            "TELEGRAM - falha ao responder callback desconhecido %s",
            callback_query_id,
            exc_info=True,
        )
        return False


class NotificadorDeFalhas(telebot.ExceptionHandler):
    """Torna visíveis as falhas dos handlers e evita respostas ausentes.

    Configurado em ``bot.loader``. O telebot captura internamente as exceções
    lançadas pelos handlers e, sem um ``exception_handler``, apenas as descarta
    (gerando falha silenciosa). Aqui registramos a falha com traceback e
    avisamos o usuário que originou a atualização.
    """

    def __init__(self):
        super().__init__()
        self.bot = None

    def handle(self, exception):
        update = getattr(self.bot, "_update_em_processamento", None) if self.bot else None
        logger.exception(
            "TELEGRAM - falha ao executar handler para %s: %s",
            descrever_update(update),
            exception,
        )
        if self.bot is not None:
            self.bot._falha_no_update = exception
        self._avisar_usuario(update)
        return True

    def _avisar_usuario(self, update):
        if self.bot is None or update is None:
            return
        try:
            message = getattr(update, "message", None)
            callback = getattr(update, "callback_query", None)
            if message is not None:
                self.bot.send_message(message.chat.id, TEXTO_FALHA_COMANDO)
            elif callback is not None:
                self.bot.answer_callback_query(callback.id, text=TEXTO_FALHA_CALLBACK)
        except Exception:
            logger.debug(
                "TELEGRAM - não foi possível avisar o usuário sobre a falha",
                exc_info=True,
            )
