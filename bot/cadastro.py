"""Autocadastro de usuários e aprovação pelo administrador (Fase 2 / Etapa 2).

Fluxo conversacional:

1. Um usuário desconhecido envia ``/start``. O bot inicia um formulário e pede
   o **nome completo** e depois o **e-mail**.
2. Os dados obtidos do Telegram (Telegram User ID, username quando houver, nome
   de exibição e Chat ID) são coletados junto do formulário.
3. Antes de enviar, o usuário revisa os dados e confirma. Só então uma
   solicitação ``pendente`` é criada (sem duplicar contas/atendimentos) e o
   administrador é notificado com um cartão completo da solicitação.
4. O administrador aprova/rejeita com botões; a decisão é revalidada no servidor
   (papel do autor e estado atual da solicitação) e o solicitante é avisado.

Regras de projeto respeitadas:

* não altera o schema, não executa migrações e não cria o administrador;
* ``nome`` e ``email`` usam colunas que já existem na tabela ``usuarios``;
* usuários já autorizados por ``config`` continuam entrando direto no menu;
* usuários pendentes/rejeitados/suspensos não acessam funcionalidades restritas
  (``bot.permissoes`` exige status aprovado + ativo);
* o formulário pode ser cancelado (``/cancelar`` ou botão) e reiniciado com
  ``/start`` sem criar solicitações duplicadas;
* nenhum token, credencial ou URL de banco é registrado em log.

Limitação conhecida (documentada, não "inventada"): o estado do formulário vive
na memória do processo (``bot.sessao_cadastro``). Reinícios/múltiplos workers
podem descartar um formulário em andamento; o usuário reinicia com ``/start``.
O username do Telegram e o nome de exibição não possuem coluna própria na tabela
``usuarios``; eles são exibidos ao administrador e registrados na trilha de
auditoria (logs estruturados, ``robo.auditoria``), mas não persistidos no banco,
para não alterar o schema.
"""

import logging
import re

from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
from bot import menu_principal, permissoes, sessao_cadastro
from bot.loader import bot
from bot.sessao_cadastro import (
    ETAPA_CONFIRMACAO,
    ETAPA_EMAIL,
    ETAPA_NOME,
)
from bot.telegram_utils import (
    TEXTO_ACESSO_NEGADO,
)
from pipeline_dados.modelos_usuarios import (
    STATUS_APROVADO,
    STATUS_PENDENTE,
    STATUS_REJEITADO,
    STATUS_SUSPENSO,
)
from pipeline_dados.repositorio_favoritos import (
    AtivoNaoCadastradoError,
    RepositorioFavoritos,
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

ACAO_FORM_CONFIRMAR = "confirmar"
ACAO_FORM_CORRIGIR = "corrigir"
ACAO_FORM_CANCELAR = "cancelar"
ACAO_FORM_FII = "fii"
ACAO_FORM_ACAO = "acao"
ACAO_FORM_FII_TOGGLE = "ft"
ACAO_FORM_ACAO_TOGGLE = "at"
ACAO_FORM_FII_PAGE = "fp"
ACAO_FORM_ACAO_PAGE = "ap"
ACAO_FORM_FII_DONE = "fd"
ACAO_FORM_ACAO_DONE = "ad"

TAMANHO_PAGINA_FAVORITOS = 10
LIMITE_SEGURANCA_TICKERS = 200

TEXTO_PENDENTE = (
    "Seu cadastro está aguardando aprovação.\n\n"
    "Você será informado quando houver uma atualização. "
    "Não é necessário enviar outros comandos agora.\n\n"
    "Para ver esta situação de novo, envie /start."
)
TEXTO_REJEITADO = (
    "Seu acesso foi recusado pelo administrador.\n\n"
    "Você não pode usar o menu neste momento. "
    "Se precisar de uma nova análise, fale com o administrador."
)
TEXTO_SUSPENSO = (
    "Seu acesso está suspenso.\n\n"
    "O menu permanece bloqueado até o administrador reativar a conta. "
    "Fale com o administrador se precisar de orientação."
)
TEXTO_CADASTRO_INDISPONIVEL = (
    "Não foi possível concluir o cadastro agora. "
    "Envie /start daqui a pouco para tentar de novo."
)
TEXTO_APROVADO = (
    "Seu acesso está liberado.\n\n"
    "Envie /start ou toque em *Menu* para abrir o painel e começar."
)
TEXTO_REATIVADO = (
    "Seu acesso foi reativado.\n\n"
    "Envie /start ou toque em *Menu* para abrir o painel e começar."
)
TEXTO_ESTADO_DESATUALIZADO = (
    "ℹ️ O estado atual desta solicitação não permite esta ação. "
    "Use /controles para ver a situação atualizada."
)

TEXTO_FORM_NOME = (
    "*Robô Financeiro*\n\n"
    "Acompanhe FIIs e ações pelo Telegram: indicadores, documentos "
    "e os ativos que você escolher.\n\n"
    "Este projeto foi iniciado em agosto de 2026.\n\n"
    "Para usar o sistema, complete o cadastro. Um administrador analisa "
    "o pedido e avisa você.\n\n"
    "Próximos passos: nome, e-mail, (opcional) favoritos e confirmação.\n"
    "Ajuda: envie /help. Para sair sem enviar, envie /cancelar.\n\n"
    "Você está na etapa de cadastro. Informe seu *nome completo* "
    "(nome e sobrenome), só com letras e espaços. Envie a mensagem "
    "para avançar."
)
TEXTO_FORM_EMAIL = (
    "Você está na etapa de cadastro. Informe seu *e-mail* de contato.\n\n"
    "Usamos o e-mail para identificar o pedido. Digite no formato "
    "*nome@dominio.com* e envie a mensagem.\n\n"
    "Se errou o nome, envie /cancelar e depois /start para recomeçar."
)
TEXTO_NOME_INVALIDO = (
    "Nome inválido. Informe o *nome completo* (nome e sobrenome), "
    "usando apenas letras e espaços. Envie de novo para continuar."
)
TEXTO_EMAIL_INVALIDO = (
    "E-mail inválido. Informe um endereço no formato *nome@dominio.com* "
    "e envie de novo para continuar."
)
TEXTO_CANCELADO = (
    "Cadastro cancelado. Nenhum pedido foi enviado. "
    "Quando quiser, envie /start para recomeçar."
)
TEXTO_SEM_FAVORITOS = "nenhum selecionado"
TEXTO_CATALOGO_VAZIO = "Nenhum ativo cadastrado para este tipo no momento."
TEXTO_NADA_PARA_CANCELAR = (
    "Não há cadastro em andamento. Envie /start para iniciar."
)
TEXTO_FORM_EXPIRADO = (
    "Este formulário expirou. Envie /start para recomeçar o cadastro."
)
TEXTO_CONFIRMADO = (
    "Cadastro concluído. Seu pedido foi enviado ao administrador.\n\n"
    "Agora o cadastro está aguardando aprovação. "
    "Você será informado quando houver uma atualização."
)
TEXTO_CONFIRMACAO_TEXTO = (
    "Use os botões acima ou responda *confirmar*, *corrigir* ou *cancelar*."
)

TEXTO_APENAS_TEXTO = (
    "Durante o cadastro, envie a resposta como texto. "
    "Para recomeçar, use /start; para sair, use /cancelar."
)


_RX_NOME = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ' .-]*$")
_RX_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")

_ROTULO_SITUACAO = {
    STATUS_PENDENTE: "Pendente de aprovação",
    STATUS_APROVADO: "Aprovado",
    STATUS_REJEITADO: "Rejeitado",
    STATUS_SUSPENSO: "Suspenso",
}


# ---------------------------------------------------------------------------
# Extração de dados do Telegram
# ---------------------------------------------------------------------------

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


def _chat_id_da_mensagem(message_or_call):
    chat = getattr(message_or_call, "chat", None)
    if chat is not None:
        return getattr(chat, "id", None)
    message = getattr(message_or_call, "message", None)
    chat = getattr(message, "chat", None)
    return getattr(chat, "id", None) if chat is not None else None


def _username_do_autor(message_or_call):
    """Username do Telegram (sem ``@``) ou ``None`` se indisponível."""
    from_user = getattr(message_or_call, "from_user", None)
    username = getattr(from_user, "username", None)
    if username:
        return str(username).strip().lstrip("@") or None
    return None


def _nome_de_exibicao(message_or_call):
    from_user = getattr(message_or_call, "from_user", None)
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


# ---------------------------------------------------------------------------
# Validação / normalização
# ---------------------------------------------------------------------------

def normalizar_nome(texto):
    """Valida e normaliza o nome completo (retorna ``None`` se inválido)."""
    if not texto:
        return None
    nome = " ".join(str(texto).split())
    if not (3 <= len(nome) <= 120):
        return None
    palavras = nome.split(" ")
    if len(palavras) < 2:
        return None
    # Exige nome e sobrenome com pelo menos 2 caracteres cada (iniciais no meio
    # são aceitas), evitando "A B" como nome completo.
    if len(palavras[0]) < 2 or len(palavras[-1]) < 2:
        return None
    if not _RX_NOME.match(nome):
        return None
    return nome


def normalizar_email(texto):
    """Normaliza (minúsculas) e valida o e-mail (``None`` se inválido)."""
    if not texto:
        return None
    email = str(texto).strip().lower()
    if not (3 <= len(email) <= 254):
        return None
    if not _RX_EMAIL.match(email):
        return None
    return email


# ---------------------------------------------------------------------------
# Envio de mensagens
# ---------------------------------------------------------------------------

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


def enviar_texto(chat_id, texto, **kwargs):
    """Alias publico de :func:`_enviar_texto` para reuso por outros modulos
    administrativos (ex.: Central de Controles), sem duplicar a implementacao."""
    return _enviar_texto(chat_id, texto, **kwargs)


def _enviar_menu(chat_id, usuario_id=None, from_user=None):
    if chat_id is None:
        return
    # Substitui o menu generico pelo painel personalizado (saudacao + favoritos
    # do proprio usuario + atalhos reais). O botao da Central de Controles e
    # anexado pelo painel somente quando o solicitante e o admin autorizado.
    menu_principal.enviar_painel(chat_id, usuario_id, from_user)


def _responder_callback(call, texto=None):
    try:
        bot.answer_callback_query(call.id, text=texto)
    except Exception:
        logger.debug("CADASTRO - falha ao responder callback", exc_info=True)


def _responder_status(chat_id, dto):
    if dto is None:
        _enviar_texto(chat_id, TEXTO_CADASTRO_INDISPONIVEL)
        return
    if dto.status == STATUS_APROVADO:
        _enviar_menu(chat_id, dto.telegram_user_id)
    elif dto.status == STATUS_REJEITADO:
        _enviar_texto(chat_id, TEXTO_REJEITADO)
    elif dto.status == STATUS_SUSPENSO:
        _enviar_texto(chat_id, TEXTO_SUSPENSO)
    else:
        _enviar_texto(chat_id, TEXTO_PENDENTE)


# ---------------------------------------------------------------------------
# Auditoria
# ---------------------------------------------------------------------------

def _registrar_auditoria(
    autor_id,
    solicitacao_id,
    acao,
    resultado,
    username=None,
    nome_telegram=None,
    status_anterior=None,
):
    """Registra um evento do cadastro numa trilha de auditoria verificavel.

    A tabela ``auditoria_acesso`` existe no banco de producao, mas seu esquema
    (colunas) nao esta declarado neste repositorio. Para nao presumir colunas
    inexistentes nem tocar o Neon, os eventos sao registrados na infraestrutura
    de auditoria compatível disponivel no codigo: a trilha estruturada de logs.

    Campos opcionais que **nao** possuem coluna na tabela ``usuarios`` (username
    e nome de exibicao do Telegram) e o estado da solicitacao antes da decisao
    administrativa sao anexados ao registro, de modo que a solicitacao possa ser
    rastreada sem alterar o schema.

    Nenhum token ou credencial e registrado; apenas identificadores de Telegram
    (ja presentes nos logs de permissao do projeto), o id interno da solicitacao
    e os dados de contato informados pelo proprio solicitante.
    """
    partes = [
        "AUDITORIA_CADASTRO",
        f"autor={autor_id}",
        f"solicitacao={solicitacao_id}",
        f"acao={acao}",
        f"resultado={resultado}",
    ]
    if username:
        partes.append(f"username=@{username}")
    if nome_telegram:
        partes.append(f"nome_telegram={nome_telegram}")
    if status_anterior:
        partes.append(f"status_anterior={status_anterior}")
    logger_auditoria.info(" ".join(partes))


def registrar_auditoria(*args, **kwargs):
    """Alias publico de :func:`_registrar_auditoria`.

    Permite que outros modulos administrativos (ex.: Central de Controles)
    registrem decisoes no mesmo mecanismo de auditoria, sem reimplementa-lo.
    """
    return _registrar_auditoria(*args, **kwargs)


# ---------------------------------------------------------------------------
# Notificação do administrador
# ---------------------------------------------------------------------------

def _chat_do_administrador():
    """Chat de destino das solicitacoes: admin configurado no ambiente.

    Prioriza ``config.TELEGRAM_ADMIN_ID`` (administrador explicito) e recorre a
    ``config.TELEGRAM_CHAT_ID`` como compatibilidade com a configuracao atual.
    """
    return getattr(config, "TELEGRAM_ADMIN_ID", None) or getattr(
        config, "TELEGRAM_CHAT_ID", None
    )


def _situacao(dto):
    return _ROTULO_SITUACAO.get(dto.status, dto.status or "Desconhecida")


def _data_solicitacao(dto):
    criado_em = getattr(dto, "criado_em", None)
    try:
        return criado_em.strftime("%d/%m/%Y %H:%M")
    except (AttributeError, ValueError):
        return "Não informada"


def _texto_solicitacao(dto, nome_telegram=None, username=None):
    """Cartão da solicitação exibido ao administrador (texto simples).

    Enviado SEM ``parse_mode`` de propósito: nome/e-mail/username vêm do usuário
    e poderiam conter caracteres que quebrariam a formatação do Telegram.
    """
    linhas = [
        "🔔 Nova solicitação de acesso",
        "",
        f"📄 Solicitação #{dto.id}",
        f"👤 Nome completo: {dto.nome or 'Não informado'}",
        f"📧 E-mail: {dto.email or 'Não informado'}",
        f"🔗 Username Telegram: @{username}" if username else "🔗 Username Telegram: não informado",
        f"🆔 Telegram User ID: {dto.telegram_user_id}",
        f"💬 Chat ID: {dto.telegram_chat_id if dto.telegram_chat_id is not None else 'não informado'}",
        f"🗓️ Data da solicitação: {_data_solicitacao(dto)}",
        f"📌 Situação: {_situacao(dto)}",
    ]
    if nome_telegram and nome_telegram != dto.nome:
        linhas.append(f"ℹ️ Nome no Telegram: {nome_telegram}")
    linhas.append("")
    linhas.append("Deseja liberar o acesso a este usuário?")
    return "\n".join(linhas)


def _notificar_admin(dto, nome_telegram=None, username=None):
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
    texto = _texto_solicitacao(dto, nome_telegram=nome_telegram, username=username)
    try:
        bot.send_message(chat_admin, texto, reply_markup=markup)
    except Exception:
        logger.warning("CADASTRO - falha ao notificar o administrador", exc_info=True)


def _notificar_usuario(dto, reativado=False):
    if dto is None:
        return
    destino = dto.telegram_chat_id or dto.telegram_user_id
    if destino is None:
        return
    if dto.status == STATUS_APROVADO:
        texto = TEXTO_REATIVADO if reativado else TEXTO_APROVADO
        _enviar_texto(destino, texto, parse_mode="Markdown")
    elif dto.status == STATUS_REJEITADO:
        _enviar_texto(destino, TEXTO_REJEITADO)
    elif dto.status == STATUS_SUSPENSO:
        _enviar_texto(destino, TEXTO_SUSPENSO)


def notificar_usuario(dto, reativado=False):
    """Alias publico de :func:`_notificar_usuario` (reuso pela Central de
    Controles). A mensagem e generica: nao revela quem decidiu nem dados
    administrativos."""
    return _notificar_usuario(dto, reativado=reativado)


# ---------------------------------------------------------------------------
# Formulário conversacional
# ---------------------------------------------------------------------------

def _resumo_confirmacao(sessao, chat_id, autor):
    selecionados_fii = ", ".join(sessao.favoritos_fii) or TEXTO_SEM_FAVORITOS
    selecionados_acao = ", ".join(sessao.favoritos_acao) or TEXTO_SEM_FAVORITOS
    linhas = [
        "Confira seus dados antes de enviar.",
        "",
        "Você está na etapa de confirmação. Depois do envio, o pedido "
        "fica aguardando aprovação do administrador.",
        "",
        f"Nome completo: {sessao.nome}",
        f"E-mail: {sessao.email}",
        f"FIIs escolhidos: {selecionados_fii}",
        f"Ações escolhidas: {selecionados_acao}",
        "",
        "Os favoritos são opcionais e só são ativados após a aprovação.",
        "",
        "Toque em Confirmar e enviar para concluir, em Corrigir para "
        "refazer nome e e-mail, ou em Cancelar para sair sem enviar.",
    ]
    return "\n".join(linhas)


def _markup_confirmacao():
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton(
            "🏢 Escolher FIIs",
            callback_data=f"{permissoes.PREFIXO_CALLBACK_FORMULARIO}{ACAO_FORM_FII}",
        ),
        InlineKeyboardButton(
            "📈 Escolher Ações",
            callback_data=f"{permissoes.PREFIXO_CALLBACK_FORMULARIO}{ACAO_FORM_ACAO}",
        ),
    )
    markup.row(
        InlineKeyboardButton(
            "✅ Confirmar e enviar",
            callback_data=f"{permissoes.PREFIXO_CALLBACK_FORMULARIO}{ACAO_FORM_CONFIRMAR}",
        ),
        InlineKeyboardButton(
            "✏️ Corrigir dados",
            callback_data=f"{permissoes.PREFIXO_CALLBACK_FORMULARIO}{ACAO_FORM_CORRIGIR}",
        ),
    )
    markup.row(
        InlineKeyboardButton(
            "❌ Cancelar cadastro",
            callback_data=f"{permissoes.PREFIXO_CALLBACK_FORMULARIO}{ACAO_FORM_CANCELAR}",
        )
    )
    return markup


def _enviar_confirmacao(chat_id, sessao, autor, call=None):
    if chat_id is None:
        return
    texto = _resumo_confirmacao(sessao, chat_id, autor)
    markup = _markup_confirmacao()
    try:
        if call is not None:
            chat_id_call, msg_id = _chat_e_message(call)
            if chat_id_call is not None and msg_id is not None:
                bot.edit_message_text(
                    texto,
                    chat_id_call,
                    msg_id,
                    reply_markup=markup,
                    parse_mode="Markdown",
                )
                return
        bot.send_message(chat_id, texto, reply_markup=markup, parse_mode="Markdown")
    except Exception as erro:
        if "message is not modified" in str(erro).lower():
            return
        logger.warning("CADASTRO - falha ao enviar confirmacao", exc_info=True)


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


def _limite_favorito(tipo):
    limites = getattr(config, "FAVORITOS_LIMITES", None) or {}
    return limites.get(tipo)


def _lista_selecionada(sessao, tipo):
    return list(sessao.favoritos_fii if tipo == "fii" else sessao.favoritos_acao)


def _texto_selecao_favoritos(sessao, tipo, catalogo, pagina):
    rotulo = "FIIs" if tipo == "fii" else "Ações"
    selecionados = _lista_selecionada(sessao, tipo)
    limite = _limite_favorito(tipo)
    if not catalogo:
        linhas = [
            f"*Escolher {rotulo}*",
            "",
            TEXTO_CATALOGO_VAZIO,
            "",
            "Toque em Concluir para voltar à confirmação.",
        ]
        return "\n".join(linhas)
    inicio = pagina * TAMANHO_PAGINA_FAVORITOS
    total_paginas = max(
        1, (len(catalogo) + TAMANHO_PAGINA_FAVORITOS - 1) // TAMANHO_PAGINA_FAVORITOS
    )
    linhas = [
        f"*Escolher {rotulo}*",
        "",
        "Toque no ativo para marcar ou desmarcar. Isso é opcional. "
        "Os favoritos só entram na sua carteira depois da aprovação.",
        "",
        f"Selecionados ({len(selecionados)}"
        + (f"/{limite}" if limite is not None else "")
        + "): "
        + (", ".join(selecionados) if selecionados else TEXTO_SEM_FAVORITOS),
        "",
        f"Página {pagina + 1}/{total_paginas}. Toque em Concluir para voltar.",
    ]
    return "\n".join(linhas)


def _markup_selecao_favoritos(sessao, tipo, catalogo, pagina):
    prefixo = permissoes.PREFIXO_CALLBACK_FORMULARIO
    selecionados = set(_lista_selecionada(sessao, tipo))
    markup = InlineKeyboardMarkup(row_width=2)
    inicio = pagina * TAMANHO_PAGINA_FAVORITOS
    fatia = catalogo[inicio : inicio + TAMANHO_PAGINA_FAVORITOS]
    prefixo_toggle = (
        ACAO_FORM_FII_TOGGLE if tipo == "fii" else ACAO_FORM_ACAO_TOGGLE
    )
    for ticker in fatia:
        marca = "☑️" if ticker in selecionados else "⬜"
        markup.add(
            InlineKeyboardButton(
                f"{marca} {ticker}",
                callback_data=f"{prefixo}{prefixo_toggle}_{ticker}",
            )
        )
    total_paginas = max(
        1, (len(catalogo) + TAMANHO_PAGINA_FAVORITOS - 1) // TAMANHO_PAGINA_FAVORITOS
    )
    navegacao = []
    prefixo_pagina = ACAO_FORM_FII_PAGE if tipo == "fii" else ACAO_FORM_ACAO_PAGE
    if pagina > 0:
        navegacao.append(
            InlineKeyboardButton(
                "⬅️", callback_data=f"{prefixo}{prefixo_pagina}_{pagina - 1}"
            )
        )
    if pagina < total_paginas - 1:
        navegacao.append(
            InlineKeyboardButton(
                "➡️", callback_data=f"{prefixo}{prefixo_pagina}_{pagina + 1}"
            )
        )
    if navegacao:
        markup.row(*navegacao)
    acao_concluir = ACAO_FORM_FII_DONE if tipo == "fii" else ACAO_FORM_ACAO_DONE
    markup.row(
            InlineKeyboardButton(
                "✅ Concluir", callback_data=f"{prefixo}{acao_concluir}"
            )
    )
    return markup


def _render_selecao_favoritos(chat_id, sessao, tipo, pagina, call=None):
    try:
        catalogo = RepositorioFavoritos().listar_catalogo(tipo)
    except Exception:
        logger.warning("CADASTRO - falha ao listar catálogo de favoritos", exc_info=True)
        _enviar_texto(chat_id, TEXTO_CADASTRO_INDISPONIVEL)
        return
    total_paginas = max(
        1, (len(catalogo) + TAMANHO_PAGINA_FAVORITOS - 1) // TAMANHO_PAGINA_FAVORITOS
    )
    pagina = max(0, min(pagina, total_paginas - 1))
    atributo = "pagina_fii" if tipo == "fii" else "pagina_acao"
    sessao = sessao_cadastro.atualizar(sessao.usuario_id, **{atributo: pagina})
    if sessao is None:
        _enviar_texto(chat_id, TEXTO_FORM_EXPIRADO)
        return
    texto = _texto_selecao_favoritos(sessao, tipo, catalogo, pagina)
    markup = _markup_selecao_favoritos(sessao, tipo, catalogo, pagina)
    try:
        if call is not None:
            chat_id_call, msg_id = _chat_e_message(call)
            if chat_id_call is not None and msg_id is not None:
                bot.edit_message_text(
                    texto,
                    chat_id_call,
                    msg_id,
                    reply_markup=markup,
                    parse_mode="Markdown",
                )
                return
        bot.send_message(chat_id, texto, reply_markup=markup, parse_mode="Markdown")
    except Exception:
        logger.warning("CADASTRO - falha ao exibir catálogo", exc_info=True)


def _alternar_favorito(sessao, tipo, ticker):
    """Marca/desmarca um ticker do catálogo, respeitando o limite configurado."""
    try:
        catalogo = set(RepositorioFavoritos().listar_catalogo(tipo))
    except Exception:
        logger.warning("CADASTRO - falha ao validar catálogo", exc_info=True)
        return sessao, TEXTO_CADASTRO_INDISPONIVEL
    chave = str(ticker or "").strip().upper()
    if chave not in catalogo:
        return sessao, "⚠️ Ativo inválido para este tipo."
    atributo = "favoritos_fii" if tipo == "fii" else "favoritos_acao"
    lista = _lista_selecionada(sessao, tipo)
    if chave in lista:
        lista.remove(chave)
        aviso = f"⬜ {chave} removido."
    else:
        limite = _limite_favorito(tipo)
        if limite is not None and len(lista) >= limite:
            return sessao, (
                f"🚫 Limite de {limite} ativo(s) deste tipo já foi atingido."
            )
        if len(lista) >= LIMITE_SEGURANCA_TICKERS:
            return sessao, "⚠️ Seleção muito grande. Finalize e tente novamente."
        lista.append(chave)
        aviso = f"☑️ {chave} selecionado."
    atualizada = sessao_cadastro.atualizar(sessao.usuario_id, **{atributo: lista})
    return atualizada or sessao, aviso


def _processar_acao_favoritos(call, usuario_id, chat_id, sessao, acao):
    """Trata as ações ``formcad_fii/acao/ft_/at_/fp_/ap_/fd/ad``.

    Retorna ``True`` quando a ação pertence à seleção de favoritos.
    """
    if acao in (ACAO_FORM_FII, ACAO_FORM_ACAO):
        tipo = "fii" if acao == ACAO_FORM_FII else "acao"
        pagina = sessao.pagina_fii if tipo == "fii" else sessao.pagina_acao
        _responder_callback(call)
        _render_selecao_favoritos(chat_id, sessao, tipo, pagina, call=call)
        return True

    for prefixo, tipo in (
        (ACAO_FORM_FII_TOGGLE + "_", "fii"),
        (ACAO_FORM_ACAO_TOGGLE + "_", "acao"),
    ):
        if acao.startswith(prefixo):
            ticker = acao[len(prefixo) :]
            sessao, aviso = _alternar_favorito(sessao, tipo, ticker)
            pagina = (
                sessao.pagina_fii if tipo == "fii" else sessao.pagina_acao
            )
            _responder_callback(call, aviso)
            _render_selecao_favoritos(chat_id, sessao, tipo, pagina, call=call)
            return True

    for prefixo, tipo in (
        (ACAO_FORM_FII_PAGE + "_", "fii"),
        (ACAO_FORM_ACAO_PAGE + "_", "acao"),
    ):
        if acao.startswith(prefixo):
            try:
                pagina = int(acao[len(prefixo) :])
            except (TypeError, ValueError):
                pagina = 0
            _responder_callback(call)
            _render_selecao_favoritos(chat_id, sessao, tipo, pagina, call=call)
            return True

    if acao in (ACAO_FORM_FII_DONE, ACAO_FORM_ACAO_DONE):
        sessao = sessao_cadastro.atualizar(usuario_id, etapa=ETAPA_CONFIRMACAO)
        if sessao is None:
            _responder_callback(call, TEXTO_FORM_EXPIRADO)
            return True
        _responder_callback(call)
        _enviar_confirmacao(chat_id, sessao, call, call=call)
        return True

    return False


def _e_texto_de_formulario(message):
    """Predicado do handler de texto: sessão ativa e mensagem não-comando.

    O administrador nunca participa do formulário de cadastro/favoritos: se
    houver uma sessão antiga em memória, ela é descartada e o painel
    administrativo assume o atendimento.
    """
    usuario_id = _id_do_autor(message)
    if not sessao_cadastro.tem_sessao_ativa(usuario_id):
        return False
    if permissoes.obter_papel(usuario_id) is not None:
        sessao_cadastro.cancelar(usuario_id)
        return False
    texto = getattr(message, "text", None)
    if not texto:
        return False
    return not texto.strip().startswith("/")


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
        _enviar_menu(chat_id, usuario_id, getattr(message, "from_user", None))
        return

    try:
        repositorio = RepositorioUsuarios()
        dto = repositorio.obter_por_telegram_id(usuario_id)
    except Exception:
        logger.warning("CADASTRO - falha ao consultar cadastro", exc_info=True)
        _enviar_texto(chat_id, TEXTO_CADASTRO_INDISPONIVEL)
        return

    if dto is not None:
        # Já existe solicitação/conta: nunca duplica; apenas informa o estado.
        try:
            dto = repositorio.atualizar_chat_id(dto.id, chat_id) or dto
        except Exception:
            logger.debug("CADASTRO - falha ao atualizar chat_id", exc_info=True)
        _responder_status(chat_id, dto)
        return

    sessao_cadastro.iniciar(usuario_id, chat_id)
    _enviar_texto(chat_id, TEXTO_FORM_NOME, parse_mode="Markdown")


@bot.message_handler(commands=[permissoes.COMANDO_CANCELAR])
def cancelar_cadastro(message):
    """Cancela o formulário em andamento (sem criar solicitação)."""
    usuario_id = _id_do_autor(message)
    chat_id = _chat_id_da_mensagem(message)
    if sessao_cadastro.cancelar(usuario_id):
        _enviar_texto(chat_id, TEXTO_CANCELADO)
    else:
        _enviar_texto(chat_id, TEXTO_NADA_PARA_CANCELAR)


@bot.message_handler(func=_e_texto_de_formulario)
def processar_texto_formulario(message):
    """Processa cada etapa do formulário (nome → e-mail → confirmação)."""
    usuario_id = _id_do_autor(message)
    chat_id = _chat_id_da_mensagem(message)
    sessao = sessao_cadastro.obter(usuario_id)
    if sessao is None:
        return

    texto = (getattr(message, "text", None) or "").strip()

    if sessao.etapa == ETAPA_NOME:
        nome = normalizar_nome(texto)
        if nome is None:
            _enviar_texto(chat_id, TEXTO_NOME_INVALIDO, parse_mode="Markdown")
            return
        sessao = sessao_cadastro.atualizar(usuario_id, nome=nome, etapa=ETAPA_EMAIL)
        _enviar_texto(chat_id, TEXTO_FORM_EMAIL, parse_mode="Markdown")
        return

    if sessao.etapa == ETAPA_EMAIL:
        email = normalizar_email(texto)
        if email is None:
            _enviar_texto(chat_id, TEXTO_EMAIL_INVALIDO, parse_mode="Markdown")
            return
        sessao = sessao_cadastro.atualizar(
            usuario_id, email=email, etapa=ETAPA_CONFIRMACAO
        )
        _enviar_confirmacao(chat_id, sessao, message)
        return

    if sessao.etapa == ETAPA_CONFIRMACAO:
        chave = texto.strip().lower()
        if chave in ("confirmar", "confirmo", "sim", "ok", "enviar"):
            _finalizar_formulario(usuario_id, chat_id, message)
        elif chave in ("cancelar", "nao", "não"):
            sessao_cadastro.cancelar(usuario_id)
            _enviar_texto(chat_id, TEXTO_CANCELADO)
        elif chave in ("corrigir", "editar"):
            sessao_cadastro.atualizar(
                usuario_id, nome=None, email=None, etapa=ETAPA_NOME
            )
            _enviar_texto(chat_id, TEXTO_FORM_NOME, parse_mode="Markdown")
        else:
            _enviar_texto(
                chat_id,
                TEXTO_CONFIRMACAO_TEXTO,
                parse_mode="Markdown",
            )
        return


def _finalizar_formulario(usuario_id, chat_id, autor):
    """Cria a solicitação após a confirmação do usuário (com revalidação)."""
    sessao = sessao_cadastro.obter(usuario_id)
    if sessao is None:
        _enviar_texto(chat_id, TEXTO_FORM_EXPIRADO)
        return

    # Revalidação (defesa em profundidade): não confia no estado da UI.
    nome = normalizar_nome(sessao.nome)
    email = normalizar_email(sessao.email)
    if nome is None or email is None:
        sessao_cadastro.atualizar(usuario_id, etapa=ETAPA_NOME)
        _enviar_texto(chat_id, TEXTO_FORM_NOME, parse_mode="Markdown")
        return

    try:
        repositorio = RepositorioUsuarios()
        dto, criado = repositorio.criar_solicitacao(
            usuario_id,
            chat_id,
            nome=nome,
            email=email,
            favoritos_pendentes=sessao.favoritos_selecionados(),
        )
        if dto is not None and not criado:
            dto = repositorio.atualizar_chat_id(dto.id, chat_id) or dto
    except Exception:
        logger.warning("CADASTRO - falha ao registrar solicitacao", exc_info=True)
        _enviar_texto(chat_id, TEXTO_CADASTRO_INDISPONIVEL)
        return

    if dto is None:
        _enviar_texto(chat_id, TEXTO_CADASTRO_INDISPONIVEL)
        return

    sessao_cadastro.limpar(usuario_id)

    username = _username_do_autor(autor)
    nome_telegram = _nome_de_exibicao(autor)

    if criado:
        _registrar_auditoria(
            usuario_id,
            dto.id,
            "solicitacao",
            "criada",
            username=username,
            nome_telegram=nome_telegram,
        )
        _notificar_admin(
            dto,
            nome_telegram=nome_telegram,
            username=username,
        )
        _enviar_texto(chat_id, TEXTO_CONFIRMADO)
    else:
        # Já existia (corrida ou repetição): não notifica de novo.
        _registrar_auditoria(
            usuario_id,
            dto.id,
            "solicitacao",
            "ja_existia",
            username=username,
            nome_telegram=nome_telegram,
        )
        _responder_status(chat_id, dto)


@bot.callback_query_handler(
    func=lambda call: bool(call.data)
    and call.data.startswith(permissoes.PREFIXO_CALLBACK_FORMULARIO)
)
def processar_confirmacao_formulario(call):
    """Confirma/corrige/cancela o formulário, sempre revalidando a sessão."""
    usuario_id = _id_do_autor(call)
    chat_id = _chat_id_da_mensagem(call)
    # Defesa explícita: contas já autorizadas (em especial o administrador) não
    # passam pelo fluxo de seleção de favoritos do cadastro de usuários comuns.
    if permissoes.obter_papel(usuario_id) is not None:
        sessao_cadastro.cancelar(usuario_id)
        _responder_callback(call, "Painel administrativo")
        _enviar_menu(chat_id, usuario_id, getattr(call, "from_user", None))
        return
    sessao = sessao_cadastro.obter(usuario_id)
    if sessao is None:
        _responder_callback(call, TEXTO_FORM_EXPIRADO)
        return

    acao = (call.data or "").split("_", 1)[1] if "_" in (call.data or "") else ""

    if _processar_acao_favoritos(call, usuario_id, chat_id, sessao, acao):
        return

    if acao == ACAO_FORM_CANCELAR:
        sessao_cadastro.cancelar(usuario_id)
        _responder_callback(call, "Cadastro cancelado.")
        _enviar_texto(chat_id, TEXTO_CANCELADO)
        return

    if acao == ACAO_FORM_CORRIGIR:
        sessao_cadastro.atualizar(
            usuario_id, nome=None, email=None, etapa=ETAPA_NOME
        )
        _responder_callback(call, "Vamos corrigir os dados.")
        _enviar_texto(chat_id, TEXTO_FORM_NOME, parse_mode="Markdown")
        return

    if acao == ACAO_FORM_CONFIRMAR:
        _responder_callback(call, "Enviando solicitação...")
        _finalizar_formulario(usuario_id, chat_id, call)
        return

    _responder_callback(call, TEXTO_ACESSO_NEGADO)


def aplicar_favoritos_pendentes(usuario_id):
    """Aplica os favoritos escolhidos no cadastro APÓS a aprovação.

    Reutiliza o repositório de favoritos existente (não cria outro). Tickers
    que não existem mais no catálogo são ignorados e registrados em log. O
    limite configurado é revalidado no momento da aplicação. Retorna a
    quantidade efetivamente adicionada. Em falha de banco, a seleção pendente é
    preservada para nova tentativa.
    """
    repositorio_usuarios = RepositorioUsuarios()
    try:
        pendentes = repositorio_usuarios.obter_favoritos_pendentes(usuario_id)
    except Exception:
        logger.warning(
            "CADASTRO - falha ao ler favoritos pendentes; seleção preservada",
            exc_info=True,
        )
        return 0
    if not (pendentes.get("fii") or pendentes.get("acao")):
        try:
            repositorio_usuarios.limpar_favoritos_pendentes(usuario_id)
        except Exception:
            logger.debug(
                "CADASTRO - falha ao limpar seleção vazia", exc_info=True
            )
        return 0
    repositorio_favoritos = RepositorioFavoritos()
    adicionados = 0
    try:
        for tipo, tickers in pendentes.items():
            if not tickers:
                continue
            limite = _limite_favorito(tipo)
            atuais = repositorio_favoritos.listar(usuario_id, tipo)
            existentes = {f.ticker for f in atuais}
            disponiveis = None if limite is None else max(0, limite - len(atuais))
            for ticker in tickers:
                if ticker in existentes:
                    continue
                if disponiveis is not None and disponiveis <= 0:
                    logger.warning(
                        "CADASTRO - limite de favoritos %s atingido ao aplicar "
                        "seleção pendente do usuário %s",
                        tipo,
                        usuario_id,
                    )
                    break
                try:
                    _dto, criado = repositorio_favoritos.adicionar(usuario_id, ticker)
                except AtivoNaoCadastradoError:
                    logger.warning(
                        "CADASTRO - ticker %s nao existe mais no catalogo; "
                        "ignorado ao aplicar favoritos",
                        ticker,
                    )
                    continue
                # Outras falhas (banco indisponivel) sobem para o except externo:
                # a selecao pendente permanece para nova tentativa.
                if criado:
                    adicionados += 1
                    existentes.add(ticker)
                    if disponiveis is not None:
                        disponiveis -= 1
        repositorio_usuarios.limpar_favoritos_pendentes(usuario_id)
    except Exception:
        logger.warning(
            "CADASTRO - falha ao aplicar favoritos pendentes; seleção preservada",
            exc_info=True,
        )
        return adicionados
    _registrar_auditoria(
        usuario_id, usuario_id, "favoritos_cadastro", f"aplicados={adicionados}"
    )
    return adicionados


def descartar_favoritos_pendentes(usuario_id):
    """Descarta a seleção pendente (rejeição/limpeza), sem tocar nos favoritos."""
    try:
        return RepositorioUsuarios().limpar_favoritos_pendentes(usuario_id)
    except Exception:
        logger.warning("CADASTRO - falha ao descartar favoritos pendentes", exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Decisão do administrador
# ---------------------------------------------------------------------------

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

    status_anterior = None
    try:
        repositorio = RepositorioUsuarios()
        # Revalidacao do estado atual da solicitacao (defesa em profundidade):
        # le o estado antes de aplicar a decisao para registrar a transicao e
        # confirmar que a solicitacao ainda existe, sem confiar na UI.
        anterior = repositorio.obter_por_id(usuario_id)
        if anterior is not None:
            status_anterior = anterior.status
        # O cartao da solicitacao so decide solicitacoes PENDENTES. A origem e
        # conferida na gravacao (mesma sessao): um botao antigo nao reativa um
        # usuario suspenso, nem rejeita/aprova quem mudou de estado depois (por
        # exemplo, pela Central de Controles). Repeticoes no mesmo alvo seguem
        # idempotentes ("ja_constava").
        if acao == ACAO_APROVAR:
            dto, mudou = repositorio.aprovar(
                usuario_id, origens_permitidas={STATUS_PENDENTE}
            )
            alvo = STATUS_APROVADO
            rotulo = "aprovado"
            texto_resultado = "✅ Solicitação APROVADA."
        else:
            dto, mudou = repositorio.rejeitar(
                usuario_id, origens_permitidas={STATUS_PENDENTE}
            )
            alvo = STATUS_REJEITADO
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

    if not mudou and dto.status != alvo:
        # Transicao bloqueada: o estado atual nao e "pendente" nem o alvo.
        _registrar_auditoria(
            autor_id,
            usuario_id,
            acao,
            "estado_invalido",
            status_anterior=dto.status,
        )
        try:
            bot.answer_callback_query(call.id, text=TEXTO_ESTADO_DESATUALIZADO)
        except Exception:
            logger.debug("CADASTRO - falha ao responder estado invalido", exc_info=True)
        return

    _registrar_auditoria(
        autor_id,
        usuario_id,
        acao,
        "aplicada" if mudou else "ja_constava",
        status_anterior=status_anterior,
    )

    # Aplica/descarta a seleção feita no cadastro somente agora, depois da
    # decisão administrativa. Cliques repetidos são idempotentes.
    if dto.status == STATUS_APROVADO:
        aplicar_favoritos_pendentes(usuario_id)
    elif dto.status == STATUS_REJEITADO:
        descartar_favoritos_pendentes(usuario_id)

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


def _e_texto_livre_do_chat(message):
    """Predicado do handler de entrada genérica (texto fora do formulário).

    Uma mensagem de texto que não é comando e não pertence a um formulário em
    andamento é tratada como pedido de entrada: o painel (admin/usuário) ou o
    início do autocadastro (visitante). Mensagens com sessão ativa já foram
    consumidas pelo handler do formulário, registrado antes deste.
    """
    texto = getattr(message, "text", None)
    if not texto or not str(texto).strip():
        return False
    if str(texto).strip().startswith("/"):
        return False
    chat = getattr(message, "chat", None)
    if getattr(chat, "type", None) != "private":
        return False
    usuario_id = _id_do_autor(message)
    if usuario_id is None:
        return False
    return not sessao_cadastro.tem_sessao_ativa(usuario_id)


@bot.message_handler(func=_e_texto_livre_do_chat)
def processar_texto_livre(message):
    """Responde a mensagens de texto diferentes de ``/start``.

    Reaproveita o fluxo de ``/start``: o papel é resolvido no servidor
    (``bot.permissoes``) e o mesmo gate de permissões já foi aplicado pelo
    loader antes do despacho. Assim, administrador e usuário aprovado recebem o
    painel, contas pendentes/rejeitadas/suspensas recebem o estado atual e um
    visitante inicia o autocadastro — sem duplicar regras neste módulo.
    """
    iniciar_cadastro(message)


def _tipos_de_midia():
    """Tipos de conteúdo não textuais aceitos pela entrada genérica."""
    try:
        from telebot.util import content_type_media

        return list(content_type_media)
    except Exception:
        logger.debug("CADASTRO - falha ao carregar tipos de midia", exc_info=True)
        return ["photo", "document", "sticker", "audio", "voice", "video"]


def _e_midia_livre_do_chat(message):
    """Predicado da entrada genérica para mídia.

    Vale apenas em conversa privada: durante o formulário a mídia não serve de
    resposta (nome/e-mail são texto) e recebe um aviso, sem reiniciar o
    cadastro; fora do formulário é tratada como pedido de entrada, exatamente
    como o texto livre: painel para quem tem acesso, estado atual para contas
    cadastradas e início do autocadastro para visitantes.
    """
    chat = getattr(message, "chat", None)
    if getattr(chat, "type", None) != "private":
        return False
    if _id_do_autor(message) is None:
        return False
    return not getattr(message, "text", None)


@bot.message_handler(
    func=_e_midia_livre_do_chat, content_types=_tipos_de_midia()
)
def processar_midia_livre(message):
    """Responde a mídia: aviso no formulário, entrada genérica fora dele."""
    usuario_id = _id_do_autor(message)
    if sessao_cadastro.tem_sessao_ativa(usuario_id):
        if permissoes.obter_papel(usuario_id) is not None:
            sessao_cadastro.cancelar(usuario_id)
            iniciar_cadastro(message)
            return
        _enviar_texto(_chat_id_da_mensagem(message), TEXTO_APENAS_TEXTO)
        return
    iniciar_cadastro(message)
