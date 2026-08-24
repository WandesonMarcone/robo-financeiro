import logging
import os

logger = logging.getLogger(__name__)

ROLE_USER = "USER"
ROLE_ADMIN = "ADMIN"
ROLE_SUPERADMIN = "SUPERADMIN"

NIVEIS = {
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


def papel_do_usuario(user_id):
    """Retorna o papel (USER/ADMIN/SUPERADMIN) de um usuário."""
    if user_id in obter_superadmin_ids():
        return ROLE_SUPERADMIN
    if user_id in obter_admin_ids():
        return ROLE_ADMIN
    if user_id in obter_dono_ids():
        return ROLE_SUPERADMIN
    return ROLE_USER


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
