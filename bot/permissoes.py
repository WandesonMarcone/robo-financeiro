"""Controle centralizado de usuários e permissões do Robô Financeiro.

Este módulo é a única fonte de verdade para responder, a partir de um update do
Telegram:

* quem é o usuário (pelo Telegram ID);
* qual é o seu papel (``admin`` ou ``user``);
* se ele está autorizado;
* se ele pode executar a operação solicitada (comando ou callback).

Ele deve permanecer leve (importa apenas ``config``) para poder ser testado de
forma isolada e para ser reutilizado pelo ``bot.loader`` antes do despacho dos
handlers. Nenhum token ou credencial é lido ou registrado aqui.
"""

import logging

import config

logger = logging.getLogger("robo.permissoes")

NIVEL_USUARIO = 1
NIVEL_ADMIN = 2

PAPEL_ADMIN = getattr(config, "PAPEL_ADMIN", "admin")
PAPEL_USUARIO = getattr(config, "PAPEL_USUARIO", "user")

# Comandos exclusivos do administrador (manutenção, configuração ou destrutivos).
COMANDOS_ADMIN = frozenset(
    {
        "status",
        "adicionar",
        "forcar_varredura",
        "forcar_docs_acoes",
        "processar_acoes_ia",
        "forcar_cvm",
        "forcar_fiis",
        "alimentar_ia",
        "mapear_nomes",
        "resetar_docs",
        "revisao",
    }
)

# Comandos de consulta/financeiros liberados para usuários comuns.
COMANDOS_USUARIO = frozenset(
    {"menu", "start", "relatorios", "docs", "help"}
)

# Callbacks exclusivos do administrador (revisão, diagnóstico e reset).
CALLBACKS_ADMIN_EXATOS = frozenset(
    {
        "ver_raiox_docs",
        "confirmar_reset",
        "cancelar_reset",
        "iniciar_revisao_pendencias",
    }
)
CALLBACKS_ADMIN_PREFIXOS = ("rev_",)

# Callbacks de navegação, filtros e consultas liberados para usuários comuns.
CALLBACKS_USUARIO_EXATOS = frozenset(
    {
        "voltar_menu",
        "menu_ajuda",
        "menu_fiis",
        "menu_acoes",
        "favoritos_fiis",
        "favoritos_acoes",
        "oportunidades_fiis",
        "oportunidades_acoes",
        "ajuda_roadmap",
        "ajuda_comandos",
    }
)
CALLBACKS_USUARIO_PREFIXOS = (
    "tipo_fii_",
    "setor_fii_",
    "setor_acao_",
    "ia_",
    "ajuda_cvm_",
    "macro_fii_",
    "subsetor_fii_",
    "macro_ac_",
    "sub_ac_",
    "painel_",
    "dados_",
    "ano_",
    "mes_",
    "docs_",
    "dnav_",
    "dl_",
)


def normalizar_id(valor):
    """Converte um identificador para string comparável (ou None se vazio)."""
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def usuarios_autorizados():
    """Retorna o mapa Telegram ID -> papel definido em ``config``."""
    return getattr(config, "USUARIOS_AUTORIZADOS", {}) or {}


def obter_papel(usuario_id):
    """Retorna o papel do usuário ou ``None`` se ele não estiver autorizado."""
    chave = normalizar_id(usuario_id)
    if chave is None:
        return None
    return usuarios_autorizados().get(chave)


def esta_autorizado(usuario_id):
    """Retorna True se o usuário constar na lista de autorizados."""
    return obter_papel(usuario_id) is not None


def pode_executar(usuario_id, nivel_minimo):
    """Retorna True se o papel do usuário comporta o nível mínimo exigido."""
    papel = obter_papel(usuario_id)
    if papel is None:
        return False
    if papel == PAPEL_ADMIN:
        return True
    return nivel_minimo <= NIVEL_USUARIO


def usuario_id_do_update(update):
    """Extrai o Telegram ID do autor do update (mensagem ou callback)."""
    if update is None:
        return None

    message = getattr(update, "message", None)
    if message is not None:
        from_user = getattr(message, "from_user", None)
        if from_user is not None:
            return getattr(from_user, "id", None)
        chat = getattr(message, "chat", None)
        return getattr(chat, "id", None)

    callback = getattr(update, "callback_query", None)
    if callback is not None:
        from_user = getattr(callback, "from_user", None)
        if from_user is not None:
            return getattr(from_user, "id", None)
        chat = getattr(getattr(callback, "message", None), "chat", None)
        return getattr(chat, "id", None)

    return None


def operacao_de_comando(texto):
    """Classifica um comando e retorna ``(nome, nivel)`` ou ``None``.

    Comandos não reconhecidos assumem o nível administrativo (falha segura):
    um usuário limitado não recebe acesso a uma operação cuja permissão não pôde
    ser determinada com segurança.
    """
    if not texto:
        return None

    texto = str(texto).strip()
    if not texto.startswith("/"):
        return None

    corpo = texto[1:].split()
    if not corpo:
        return None

    comando = corpo[0].split("@", 1)[0].lower()
    if not comando:
        return None

    if comando in COMANDOS_ADMIN:
        return (f"comando:/{comando}", NIVEL_ADMIN)
    if comando in COMANDOS_USUARIO:
        return (f"comando:/{comando}", NIVEL_USUARIO)
    return (f"comando:/{comando}", NIVEL_ADMIN)


def operacao_de_callback(dados):
    """Classifica um callback e retorna ``(nome, nivel)``.

    Callbacks desconhecidos assumem o nível administrativo (falha segura).
    """
    dados = dados or ""

    if dados in CALLBACKS_ADMIN_EXATOS or dados.startswith(CALLBACKS_ADMIN_PREFIXOS):
        return (f"callback:{dados}", NIVEL_ADMIN)
    if dados in CALLBACKS_USUARIO_EXATOS or dados.startswith(
        CALLBACKS_USUARIO_PREFIXOS
    ):
        return (f"callback:{dados}", NIVEL_USUARIO)
    return (f"callback:{dados}", NIVEL_ADMIN)


def operacao_do_update(update):
    """Retorna a operação ``(nome, nivel)`` do update ou ``None`` se não houver."""
    message = getattr(update, "message", None)
    if message is not None:
        return operacao_de_comando(getattr(message, "text", None))

    callback = getattr(update, "callback_query", None)
    if callback is not None:
        return operacao_de_callback(getattr(callback, "data", None))

    return None


def verificar_update(update):
    """Decide se o update pode ser despachado para os handlers.

    Retorna uma tupla ``(permitido, operacao)``. Updates sem operação
    reconhecível (ex.: mensagens comuns) são liberados; operações protegidas
    exigem identificação válida e papel compatível. Em qualquer falha inesperada
    a decisão é negar, sem interromper o bot.
    """
    try:
        operacao = operacao_do_update(update)
        if operacao is None:
            return True, None

        nome, nivel_minimo = operacao
        usuario_id = usuario_id_do_update(update)
        if usuario_id is None:
            return False, nome
        if not esta_autorizado(usuario_id):
            return False, nome
        return pode_executar(usuario_id, nivel_minimo), nome
    except Exception:
        logger.exception("Falha ao verificar permissao do update")
        return False, None
