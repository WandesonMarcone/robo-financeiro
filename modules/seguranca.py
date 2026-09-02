import logging
import os

logger = logging.getLogger(__name__)

ROLE_USER = "USER"
ROLE_ADMIN = "ADMIN"
ROLE_SUPERADMIN = "SUPERADMIN"
ROLE_VISITOR = "VISITOR"

# Sinalização interna (Etapa 8): Telegram ID vinculado no banco a um usuário
# DESATIVADO. Não é um papel atribuível: apenas indica que a identidade do banco
# prevalece sobre o legado e o acesso às funções protegidas deve ser negado.
ROLE_DESATIVADO = "DESATIVADO"

# Níveis usados apenas para comparar hierarquia na resolução de papel
# (Fase 5, Etapa 4). VISITOR fica abaixo de USER; a matriz completa de
# permissões pertence a uma etapa posterior.
NIVEIS = {
    ROLE_VISITOR: -1,
    ROLE_USER: 0,
    ROLE_ADMIN: 1,
    ROLE_SUPERADMIN: 2,
}

_MENSAGEM_NEGACAO = (
    "⛔ Acesso negado. Este comando exige o papel `{papel}`.\n"
    "Se você é o responsável pelo projeto, defina as variáveis "
    "`ADMIN_CHAT_IDS` e/ou `SUPERADMIN_CHAT_IDS` no ambiente."
)


def _parse_id_list(raw):
    """Converte '123, 456,789' em [123, 456, 789]. Ignora valores inválidos."""
    ids = []
    for parte in str(raw or "").split(","):
        parte = parte.strip()
        if parte.isdigit():
            ids.append(int(parte))
    return ids


def obter_admin_ids():
    """IDs de chat/usuário com papel ADMIN (via ADMIN_CHAT_IDS)."""
    return _parse_id_list(os.environ.get("ADMIN_CHAT_IDS"))


def obter_superadmin_ids():
    """IDs de chat/usuário com papel SUPERADMIN (via SUPERADMIN_CHAT_IDS)."""
    ids = _parse_id_list(os.environ.get("SUPERADMIN_CHAT_IDS"))
    if ids:
        return ids
    # Fallback compatível: sem SUPERADMIN_CHAT_IDS, admin também é superadmin.
    return obter_admin_ids()


def obter_dono_ids():
    """Chat principal de alertas (TELEGRAM_CHAT_ID).

    Mantido como SUPERADMIN para preservar o comportamento de operador único
    anterior à Fase 2, quando esse ID dava acesso total ao sistema.
    """
    dono = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    return [int(dono)] if dono.isdigit() else []


def _papel_no_banco(user_id):
    """Papel do Telegram ID a partir do banco (Fase 5, Etapas 4 e 8).

    Consulta a tabela ``usuarios`` pelo ``telegram_user_id`` vinculado. Retorna:

    - o ``papel`` quando o usuário está vinculado e ATIVO;
    - ``ROLE_DESATIVADO`` quando vinculado porém desativado (a identidade do
      banco prevalece sobre o legado: o acesso às funções protegidas é negado e
      NÃO há fallback para as variáveis de ambiente — o vínculo não é apagado e
      o SUPERADMIN pode reativar o usuário depois);
    - ``None`` quando não há vínculo, o banco está vazio/indisponível ou a
      consulta falha (o chamador cai no comportamento legado).

    Nunca lança exceção: qualquer falha é registrada em log sem segredos. A
    importação é preguiçosa para não atrasar o import do módulo nem quebrá-lo
    caso a infraestrutura de banco não esteja pronta.
    """
    try:
        from atualizador_documentos import SessionDB
        from pipeline_dados.banco_dados import Usuario

        sessao = SessionDB()
        try:
            usuario = (
                sessao.query(Usuario)
                .filter(Usuario.telegram_user_id == user_id)
                .first()
            )
            if usuario is None:
                return None
            if not usuario.ativo:
                return ROLE_DESATIVADO
            if usuario.papel in NIVEIS:
                return usuario.papel
            return None
        finally:
            sessao.close()
    except Exception as e:
        logger.warning(
            "Falha ao consultar papel do usuário %s no banco (%s); usando comportamento legado.",
            user_id,
            type(e).__name__,
        )
        return None


def _papel_legado(user_id):
    """Mecanismo legado exato de resolução de papel.

    Ordem preservada: SUPERADMIN_CHAT_IDS, ADMIN_CHAT_IDS e TELEGRAM_CHAT_ID
    (dono, também SUPERADMIN). Sem configuração, retorna USER.
    """
    if user_id in obter_superadmin_ids():
        return ROLE_SUPERADMIN
    if user_id in obter_admin_ids():
        return ROLE_ADMIN
    if user_id in obter_dono_ids():
        return ROLE_SUPERADMIN
    return ROLE_USER


def papel_do_usuario(user_id):
    """Retorna o papel (VISITOR/USER/ADMIN/SUPERADMIN) de um usuário.

    Resolução DB-first (Fase 5, Etapas 4 e 8):
    1. Se o Telegram ID está vinculado a um ``Usuario`` ATIVO no banco, o papel
       vem do banco (fonte de identidade).
    2. Se está vinculado a um usuário DESATIVADO, o acesso é negado
       (retorna ``VISITOR``) — o banco prevalece e não há fallback legado.
    3. Sem vínculo, banco vazio/indisponível ou erro na consulta, utiliza
       EXATAMENTE o mecanismo legado (``SUPERADMIN_CHAT_IDS``,
       ``ADMIN_CHAT_IDS`` e ``TELEGRAM_CHAT_ID``).
    """
    if user_id is None:
        return _papel_legado(user_id)
    papel_db = _papel_no_banco(user_id)
    if papel_db == ROLE_DESATIVADO:
        return ROLE_VISITOR
    if papel_db is not None:
        return papel_db
    return _papel_legado(user_id)


def usuario_tem_papel(user_id, papel_minimo):
    """True se user_id possui papel igual ou superior a papel_minimo."""
    return NIVEIS[papel_do_usuario(user_id)] >= NIVEIS[papel_minimo]


def eh_admin(user_id):
    return usuario_tem_papel(user_id, ROLE_ADMIN)


def eh_superadmin(user_id):
    return usuario_tem_papel(user_id, ROLE_SUPERADMIN)


def negar_acesso(bot, message, papel_necessario):
    """Responde negando acesso e registra o evento em log."""
    user_id = getattr(message.from_user, "id", None)
    comando = getattr(message, "text", "") or ""
    logger.warning(
        "Acesso negado: usuário %s tentou usar '%s' (exigido: %s)",
        user_id,
        comando.split()[0] if comando else comando,
        papel_necessario,
    )
    try:
        bot.reply_to(
            message,
            _MENSAGEM_NEGACAO.format(papel=papel_necessario),
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error("Falha ao enviar mensagem de acesso negado: %s", e)
