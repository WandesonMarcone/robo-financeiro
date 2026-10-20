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
    "*Robô Financeiro*\n"
    "Escolha uma opção no menu para começar."
)

TITULO_PAINEL = "*Robô Financeiro*"

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
    """Monta o texto e o teclado do painel inicial.

    Retorna ``(texto, markup)``. Função pura (sem banco/serviços) para poder ser
    testada isoladamente. O administrador recebe um painel próprio, com as
    funções administrativas (Central de Controles, consulta de indicadores e
    minha carteira) e **sem** o fluxo de seleção de favoritos usado no cadastro
    dos usuários comuns. ``favoritos_fii``/``favoritos_acao`` aceitam tanto
    objetos com atributo ``ticker`` (``FavoritoDTO``) quanto strings de ticker.
    """
    nome_limpo = nome_de_exibicao(nome)
    itens_fii = _normalizar_favoritos(favoritos_fii)
    itens_acao = _normalizar_favoritos(favoritos_acao)

    if incluir_admin:
        return _montar_painel_admin(nome_limpo, itens_fii, itens_acao)

    linhas = [
        TITULO_PAINEL,
        "",
        f"Olá, {escapar_markdown(nome_limpo)}.",
        "",
        "Seu acesso está liberado. Escolha uma opção no menu para começar.",
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
        InlineKeyboardButton("📊 Minha carteira", callback_data="minha_carteira")
    )
    markup.row(
        InlineKeyboardButton("📄 Novos documentos", callback_data="novos_documentos"),
        InlineKeyboardButton("🔔 Alertas", callback_data="meus_alertas"),
    )
    markup.row(
        InlineKeyboardButton("⭐ Gerenciar favoritos", callback_data="gerenciar_favoritos")
    )
    markup.row(
        InlineKeyboardButton("👤 Minha conta", callback_data="minha_conta"),
        InlineKeyboardButton("ℹ️ Ajuda", callback_data="menu_ajuda"),
    )
    return texto, markup


def _montar_painel_admin(nome_limpo, itens_fii, itens_acao):
    """Painel exclusivo do administrador (diferente do fluxo de usuário comum)."""
    linhas = [
        TITULO_PAINEL,
        "",
        f"Olá, {escapar_markdown(nome_limpo)}.",
        "",
        "*Painel administrativo*",
        "",
        "📌 *AÇÕES ADMINISTRATIVAS*",
        "• Central de Controles",
        "• Consulta de indicadores",
        "• Minha carteira",
        "• Novos documentos",
        "",
        "📊 *RESUMO DOS SEUS ATIVOS*",
        "🏢 FIIs: "
        + (
            ", ".join(escapar_markdown(t) for t in itens_fii)
            if itens_fii
            else TEXTO_CATEGORIA_VAZIA
        ),
        "📈 Ações: "
        + (
            ", ".join(escapar_markdown(t) for t in itens_acao)
            if itens_acao
            else TEXTO_CATEGORIA_VAZIA
        ),
    ]
    texto = "\n".join(linhas)

    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton(
            "⚙️ Central de Controles", callback_data="adm_home"
        )
    )
    markup.row(
        InlineKeyboardButton(
            "📈 Consultar indicadores", callback_data="consultar_indicadores"
        )
    )
    markup.row(
        InlineKeyboardButton("📊 Minha carteira", callback_data="minha_carteira")
    )
    markup.row(
        InlineKeyboardButton(
            "📄 Novos documentos", callback_data="novos_documentos"
        )
    )
    markup.row(
        InlineKeyboardButton("👤 Minha conta", callback_data="minha_conta"),
        InlineKeyboardButton("ℹ️ Ajuda", callback_data="menu_ajuda"),
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
    if incluir_admin:
        # Navegação geral por todos os ativos: exclusiva do administrador.
        markup.row(
            InlineKeyboardButton("🏢 FIIs (Imobiliários)", callback_data="menu_fiis"),
            InlineKeyboardButton("📈 Ações (Empresas)", callback_data="menu_acoes"),
        )
    else:
        markup.row(
            InlineKeyboardButton("📊 Minha carteira", callback_data="minha_carteira"),
            InlineKeyboardButton(
                "⭐ Gerenciar favoritos", callback_data="gerenciar_favoritos"
            ),
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
    ("/start", "Abre o painel, se o acesso estiver liberado, ou continua o cadastro."),
    ("/menu", "Abre o painel principal (conta aprovada)."),
    ("/relatorios", "Últimos documentos dos seus ativos."),
    ("/docs", "Atalho para os últimos documentos."),
    ("/help", "Mostra esta ajuda."),
    ("/cancelar", "Cancela um cadastro em andamento, sem enviar pedido."),
)

# Comandos exclusivos do administrador. Só aparecem para quem tem o papel
# ``admin``; continuam sendo validados pelo controle central de permissões.
COMANDOS_AJUDA_ADMIN = (
    ("/status", "Saúde do banco de dados."),
    ("/adicionar TICKER", "Adiciona um ativo ao monitoramento."),
    ("/forcar_varredura [DIAS]", "Varredura FNET de FIIs (padrao: 60 dias)."),
    ("/forcar_docs_acoes [ANO]", "Baixa PDFs de acoes na CVM (padrao: ano civil corrente)."),
    ("/processar_acoes_ia", "Processa PDFs de ações com a IA."),
    ("/forcar_cvm [ANO]", "Coleta ITR de acoes da CVM (padrao: ano civil corrente)."),
    ("/forcar_fiis [ANO]", "Coleta informes mensais de FIIs (padrao: ano civil corrente)."),
    ("/alimentar_ia", "Extrai texto de PDFs antigos."),
    ("/mapear_nomes", "Cataloga os nomes de fundos da B3."),
    ("/resetar_docs", "Apaga registros de documentos (irreversível)."),
    ("/revisao", "Abre a fila de revisão manual."),
    ("/controles", "Abre a Central de Controles."),
)


def montar_guia_comandos(papel=None, status=None, formulario_ativo=False):
    """Monta o texto do guia de comandos, restrito ao papel e ao estado.

    Usuários comuns veem apenas os comandos que realmente podem executar; a
    seção administrativa só é incluída quando ``papel`` é o de administrador.
    Função pura (sem banco/serviços) para poder ser testada isoladamente.
    """
    linhas = ["*Ajuda*", "", TEXTO_SOBRE_O_PROJETO, ""]
    if formulario_ativo:
        linhas += [
            "Você está na etapa de cadastro.",
            "Informe o dado pedido, use os botões da conversa ou envie "
            "/cancelar para sair sem enviar o pedido.",
            "Depois do envio, um administrador analisa o pedido.",
            "",
        ]
    elif status == "pendente":
        linhas += [
            "Seu cadastro está aguardando aprovação.",
            "Você será informado quando houver uma atualização.",
            "Envie /start para ver esta situação de novo.",
            "",
        ]
    elif status == "rejeitado":
        linhas += [
            "Seu acesso foi recusado. O menu permanece bloqueado.",
            "Fale com o administrador se precisar de uma nova análise.",
            "",
        ]
    elif status == "suspenso":
        linhas += [
            "Seu acesso está suspenso. O menu permanece bloqueado.",
            "Fale com o administrador se precisar de orientação.",
            "",
        ]
    elif papel == getattr(config, "PAPEL_ADMIN", "admin"):
        linhas += [
            "Seu acesso de administrador está ativo.",
            "Use o painel ou os comandos abaixo.",
            "",
        ]
    elif papel:
        linhas += [
            "Seu acesso está liberado. Escolha uma opção no menu para começar.",
            "Envie /menu para voltar ao painel.",
            "",
        ]
    else:
        linhas += [
            "Para começar, envie /start e complete o cadastro.",
            "Um administrador analisa o pedido antes de liberar o menu.",
            "",
        ]
    linhas += ["*Comandos*"]
    for comando, descricao in COMANDOS_AJUDA_USUARIO:
        linhas.append(f"`{comando}` — {descricao}")
    if papel == getattr(config, "PAPEL_ADMIN", "admin"):
        linhas += ["", "*Administração (somente admin)*"]
        for comando, descricao in COMANDOS_AJUDA_ADMIN:
            linhas.append(f"`{comando}` — {descricao}")
    linhas += [
        "",
        "No painel, cada botão abre a função indicada no nome. "
        "Alertas personalizados por usuário ainda não estão disponíveis.",
    ]
    return "\n".join(linhas)


TEXTO_SOBRE_O_PROJETO = (
    "O Robô Financeiro acompanha FIIs e ações pelo Telegram: indicadores, "
    "documentos e os ativos que você escolher. "
    "Este projeto foi iniciado em agosto de 2026."
)

TEXTO_MENU_AJUDA = (
    "*Ajuda*\n\n"
    f"{TEXTO_SOBRE_O_PROJETO}\n\n"
    "Como usar:\n"
    "• Cadastro: envie /start, informe nome e e-mail e confirme o pedido.\n"
    "• Depois da aprovação, envie /start ou /menu para abrir o painel.\n"
    "• No painel, toque no botão da ação que deseja fazer.\n"
    "• Para cancelar um cadastro em andamento, envie /cancelar.\n\n"
    "Se um botão não funcionar, envie /menu. "
    "Se o cadastro estiver pendente, aguarde o aviso do administrador."
)


TEXTO_CALLBACK_DESCONHECIDO = (
    "Este botão não é mais válido. Envie /menu para voltar ao painel, "
    "ou /start se ainda estiver no cadastro."
)
TEXTO_ACESSO_NEGADO = (
    "Você não tem permissão para esta operação. "
    "Se ainda não concluiu o cadastro, envie /start. "
    "Se o pedido está em análise, aguarde a aprovação. "
    "Com o acesso liberado, envie /menu."
)
TEXTO_FALHA_COMANDO = (
    "Não foi possível concluir o comando. Tente novamente ou envie /menu."
)
TEXTO_FALHA_CALLBACK = (
    "Não foi possível processar este botão. Envie /menu para voltar ao painel."
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
