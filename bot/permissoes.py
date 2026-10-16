"""Controle centralizado de usuários e permissões do Robô Financeiro.

Este módulo é a única fonte de verdade para responder, a partir de um update do
Telegram:

* quem é o usuário (pelo Telegram ID);
* qual é o seu papel (``admin`` ou ``user``);
* se ele está autorizado;
* se ele pode executar a operação solicitada (comando ou callback).

Ele deve permanecer leve (importa ``config`` no topo e o repositório de usuários
de forma preguiçosa, apenas para reconhecer contas aprovadas no autocadastro) para
poder ser testado de forma isolada e para ser reutilizado pelo ``bot.loader``
antes do despacho dos handlers. Nenhum token ou credencial é lido ou registrado
aqui; qualquer falha de banco resulta em negação (falha segura), nunca em
concessão de acesso.
"""

import logging

import config

logger = logging.getLogger("robo.permissoes")

NIVEL_USUARIO = 1
NIVEL_ADMIN = 2

PAPEL_ADMIN = getattr(config, "PAPEL_ADMIN", "admin")
PAPEL_USUARIO = getattr(config, "PAPEL_USUARIO", "user")

# Ponto de entrada publico do autocadastro. E o unico comando que um usuario
# ainda nao cadastrado pode executar; todo o restante exige aprovacao.
COMANDO_CADASTRO = "start"

# Comando de cancelamento do formulario de autocadastro. So tem efeito enquanto
# existe um formulario em andamento (ver ``tem_fluxo_cadastro_ativo``).
COMANDO_CANCELAR = "cancelar"

# Prefixo dos callbacks do formulario conversacional (confirmar/corrigir/
# cancelar). Sao operacoes de nivel de usuario e exigem formulario ativo.
PREFIXO_CALLBACK_FORMULARIO = "formcad_"

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
        "controles",
    }
)

# Comandos de consulta/financeiros liberados para usuários comuns. O comando
# ``cancelar`` é do formulário de autocadastro e, para um usuário ainda não
# aprovado, só é liberado enquanto houver formulário ativo (ver ``verificar_update``).
COMANDOS_USUARIO = frozenset(
    {"menu", "start", "relatorios", "docs", "help", "cancelar"}
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
CALLBACKS_ADMIN_PREFIXOS = ("rev_", "cad_", "adm_")

# Callbacks de navegação, filtros e consultas liberados para usuários comuns.
CALLBACKS_USUARIO_EXATOS = frozenset(
    {
        "voltar_menu",
        "voltar_painel",
        "menu_ajuda",
        "menu_fiis",
        "menu_acoes",
        "favoritos_fiis",
        "favoritos_acoes",
        "oportunidades_fiis",
        "oportunidades_acoes",
        "ajuda_roadmap",
        "ajuda_comandos",
        # Atalhos do painel inicial personalizado. As telas que devolvem dados
        # (carteira, conta, documentos) revalidam a conta aprovada no handler.
        "novos_documentos",
        "minha_carteira",
        "meus_alertas",
        "gerenciar_favoritos",
        "consultar_indicadores",
        "minha_conta",
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
    # Favoritos individuais por usuário (Etapa 3). São operações de nível de
    # usuário; o handler ainda revalida que a conta está aprovada no banco.
    "favadd_",
    "favnew_",
    "favrem_",
    # Callbacks do formulário conversacional de autocadastro. Ficam no nível de
    # usuário; o acesso de um solicitante ainda não aprovado é liberado em
    # ``verificar_update`` somente enquanto há formulário ativo.
    PREFIXO_CALLBACK_FORMULARIO,
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


def _papel_do_banco(usuario_id):
    """Consulta o papel de um usuário aprovado no banco (falha segura).

    A lista estática de ``config`` continua sendo a fonte de verdade primária
    (o administrador e o usuário limitado atuais não dependem do banco). Este
    fallback existe para que usuários aprovados via autocadastro também tenham
    seu papel reconhecido. Qualquer erro (banco não configurado, indisponível)
    resulta em ``None``: nunca se "adivinha" um papel.
    """
    chave = normalizar_id(usuario_id)
    if chave is None:
        return None
    try:
        from pipeline_dados.repositorio_usuarios import RepositorioUsuarios

        return RepositorioUsuarios().papel_de_usuario_aprovado(chave)
    except Exception:
        logger.debug("Falha ao consultar papel no banco", exc_info=True)
        return None


def obter_papel(usuario_id):
    """Retorna o papel do usuário ou ``None`` se ele não estiver autorizado.

    Resolve primeiro em ``config`` (rápido, sem banco) e, se não encontrado,
    consulta o banco para reconhecer usuários aprovados no autocadastro.
    """
    chave = normalizar_id(usuario_id)
    if chave is None:
        return None
    papel = usuarios_autorizados().get(chave)
    if papel:
        return papel
    return _papel_do_banco(chave)


def esta_autorizado(usuario_id):
    """Retorna True se o usuário constar na lista de autorizados."""
    return obter_papel(usuario_id) is not None


def _papel_comporta(papel, nivel_minimo):
    if papel == PAPEL_ADMIN:
        return True
    if papel == PAPEL_USUARIO:
        return nivel_minimo <= NIVEL_USUARIO
    return False


def pode_executar(usuario_id, nivel_minimo):
    """Retorna True se o papel do usuário comporta o nível mínimo exigido."""
    return _papel_comporta(obter_papel(usuario_id), nivel_minimo)


def usuario_reconhecido(usuario_id):
    """True se o Telegram ID pertence a um usuário autorizado OU cadastrado.

    Usado pela allowlist de chats em ``bot.loader`` para permitir que um
    usuário autocadastrado receba as mensagens de status (pendente, aprovado,
    rejeitado, suspenso) mesmo sem constar na lista estática de ``config``.
    Falha segura: sem banco, só a lista de ``config`` vale.
    """
    chave = normalizar_id(usuario_id)
    if chave is None:
        return False
    if chave in usuarios_autorizados():
        return True
    try:
        from pipeline_dados.repositorio_usuarios import RepositorioUsuarios

        return RepositorioUsuarios().obter_por_telegram_id(chave) is not None
    except Exception:
        logger.debug("Falha ao verificar cadastro no banco", exc_info=True)
        return False


def e_comando_start(update):
    """True se o update for a mensagem pública de entrada ``/start``."""
    message = getattr(update, "message", None)
    if message is None:
        return False
    operacao = operacao_de_comando(getattr(message, "text", None))
    if operacao is None:
        return False
    return operacao[0] == f"comando:/{COMANDO_CADASTRO}"


def tem_fluxo_cadastro_ativo(usuario_id):
    """True se o usuário tem um formulário de autocadastro em andamento.

    Delega ao armazenamento de estado (``bot.sessao_cadastro``) por import
    preguiçoso, mantendo este módulo leve. Qualquer falha resulta em ``False``
    (falha segura: sem formulário reconhecido, nada é liberado).
    """
    try:
        from bot import sessao_cadastro

        return sessao_cadastro.tem_sessao_ativa(usuario_id)
    except Exception:
        logger.debug("Falha ao consultar formulario de cadastro", exc_info=True)
        return False


def _e_entrada_publica(nome):
    """Operações liberadas independentemente de papel (autocadastro público)."""
    return nome == f"comando:/{COMANDO_CADASTRO}"


def _e_operacao_do_formulario(nome):
    """Operações válidas apenas durante um formulário de autocadastro ativo."""
    if nome == f"comando:/{COMANDO_CANCELAR}":
        return True
    return nome.startswith(f"callback:{PREFIXO_CALLBACK_FORMULARIO}")


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
        # Entrada pública do autocadastro: liberada para qualquer usuário
        # identificável (inclusive ainda não cadastrado). A decisão de acesso
        # efetiva continua sendo tomada pelo fluxo de cadastro.
        if _e_entrada_publica(nome):
            return True, nome
        # Operações do formulário (cancelar e callbacks de confirmação): são
        # liberadas apenas enquanto existe formulário ativo para este usuário.
        if _e_operacao_do_formulario(nome) and tem_fluxo_cadastro_ativo(usuario_id):
            return True, nome
        return _papel_comporta(obter_papel(usuario_id), nivel_minimo), nome
    except Exception:
        logger.exception("Falha ao verificar permissao do update")
        return False, None
