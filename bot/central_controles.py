"""Central de Controles administrativa (gestão de acessos pelo Telegram).

Entrega ao administrador autorizado um painel para gerenciar os acessos sem
tocar diretamente no banco de dados. Reutiliza os mecanismos do projeto:

* ``pipeline_dados.repositorio_usuarios`` para listar/consultar/atualizar o
  status (``definir_status``, com pré-condição de origem na própria gravação);
* ``bot.permissoes`` como fonte de verdade da autorização do autor;
* ``bot.cadastro`` para a auditoria (``registrar_auditoria``), o envio de
  mensagens (``enviar_texto``) e a notificação do usuário afetado
  (``notificar_usuario``), sem reimplementar nenhum deles;
* ``bot.telegram_utils.construir_menu_inicial`` para o atalho no menu.

Regras de projeto respeitadas
-----------------------------
* Visível e executável só pelo administrador autorizado. O acesso é
  revalidado a cada comando/callback a partir do Telegram ID do próprio update
  (nunca do ``callback_data``), e ``bot.permissoes`` já classifica ``/controles``
  e o prefixo ``adm_`` como administrativos antes de o handler rodar.
* O estado do usuário é relido a cada callback e a transição é conferida de novo
  no momento da gravação (``origens_permitidas``): botão/tela antigos não
  sobrescrevem um estado que mudou.
* Não cria tabelas nem migrações; só consulta/atualiza ``status_cadastro``.
* Não existe exclusão de usuários: a revogação é por rejeição/suspensão,
  preservando históricos, documentos e auditoria.
* Rejeitar, suspender e reativar (e reconsiderar uma rejeição) exigem
  confirmação explícita.
* Contas cujo acesso é definido em ``config.USUARIOS_AUTORIZADOS`` (por ex. o
  próprio administrador) e a própria conta do autor são somente leitura: a
  precedência de ``bot.permissoes`` é a configuração, então alterar o banco não
  revogaria o acesso e daria uma falsa impressão de suspensão.
* Auditoria: ``cadastro.registrar_auditoria`` (logger ``robo.auditoria``). A
  tabela ``auditoria_acesso`` não tem esquema declarado no repositório, então
  nenhuma coluna é presumida.
* Mensagens ao usuário afetado são as de ``bot.cadastro`` (genéricas, sem
  identificar o administrador nem expor dados administrativos).
"""

import logging

from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import cadastro, permissoes
from bot.loader import bot
from bot.telegram_utils import TEXTO_ACESSO_NEGADO
from pipeline_dados.modelos_usuarios import (
    STATUS_APROVADO,
    STATUS_PENDENTE,
    STATUS_REJEITADO,
    STATUS_SUSPENSO,
)
from pipeline_dados.repositorio_usuarios import RepositorioUsuarios

logger = logging.getLogger("robo.central")

# Prefixo exclusivo dos callbacks administrativos (também em
# ``bot.permissoes.CALLBACKS_ADMIN_PREFIXOS``: defesa em profundidade).
PREFIXO_CALLBACK = "adm_"

# Áreas da Central (chaves curtas: o callback_data do Telegram tem 64 bytes).
AREA_PENDENTES = "pend"
AREA_APROVADOS = "aprov"
AREA_REJEITADOS = "rej"
AREA_SUSPENSOS = "susp"

# chave -> (rótulo, status persistido, ícone)
AREAS = {
    AREA_PENDENTES: ("Solicitações pendentes", STATUS_PENDENTE, "📥"),
    AREA_APROVADOS: ("Usuários aprovados", STATUS_APROVADO, "✅"),
    AREA_REJEITADOS: ("Usuários rejeitados", STATUS_REJEITADO, "🚫"),
    AREA_SUSPENSOS: ("Usuários suspensos", STATUS_SUSPENSO, "⛔"),
}

ACAO_APROVAR = "aprovar"
ACAO_REJEITAR = "rejeitar"
ACAO_SUSPENDER = "suspender"
ACAO_REATIVAR = "reativar"

# ação -> (status alvo, status de origem permitidos). A reativação reaproveita a
# aprovação (volta para ``aprovado``); aprovar a partir de ``rejeitado`` é a
# reconsideração de uma rejeição.
ACOES = {
    ACAO_APROVAR: (STATUS_APROVADO, frozenset({STATUS_PENDENTE, STATUS_REJEITADO})),
    ACAO_REJEITAR: (STATUS_REJEITADO, frozenset({STATUS_PENDENTE})),
    ACAO_SUSPENDER: (STATUS_SUSPENSO, frozenset({STATUS_APROVADO})),
    ACAO_REATIVAR: (STATUS_APROVADO, frozenset({STATUS_SUSPENSO})),
}

# Ações que sempre exigem confirmação. Aprovar também exige quando reverte uma
# rejeição (ver ``_exige_confirmacao``).
ACOES_COM_CONFIRMACAO = frozenset({ACAO_REJEITAR, ACAO_SUSPENDER, ACAO_REATIVAR})

ROTULO_ACAO = {
    ACAO_APROVAR: "aprovar",
    ACAO_REJEITAR: "rejeitar",
    ACAO_SUSPENDER: "suspender",
    ACAO_REATIVAR: "reativar",
}
_PARTICIPIO = {
    ACAO_APROVAR: "acesso aprovado",
    ACAO_REJEITAR: "solicitação rejeitada",
    ACAO_SUSPENDER: "usuário suspenso",
    ACAO_REATIVAR: "usuário reativado",
}
_CONSEQUENCIA = {
    ACAO_APROVAR: "O usuário passará a ter acesso ao robô.",
    ACAO_REJEITAR: "A solicitação será recusada e o usuário não terá acesso.",
    ACAO_SUSPENDER: "O usuário perderá o acesso imediatamente.",
    ACAO_REATIVAR: "O usuário voltará a ter acesso ao robô.",
}

TAMANHO_PAGINA = 8

# Limites de sanidade para os números recebidos no callback_data.
_ID_MAXIMO = 2_147_483_647
_PAGINA_MAXIMA = 10_000

_ROTULO_SITUACAO = {
    STATUS_PENDENTE: "Pendente de aprovação",
    STATUS_APROVADO: "Aprovado",
    STATUS_REJEITADO: "Rejeitado",
    STATUS_SUSPENSO: "Suspenso",
}

TEXTO_ERRO = "⚠️ Não foi possível concluir a operação agora. Tente novamente."
TEXTO_ERRO_BANCO = "⚠️ Não foi possível acessar os cadastros agora. Tente novamente."
TEXTO_SESSAO_INVALIDA = "⚠️ Operação inválida. Abra a Central novamente com /controles."
TEXTO_ESTADO_INVALIDO = "ℹ️ O estado atual deste usuário não permite esta ação."
TEXTO_USUARIO_INEXISTENTE = "⚠️ Usuário não encontrado."
TEXTO_ACESSO_FIXO = (
    "🔒 O acesso desta conta é definido na configuração do sistema e não "
    "pode ser alterado por aqui."
)
TEXTO_PROPRIA_CONTA = "🔒 Você não pode alterar o acesso da sua própria conta."
TEXTO_USERNAME_INDISPONIVEL = "não disponível"


# ---------------------------------------------------------------------------
# Identificação do autor e autorização
# ---------------------------------------------------------------------------

def _id_do_autor(message_or_call):
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


def e_administrador(message_or_call):
    """True se o autor do update for o administrador autorizado.

    Revalida a autorização a partir do Telegram ID do próprio update (nunca de
    dados de callback). Qualquer falha resulta em ``False`` (falha segura).
    """
    try:
        return (
            permissoes.obter_papel(_id_do_autor(message_or_call))
            == permissoes.PAPEL_ADMIN
        )
    except Exception:
        logger.warning("CENTRAL - falha ao verificar autorizacao", exc_info=True)
        return False


def _motivo_bloqueio(dto, autor_id):
    """Texto de bloqueio se a conta não puder ser alterada por esta Central.

    * própria conta do autor: evita que o administrador se revogue;
    * conta definida em ``config.USUARIOS_AUTORIZADOS``: ``bot.permissoes`` dá
      precedência à configuração, então mudar o status no banco não revogaria o
      acesso (e a notificação "suspenso" seria enganosa).
    """
    chave = permissoes.normalizar_id(dto.telegram_user_id)
    if chave is not None and chave == permissoes.normalizar_id(autor_id):
        return TEXTO_PROPRIA_CONTA
    if chave is not None and chave in permissoes.usuarios_autorizados():
        return TEXTO_ACESSO_FIXO
    return None


def _exige_confirmacao(acao, status_atual):
    if acao in ACOES_COM_CONFIRMACAO:
        return True
    return acao == ACAO_APROVAR and status_atual == STATUS_REJEITADO


# ---------------------------------------------------------------------------
# Envio / renderização
# ---------------------------------------------------------------------------

def _responder_callback(call, texto=None, alerta=False):
    """Responde ao callback uma única vez (o Telegram só honra a primeira)."""
    try:
        bot.answer_callback_query(call.id, text=texto, show_alert=alerta)
    except Exception:
        logger.debug("CENTRAL - falha ao responder callback", exc_info=True)


def _render(call, texto, markup):
    chat_id, msg_id = _chat_e_message(call)
    if chat_id is None:
        return
    try:
        if msg_id is not None:
            bot.edit_message_text(texto, chat_id, msg_id, reply_markup=markup)
        else:
            bot.send_message(chat_id, texto, reply_markup=markup)
    except Exception as erro:
        # Reabrir a mesma tela (ex.: "Atualizar dados" sem mudanças) não é falha.
        if "message is not modified" in str(erro).lower():
            return
        logger.warning("CENTRAL - falha ao exibir tela", exc_info=True)


# ---------------------------------------------------------------------------
# Formatação
# ---------------------------------------------------------------------------

def _situacao(status):
    return _ROTULO_SITUACAO.get(status, status or "Desconhecida")


def _data(criado_em):
    try:
        return criado_em.strftime("%d/%m/%Y %H:%M")
    except (AttributeError, ValueError):
        return "Não informada"


def _protegido(dto):
    chave = permissoes.normalizar_id(dto.telegram_user_id)
    return chave is not None and chave in permissoes.usuarios_autorizados()


def _rotulo_usuario(dto):
    nome = dto.nome or "Sem nome"
    if len(nome) > 28:
        nome = nome[:27] + "…"
    cadeado = "🔒 " if _protegido(dto) else ""
    return f"👤 {cadeado}{nome} (#{dto.id})"


def _username_atual(dto):
    """Username do Telegram consultado na hora (não é persistido no banco).

    A tabela ``usuarios`` não tem coluna de username; ele é obtido do Telegram
    apenas para exibição ao administrador. Qualquer falha (usuário bloqueou o
    bot, sem conversa prévia, rede) resulta em ``None``.
    """
    destino = dto.telegram_chat_id or dto.telegram_user_id
    if destino is None:
        return None
    try:
        chat = bot.get_chat(destino)
    except Exception:
        logger.debug("CENTRAL - username indisponivel", exc_info=True)
        return None
    username = getattr(chat, "username", None)
    if not username:
        return None
    return str(username).strip().lstrip("@") or None


def _texto_hub():
    return "\n".join(
        [
            "⚙️ CENTRAL DE CONTROLES",
            "Escolha uma area:",
            "",
            "👥 Usuarios — solicitacoes e cadastros.",
            "🔔 Notificacoes — alertas por pessoa ou por FIIs/acoes favoritados.",
            "⚖️ Central de Revisoes — documentos suspeitos de FIIs.",
        ]
    )


def _markup_hub():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("👥 Usuarios", callback_data=f"{PREFIXO_CALLBACK}usuarios")
    )
    markup.add(
        InlineKeyboardButton(
            "🔔 Notificacoes", callback_data=f"{PREFIXO_CALLBACK}notificacoes"
        )
    )
    markup.add(
        InlineKeyboardButton(
            "⚖️ Central de Revisoes", callback_data=f"{PREFIXO_CALLBACK}revisoes"
        )
    )
    markup.add(InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="voltar_menu"))
    return markup


def _texto_home(contagens):
    linhas = [
        "⚙️ CENTRAL DE CONTROLES",
        "👥 Usuarios — gestao de acessos pelo Telegram.",
        "",
    ]
    for area, (rotulo, _status, icone) in AREAS.items():
        linhas.append(f"{icone} {rotulo}: {contagens[area]}")
    linhas += ["", "Selecione uma area para gerenciar:"]
    return "\n".join(linhas)


def _markup_home(contagens):
    markup = InlineKeyboardMarkup(row_width=1)
    for area, (rotulo, _status, icone) in AREAS.items():
        markup.add(
            InlineKeyboardButton(
                f"{icone} {rotulo} ({contagens[area]})",
                callback_data=f"{PREFIXO_CALLBACK}area_{area}_0",
            )
        )
    markup.add(
        InlineKeyboardButton(
            "🔁 Solicitacoes de troca", callback_data="trocaadm_home"
        )
    )
    markup.add(
        InlineKeyboardButton("🔙 Voltar", callback_data=f"{PREFIXO_CALLBACK}home")
    )
    return markup


def _contagens():
    repositorio = RepositorioUsuarios()
    return {
        area: repositorio.contar_por_status(status)
        for area, (_rotulo, status, _icone) in AREAS.items()
    }


def _texto_area(area, usuarios, pagina, total_paginas, total, aviso=None):
    rotulo, _status, icone = AREAS[area]
    linhas = []
    if aviso:
        linhas += [aviso, ""]
    linhas += ["⚙️ CENTRAL DE CONTROLES", f"{icone} {rotulo}", ""]
    if not usuarios:
        linhas.append("Nenhum usuário nesta área.")
    else:
        linhas.append(f"Página {pagina + 1}/{total_paginas} — {total} registro(s).")
        linhas.append("Toque em uma pessoa para ver os dados e as ações:")
    return "\n".join(linhas)


def _markup_area(area, usuarios, pagina, total_paginas):
    markup = InlineKeyboardMarkup(row_width=1)
    for dto in usuarios:
        markup.add(
            InlineKeyboardButton(
                _rotulo_usuario(dto),
                callback_data=f"{PREFIXO_CALLBACK}ver_{dto.id}_{area}_{pagina}",
            )
        )
    navegacao = []
    if pagina > 0:
        navegacao.append(
            InlineKeyboardButton(
                "⬅️ Anterior", callback_data=f"{PREFIXO_CALLBACK}area_{area}_{pagina - 1}"
            )
        )
    if pagina < total_paginas - 1:
        navegacao.append(
            InlineKeyboardButton(
                "Próxima ➡️", callback_data=f"{PREFIXO_CALLBACK}area_{area}_{pagina + 1}"
            )
        )
    if navegacao:
        markup.row(*navegacao)
    markup.add(
        InlineKeyboardButton("🔙 Voltar", callback_data=f"{PREFIXO_CALLBACK}usuarios")
    )
    return markup


def _texto_usuario(dto, autor_id, username):
    linhas = [
        "⚙️ CENTRAL DE CONTROLES",
        "",
        "DADOS CADASTRAIS",
        f"Nome completo: {dto.nome or 'Não informado'}",
        f"E-mail: {dto.email or 'Não informado'}",
        f"Telegram User ID: {dto.telegram_user_id}",
        f"Username: {'@' + username if username else TEXTO_USERNAME_INDISPONIVEL}",
        "Chat ID: "
        + (
            str(dto.telegram_chat_id)
            if dto.telegram_chat_id is not None
            else "não informado"
        ),
        f"Data de cadastro: {_data(dto.criado_em)}",
        f"Situação atual: {_situacao(dto.status)}",
        f"Identificador interno: #{dto.id}",
        "",
    ]
    bloqueio = _motivo_bloqueio(dto, autor_id)
    if bloqueio:
        linhas.append(bloqueio)
    else:
        linhas.append("Ações disponíveis:")
    return "\n".join(linhas)


def _botao_acao(acao, dto, area, pagina, rotulo):
    verbo = "conf" if _exige_confirmacao(acao, dto.status) else "do"
    return InlineKeyboardButton(
        rotulo,
        callback_data=f"{PREFIXO_CALLBACK}{verbo}_{acao}_{dto.id}_{area}_{pagina}",
    )


def _markup_usuario(dto, area, pagina, autor_id):
    markup = InlineKeyboardMarkup(row_width=1)
    # Contas somente-leitura não recebem botões de ação.
    if _motivo_bloqueio(dto, autor_id) is None:
        if dto.status == STATUS_PENDENTE:
            markup.add(_botao_acao(ACAO_APROVAR, dto, area, pagina, "✅ Aprovar solicitação"))
            markup.add(_botao_acao(ACAO_REJEITAR, dto, area, pagina, "🚫 Rejeitar solicitação"))
        elif dto.status == STATUS_APROVADO:
            markup.add(_botao_acao(ACAO_SUSPENDER, dto, area, pagina, "⛔ Suspender usuário"))
        elif dto.status == STATUS_REJEITADO:
            markup.add(
                _botao_acao(ACAO_APROVAR, dto, area, pagina, "✅ Aprovar (reconsiderar)")
            )
        elif dto.status == STATUS_SUSPENSO:
            markup.add(_botao_acao(ACAO_REATIVAR, dto, area, pagina, "♻️ Reativar usuário"))
    markup.add(
        InlineKeyboardButton(
            "🔄 Atualizar dados",
            callback_data=f"{PREFIXO_CALLBACK}ver_{dto.id}_{area}_{pagina}",
        )
    )
    markup.add(
        InlineKeyboardButton(
            "🔙 Voltar à lista",
            callback_data=f"{PREFIXO_CALLBACK}area_{area}_{pagina}",
        )
    )
    return markup


# ---------------------------------------------------------------------------
# Telas
# ---------------------------------------------------------------------------

def _tela_hub():
    return _texto_hub(), _markup_hub()


def _tela_home():
    contagens = _contagens()
    return _texto_home(contagens), _markup_home(contagens)


def _mostrar_hub(call):
    _render(call, *_tela_hub())
    return None


def _mostrar_home(call):
    try:
        texto, markup = _tela_home()
    except Exception:
        logger.warning("CENTRAL - falha ao montar home", exc_info=True)
        _render(
            call,
            TEXTO_ERRO_BANCO,
            InlineKeyboardMarkup().add(
                InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="voltar_menu")
            ),
        )
        return TEXTO_ERRO_BANCO
    _render(call, texto, markup)
    return None


def _formatar_valor_alerta(valor):
    if valor is None:
        return None
    texto = format(valor, "f") if hasattr(valor, "as_tuple") else str(valor)
    if "." in texto:
        texto = texto.rstrip("0").rstrip(".")
    return texto or "0"


def _linhas_eventos_alerta(eventos):
    linhas = []
    for evento in eventos:
        data = (
            evento.data_evento.strftime("%d/%m/%Y %H:%M")
            if evento.data_evento
            else "Data N/A"
        )
        linhas.append(f"🏢 {evento.ticker} — {data}")
        linhas.append(
            f"🏷️ {evento.indicador} · {evento.regra} · {evento.severidade}"
        )
        if evento.motivo:
            linhas.append(str(evento.motivo))
        atual = _formatar_valor_alerta(evento.valor_atual)
        anterior = _formatar_valor_alerta(evento.valor_anterior)
        if atual is not None or anterior is not None:
            partes = []
            if atual is not None:
                partes.append(f"atual {atual}")
            if anterior is not None:
                partes.append(f"anterior {anterior}")
            linhas.append(" · ".join(partes))
        linhas.append("")
    return linhas


def _texto_menu_notificacoes():
    return "\n".join(
        [
            "🔔 NOTIFICACOES",
            "Alertas importantes. Escolha o recorte:",
            "",
            "👤 Por pessoa — alertas dos favoritos de cada usuario.",
            "🏢 Por FIIs/acoes favoritados — recorte pelos ativos acompanhados.",
        ]
    )


def _markup_menu_notificacoes():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton(
            "👤 Por pessoa", callback_data=f"{PREFIXO_CALLBACK}npessoas_0"
        )
    )
    markup.add(
        InlineKeyboardButton(
            "🏢 Por FIIs/acoes favoritados",
            callback_data=f"{PREFIXO_CALLBACK}nativos",
        )
    )
    markup.add(InlineKeyboardButton("🔙 Voltar", callback_data=f"{PREFIXO_CALLBACK}home"))
    return markup


def _texto_notificacoes():
    from pipeline_dados.repositorio_alertas import RepositorioAlertas
    from pipeline_dados.repositorio_favoritos import RepositorioFavoritos

    ids = RepositorioFavoritos().listar_ids_ativos_acompanhados()
    if not ids:
        return (
            "🔔 NOTIFICACOES\n"
            "Alertas importantes dos FIIs e acoes favoritados por usuarios.\n\n"
            "Nenhum ativo favoritado. Sem recorte de alertas."
        )
    eventos = RepositorioAlertas().listar_por_ativos(ids, limite=15)
    if not eventos:
        return (
            "🔔 NOTIFICACOES\n"
            "Alertas importantes dos FIIs e acoes favoritados por usuarios.\n\n"
            "Nenhum evento persistido nesses ativos."
        )
    linhas = [
        "🔔 NOTIFICACOES",
        "Alertas importantes dos FIIs e acoes favoritados por usuarios.",
        "Fato persistido; telegram_enviado nao prova entrega.",
        "",
    ]
    linhas.extend(_linhas_eventos_alerta(eventos))
    return "\n".join(linhas).rstrip()


def _markup_notificacoes_ativos():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("🔄 Atualizar", callback_data=f"{PREFIXO_CALLBACK}nativos")
    )
    markup.add(
        InlineKeyboardButton(
            "🔙 Voltar", callback_data=f"{PREFIXO_CALLBACK}notificacoes"
        )
    )
    return markup


def _pessoas_com_favoritos():
    from pipeline_dados.repositorio_favoritos import RepositorioFavoritos

    repo_u = RepositorioUsuarios()
    repo_f = RepositorioFavoritos()
    pessoas = []
    total = min(repo_u.contar_por_status(STATUS_APROVADO), 200)
    deslocamento = 0
    while deslocamento < total:
        lote = repo_u.listar_por_status(
            STATUS_APROVADO, limite=50, deslocamento=deslocamento
        )
        if not lote:
            break
        for dto in lote:
            favs = repo_f.listar(dto.id)
            if favs:
                pessoas.append((dto, favs))
        deslocamento += len(lote)
        if len(lote) < 50:
            break
    return pessoas


def _rotulo_pessoa_notificacao(dto, favs):
    nome = dto.nome or "Sem nome"
    if len(nome) > 22:
        nome = nome[:21] + "…"
    return f"👤 {nome} ({len(favs)} ativo(s))"


def _texto_notificacoes_pessoas(pessoas, pagina, total_paginas):
    linhas = [
        "🔔 NOTIFICACOES",
        "👤 Por pessoa — alertas dos favoritos de cada usuario.",
        "",
    ]
    if not pessoas:
        linhas.append("Nenhum usuario aprovado com ativos favoritados.")
        return "\n".join(linhas)
    linhas.append(f"Pagina {pagina + 1}/{total_paginas} — toque em uma pessoa:")
    return "\n".join(linhas)


def _markup_notificacoes_pessoas(pessoas, pagina, total_paginas):
    markup = InlineKeyboardMarkup(row_width=1)
    for dto, favs in pessoas:
        markup.add(
            InlineKeyboardButton(
                _rotulo_pessoa_notificacao(dto, favs),
                callback_data=f"{PREFIXO_CALLBACK}npessoa_{dto.id}",
            )
        )
    navegacao = []
    if pagina > 0:
        navegacao.append(
            InlineKeyboardButton(
                "⬅️ Anterior",
                callback_data=f"{PREFIXO_CALLBACK}npessoas_{pagina - 1}",
            )
        )
    if pagina < total_paginas - 1:
        navegacao.append(
            InlineKeyboardButton(
                "Próxima ➡️",
                callback_data=f"{PREFIXO_CALLBACK}npessoas_{pagina + 1}",
            )
        )
    if navegacao:
        markup.row(*navegacao)
    markup.add(
        InlineKeyboardButton(
            "🔙 Voltar", callback_data=f"{PREFIXO_CALLBACK}notificacoes"
        )
    )
    return markup


def _texto_notificacoes_pessoa(dto, favs, eventos):
    tickers = ", ".join(f.ticker for f in favs) or "nenhum"
    linhas = [
        "🔔 NOTIFICACOES",
        f"👤 {dto.nome or 'Sem nome'}",
        f"⭐ Favoritos: {tickers}",
        "Fato persistido; telegram_enviado nao prova entrega.",
        "",
    ]
    if not eventos:
        linhas.append("Nenhum evento persistido nos favoritos desta pessoa.")
        return "\n".join(linhas)
    linhas.extend(_linhas_eventos_alerta(eventos))
    return "\n".join(linhas).rstrip()


def _markup_notificacoes_pessoa(usuario_id):
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton(
            "🔄 Atualizar", callback_data=f"{PREFIXO_CALLBACK}npessoa_{usuario_id}"
        )
    )
    markup.add(
        InlineKeyboardButton(
            "🔙 Voltar", callback_data=f"{PREFIXO_CALLBACK}npessoas_0"
        )
    )
    return markup


def _mostrar_notificacoes(call):
    _render(call, _texto_menu_notificacoes(), _markup_menu_notificacoes())
    return None


def _mostrar_notificacoes_ativos(call):
    try:
        texto = _texto_notificacoes()
    except Exception:
        logger.warning("CENTRAL - falha ao listar alertas", exc_info=True)
        texto = TEXTO_ERRO_BANCO
    _render(call, texto, _markup_notificacoes_ativos())
    return None


def _mostrar_notificacoes_pessoas(call, pagina):
    try:
        todas = _pessoas_com_favoritos()
    except Exception:
        logger.warning("CENTRAL - falha ao listar pessoas", exc_info=True)
        _render(
            call,
            TEXTO_ERRO_BANCO,
            InlineKeyboardMarkup().add(
                InlineKeyboardButton(
                    "🔙 Voltar", callback_data=f"{PREFIXO_CALLBACK}notificacoes"
                )
            ),
        )
        return TEXTO_ERRO_BANCO
    total = len(todas)
    total_paginas = max(1, (total + TAMANHO_PAGINA - 1) // TAMANHO_PAGINA)
    pagina = max(0, min(pagina, total_paginas - 1))
    fatia = todas[pagina * TAMANHO_PAGINA : (pagina + 1) * TAMANHO_PAGINA]
    _render(
        call,
        _texto_notificacoes_pessoas(fatia if total else [], pagina, total_paginas),
        _markup_notificacoes_pessoas(fatia, pagina, total_paginas),
    )
    return None


def _mostrar_notificacoes_pessoa(call, usuario_id):
    from pipeline_dados.repositorio_alertas import RepositorioAlertas
    from pipeline_dados.repositorio_favoritos import RepositorioFavoritos

    try:
        dto = RepositorioUsuarios().obter_por_id(usuario_id)
        favs = RepositorioFavoritos().listar(usuario_id) if dto is not None else []
        ids = [f.ativo_id for f in favs]
        eventos = RepositorioAlertas().listar_por_ativos(ids, limite=15) if ids else []
    except Exception:
        logger.warning("CENTRAL - falha ao listar alertas da pessoa", exc_info=True)
        _render(
            call,
            TEXTO_ERRO_BANCO,
            InlineKeyboardMarkup().add(
                InlineKeyboardButton(
                    "🔙 Voltar", callback_data=f"{PREFIXO_CALLBACK}npessoas_0"
                )
            ),
        )
        return TEXTO_ERRO_BANCO
    if dto is None:
        return _mostrar_notificacoes_pessoas(call, 0) or TEXTO_USUARIO_INEXISTENTE
    _render(
        call,
        _texto_notificacoes_pessoa(dto, favs, eventos),
        _markup_notificacoes_pessoa(usuario_id),
    )
    return None


def _mostrar_revisoes(call):
    from bot.callbacks_revisao import enviar_painel_tickers

    chat_id, msg_id = _chat_e_message(call)
    if chat_id is None:
        return TEXTO_ERRO
    enviar_painel_tickers(chat_id, msg_id)
    return None


def _montar_area(area, pagina, aviso=None):
    """Monta a tela de uma área; retorna ``(texto, markup)`` ou ``None``."""
    if area not in AREAS:
        return None
    _rotulo, status, _icone = AREAS[area]
    repositorio = RepositorioUsuarios()
    total = repositorio.contar_por_status(status)
    total_paginas = max(1, (total + TAMANHO_PAGINA - 1) // TAMANHO_PAGINA)
    pagina = max(0, min(pagina, total_paginas - 1))
    usuarios = repositorio.listar_por_status(
        status, limite=TAMANHO_PAGINA, deslocamento=pagina * TAMANHO_PAGINA
    )
    texto = _texto_area(area, usuarios, pagina, total_paginas, total, aviso=aviso)
    markup = _markup_area(area, usuarios, pagina, total_paginas)
    return texto, markup


def _mostrar_area(call, area, pagina, aviso=None):
    try:
        tela = _montar_area(area, pagina, aviso=aviso)
    except Exception:
        logger.warning("CENTRAL - falha ao listar area", exc_info=True)
        return TEXTO_ERRO_BANCO
    if tela is None:
        _mostrar_home(call)
        return TEXTO_SESSAO_INVALIDA
    _render(call, tela[0], tela[1])
    return None


def _mostrar_usuario(call, dto, area, pagina):
    autor_id = _id_do_autor(call)
    _render(
        call,
        _texto_usuario(dto, autor_id, _username_atual(dto)),
        _markup_usuario(dto, area, pagina, autor_id),
    )


# ---------------------------------------------------------------------------
# Auditoria
# ---------------------------------------------------------------------------

def _registrar(autor_id, usuario_id, acao, resultado, status_anterior=None):
    cadastro.registrar_auditoria(
        autor_id,
        usuario_id,
        f"central_{acao}",
        resultado,
        status_anterior=status_anterior,
    )


# ---------------------------------------------------------------------------
# Interpretação do callback_data (valores sempre validados)
# ---------------------------------------------------------------------------

def _inteiro(valor, minimo, maximo):
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        return None
    if numero < minimo or numero > maximo:
        return None
    return numero


def _id_usuario(valor):
    return _inteiro(valor, 1, _ID_MAXIMO)


def _num_pagina(valor):
    return _inteiro(valor, 0, _PAGINA_MAXIMA)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

@bot.message_handler(commands=["controles"])
def abrir_central(message):
    """Abre a Central de Controles (exclusiva do administrador autorizado)."""
    chat_id, _msg = _chat_e_message(message)
    if not e_administrador(message):
        logger.warning("CENTRAL - comando negado (autor nao admin)")
        cadastro.registrar_auditoria(
            _id_do_autor(message), None, "central_negada", "autor_nao_admin"
        )
        cadastro.enviar_texto(chat_id, TEXTO_ACESSO_NEGADO)
        return
    if chat_id is None:
        return
    texto, markup = _tela_hub()
    cadastro.enviar_texto(chat_id, texto, reply_markup=markup)


@bot.callback_query_handler(
    func=lambda call: bool(call.data) and call.data.startswith(PREFIXO_CALLBACK)
)
def tratar_callback(call):
    """Despachante único dos callbacks da Central.

    Revalida a autorização do autor a cada chamada (a permissão não depende da
    existência do botão nem do identificador enviado pelo Telegram) e responde
    ao callback exatamente uma vez.
    """
    autor_id = _id_do_autor(call)
    if not e_administrador(call):
        logger.warning("CENTRAL - callback negado (autor nao admin)")
        cadastro.registrar_auditoria(autor_id, None, "central_negada", "autor_nao_admin")
        _responder_callback(call, TEXTO_ACESSO_NEGADO, alerta=True)
        return

    partes = (call.data or "").split("_")
    acao = partes[1] if len(partes) > 1 else ""
    try:
        if acao == "home":
            toast = _mostrar_hub(call)
        elif acao == "usuarios":
            toast = _mostrar_home(call)
        elif acao == "notificacoes":
            toast = _mostrar_notificacoes(call)
        elif acao == "nativos":
            toast = _mostrar_notificacoes_ativos(call)
        elif acao == "npessoas":
            pagina = _num_pagina(partes[2]) if len(partes) >= 3 else 0
            if pagina is None:
                toast = TEXTO_SESSAO_INVALIDA
            else:
                toast = _mostrar_notificacoes_pessoas(call, pagina)
        elif acao == "npessoa":
            usuario_id = _id_usuario(partes[2]) if len(partes) >= 3 else None
            if usuario_id is None:
                toast = TEXTO_SESSAO_INVALIDA
            else:
                toast = _mostrar_notificacoes_pessoa(call, usuario_id)
        elif acao == "revisoes":
            toast = _mostrar_revisoes(call)
        elif acao == "area":
            toast = _tratar_area(call, partes)
        elif acao == "ver":
            toast = _tratar_ver(call, partes)
        elif acao == "conf":
            toast = _tratar_conf(call, partes)
        elif acao == "do":
            toast = _tratar_do(call, partes)
        else:
            _mostrar_hub(call)
            toast = TEXTO_SESSAO_INVALIDA
    except Exception:
        logger.warning("CENTRAL - falha ao processar callback", exc_info=True)
        toast = TEXTO_ERRO
    _responder_callback(call, toast)


def _tratar_area(call, partes):
    # adm_area_<area>_<pagina>
    if len(partes) != 4:
        return TEXTO_SESSAO_INVALIDA
    area, pagina = partes[2], _num_pagina(partes[3])
    if area not in AREAS or pagina is None:
        return TEXTO_SESSAO_INVALIDA
    return _mostrar_area(call, area, pagina)


def _tratar_ver(call, partes):
    # adm_ver_<id>_<area>_<pagina>
    if len(partes) != 5:
        return TEXTO_SESSAO_INVALIDA
    usuario_id = _id_usuario(partes[2])
    area, pagina = partes[3], _num_pagina(partes[4])
    if usuario_id is None or area not in AREAS or pagina is None:
        return TEXTO_SESSAO_INVALIDA
    try:
        dto = RepositorioUsuarios().obter_por_id(usuario_id)
    except Exception:
        logger.warning("CENTRAL - falha ao carregar usuario", exc_info=True)
        return TEXTO_ERRO_BANCO
    if dto is None:
        return _voltar_a_lista(call, area, pagina, TEXTO_USUARIO_INEXISTENTE)
    _mostrar_usuario(call, dto, area, pagina)
    return None


def _voltar_a_lista(call, area, pagina, toast):
    erro = _mostrar_area(call, area, pagina)
    return erro or toast


def _parse_acao(partes):
    """``adm_<conf|do>_<acao>_<id>_<area>_<pagina>`` -> (acao, id, area, pagina)."""
    if len(partes) != 6:
        return None
    acao, usuario_id = partes[2], _id_usuario(partes[3])
    area, pagina = partes[4], _num_pagina(partes[5])
    if acao not in ACOES or usuario_id is None or area not in AREAS or pagina is None:
        return None
    return acao, usuario_id, area, pagina


def _tratar_conf(call, partes):
    # adm_conf_<acao>_<id>_<area>_<pagina>: tela de confirmação (não altera nada)
    parsed = _parse_acao(partes)
    if parsed is None:
        return TEXTO_SESSAO_INVALIDA
    acao, usuario_id, area, pagina = parsed
    autor_id = _id_do_autor(call)
    try:
        dto = RepositorioUsuarios().obter_por_id(usuario_id)
    except Exception:
        logger.warning("CENTRAL - falha ao carregar usuario", exc_info=True)
        return TEXTO_ERRO_BANCO
    if dto is None:
        return _voltar_a_lista(call, area, pagina, TEXTO_USUARIO_INEXISTENTE)

    bloqueio = _motivo_bloqueio(dto, autor_id)
    if bloqueio:
        _registrar(autor_id, dto.id, acao, "bloqueado", status_anterior=dto.status)
        _mostrar_usuario(call, dto, area, pagina)
        return bloqueio

    _status_alvo, origens = ACOES[acao]
    if dto.status not in origens:
        _registrar(autor_id, dto.id, acao, "estado_invalido", status_anterior=dto.status)
        _mostrar_usuario(call, dto, area, pagina)
        return TEXTO_ESTADO_INVALIDO

    rotulo = ROTULO_ACAO[acao]
    texto = (
        "⚠️ CONFIRMAÇÃO\n\n"
        f"Deseja realmente {rotulo} o acesso de:\n\n"
        f"👤 {dto.nome or 'Sem nome'}\n"
        f"🆔 Telegram User ID: {dto.telegram_user_id}\n"
        f"📌 Situação atual: {_situacao(dto.status)}\n\n"
        f"{_CONSEQUENCIA[acao]}\n"
        "Esta ação será registrada na auditoria."
    )
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton(
            f"✅ Sim, {rotulo}",
            callback_data=f"{PREFIXO_CALLBACK}do_{acao}_{dto.id}_{area}_{pagina}",
        )
    )
    markup.add(
        InlineKeyboardButton(
            "❌ Cancelar",
            callback_data=f"{PREFIXO_CALLBACK}ver_{dto.id}_{area}_{pagina}",
        )
    )
    _render(call, texto, markup)
    return None


def _tratar_do(call, partes):
    # adm_do_<acao>_<id>_<area>_<pagina>: executa a decisão (com revalidação)
    parsed = _parse_acao(partes)
    if parsed is None:
        return TEXTO_SESSAO_INVALIDA
    acao, usuario_id, area, pagina = parsed
    autor_id = _id_do_autor(call)
    status_alvo, origens = ACOES[acao]

    try:
        dto = RepositorioUsuarios().obter_por_id(usuario_id)
    except Exception:
        logger.warning("CENTRAL - falha ao carregar usuario", exc_info=True)
        _registrar(autor_id, usuario_id, acao, "falha_banco")
        return TEXTO_ERRO_BANCO
    if dto is None:
        _registrar(autor_id, usuario_id, acao, "usuario_inexistente")
        return _voltar_a_lista(call, area, pagina, TEXTO_USUARIO_INEXISTENTE)

    status_anterior = dto.status

    bloqueio = _motivo_bloqueio(dto, autor_id)
    if bloqueio:
        _registrar(autor_id, dto.id, acao, "bloqueado", status_anterior=status_anterior)
        _mostrar_usuario(call, dto, area, pagina)
        return bloqueio

    if status_anterior not in origens and status_anterior != status_alvo:
        _registrar(autor_id, dto.id, acao, "estado_invalido", status_anterior=status_anterior)
        _mostrar_usuario(call, dto, area, pagina)
        return TEXTO_ESTADO_INVALIDO

    try:
        # A origem é conferida de novo na gravação (mesma sessão do banco).
        atualizado, mudou = RepositorioUsuarios().definir_status(
            usuario_id, status_alvo, origens_permitidas=origens
        )
    except Exception:
        logger.warning("CENTRAL - falha ao aplicar decisao", exc_info=True)
        _registrar(autor_id, dto.id, acao, "falha_banco", status_anterior=status_anterior)
        return TEXTO_ERRO_BANCO

    if atualizado is None:
        _registrar(autor_id, dto.id, acao, "usuario_inexistente", status_anterior=status_anterior)
        return _voltar_a_lista(call, area, pagina, TEXTO_USUARIO_INEXISTENTE)

    if not mudou and atualizado.status != status_alvo:
        # O estado mudou entre a leitura e a gravação: nada foi alterado.
        _registrar(
            autor_id, dto.id, acao, "estado_invalido", status_anterior=atualizado.status
        )
        _mostrar_usuario(call, atualizado, area, pagina)
        return TEXTO_ESTADO_INVALIDO

    _registrar(
        autor_id,
        dto.id,
        acao,
        "aplicada" if mudou else "ja_constava",
        status_anterior=status_anterior,
    )

    nome = atualizado.nome or "Usuário"
    if mudou:
        toast = f"✅ {_PARTICIPIO[acao].capitalize()}."
        aviso = (
            f"✅ {nome} — {_PARTICIPIO[acao]}. "
            f"Situação atual: {_situacao(status_alvo)}."
        )
        # Só notifica quando houve mudança real (cliques repetidos não duplicam).
        cadastro.notificar_usuario(atualizado, reativado=(acao == ACAO_REATIVAR))
    else:
        toast = f"ℹ️ Já constava como {_situacao(status_alvo).lower()}."
        aviso = f"ℹ️ {nome} já constava como {_situacao(status_alvo)}."

    # Atualiza a interface voltando à lista da área (a página é reajustada).
    erro = _mostrar_area(call, area, pagina, aviso=aviso)
    return erro or toast
