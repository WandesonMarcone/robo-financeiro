"""Solicitações de troca de ativo favorito (usuário solicita, admin decide).

Fluxo implementado (persistente, com histórico):

1. O usuário aprovado abre um dos seus favoritos e toca em "🔁 Trocar".
2. Escolhe um ativo de destino do mesmo tipo (FII→FII, Ação→Ação), disponível no
   catálogo, e confirma.
3. A solicitação é gravada como ``pendente`` na tabela ``solicitacoes_troca``
   (criada manualmente pela migração 0002 — nunca automaticamente). O admin é
   notificado com um atalho.
4. O administrador decide na Central de Controles ("🔁 Solicitações de troca"):
   aprovar aplica a troca de favoritos atomicamente; rejeitar apenas registra.
5. O solicitante é notificado do resultado. A expiração (configurável em
   ``config.TROCAS_PRAZO_HORAS``) apenas marca como ``expirada`` — NUNCA aprova
   automaticamente — e o registro é preservado.

Regras de projeto respeitadas:
* autorização revalidada a cada callback pelo Telegram ID do próprio update;
* nenhuma tabela é criada em produção (migração manual documentada);
* decisões duplicadas e callbacks antigos são bloqueados (estado terminal +
  conferência de origem na gravação);
* ativos inexistentes/não suportados são recusados (o catálogo vem de ``ativos``);
* handlers registrados com filtros específicos, importados ANTES do handler
  genérico de ``bot.callbacks_menus``, e os callbacks administrativos usam um
  prefixo próprio (``trocaadm_``) para não colidir com o despachante ``adm_`` da
  Central de Controles.
"""

import logging
from datetime import datetime

from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
from bot.loader import bot
from bot import cadastro, menu_principal, permissoes
from bot.telegram_utils import TEXTO_ACESSO_NEGADO
from pipeline_dados.modelos_trocas import (
    STATUS_TROCA_APROVADA,
    STATUS_TROCA_EXPIRADA,
    STATUS_TROCA_PENDENTE,
    STATUS_TROCA_REJEITADA,
)
from pipeline_dados.repositorio_favoritos import RepositorioFavoritos
from pipeline_dados.repositorio_trocas import (
    RepositorioTrocas,
    TrocaInvalidaError,
)
from pipeline_dados.repositorio_usuarios import RepositorioUsuarios

logger = logging.getLogger("robo.trocas")

PREFIXO_USUARIO = "troca_"
PREFIXO_ADMIN = "trocaadm_"

TAMANHO_PAGINA = 12

TEXTO_SEM_CONTA = menu_principal.TEXTO_SEM_CONTA
TEXTO_ERRO_BANCO = "⚠️ Não foi possível acessar as solicitações agora. Tente novamente."
TEXTO_INVALIDO = "⚠️ Operação inválida. Abra os favoritos novamente."

ACAO_APROVAR = "aprovar"
ACAO_REJEITAR = "rejeitar"

# status persistido -> (chave curta, rótulo)
AREAS_TROCA = {
    STATUS_TROCA_PENDENTE: ("pend", "Solicitações de troca pendentes"),
    STATUS_TROCA_APROVADA: ("aprov", "Trocas aprovadas"),
    STATUS_TROCA_REJEITADA: ("rej", "Trocas rejeitadas"),
    STATUS_TROCA_EXPIRADA: ("exp", "Trocas expiradas"),
}
_AREA_POR_CHAVE = {chave: status for status, (chave, _rot) in AREAS_TROCA.items()}

_ROTULO_STATUS = {
    STATUS_TROCA_PENDENTE: "Pendente",
    STATUS_TROCA_APROVADA: "Aprovada",
    STATUS_TROCA_REJEITADA: "Rejeitada",
    STATUS_TROCA_EXPIRADA: "Expirada",
}

_ID_MAXIMO = 2_147_483_647
_PAGINA_MAXIMA = 10_000

_ACAO_STATUS = {
    ACAO_APROVAR: STATUS_TROCA_APROVADA,
    ACAO_REJEITAR: STATUS_TROCA_REJEITADA,
}
_ROTULO_ACAO = {ACAO_APROVAR: "aprovar", ACAO_REJEITAR: "rejeitar"}


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------


def _id_do_autor(message_or_call):
    from_user = getattr(message_or_call, "from_user", None)
    if from_user is not None:
        return getattr(from_user, "id", None)
    chat = getattr(message_or_call, "chat", None)
    return getattr(chat, "id", None)


def _responder(call, texto=None, alerta=False):
    try:
        bot.answer_callback_query(call.id, text=texto, show_alert=alerta)
    except Exception:
        logger.debug("TROCAS - falha ao responder callback", exc_info=True)


def _render(call, texto, markup):
    chat_id, msg_id = menu_principal.chat_e_message(call)
    if chat_id is None:
        return
    try:
        if msg_id is not None:
            bot.edit_message_text(texto, chat_id, msg_id, reply_markup=markup)
        else:
            bot.send_message(chat_id, texto, reply_markup=markup)
    except Exception as erro:
        if "message is not modified" in str(erro).lower():
            return
        logger.warning("TROCAS - falha ao exibir tela", exc_info=True)


def _e_admin(message_or_call):
    try:
        return (
            permissoes.obter_papel(_id_do_autor(message_or_call))
            == permissoes.PAPEL_ADMIN
        )
    except Exception:
        logger.warning("TROCAS - falha ao verificar admin", exc_info=True)
        return False


def _usuario_do_callback(call):
    """Resolve ``(telegram_id, usuario_id, dto, erro)`` revalidando o acesso."""
    telegram_id, _papel, dto, erro = menu_principal.usuario_autorizado(call)
    if erro:
        return None, None, None, erro
    if dto is None:
        return telegram_id, None, None, TEXTO_SEM_CONTA
    return telegram_id, dto.id, dto, None


def _expirar_vencidas():
    """Marca como ``expirada`` toda pendente fora do prazo configurado.

    Chamada antes de qualquer decisão ou nova solicitação para que um pedido
    vencido não possa ser aprovado (nem bloqueie um novo pedido) só porque a
    varredura ainda não rodou. NUNCA aprova: apenas muda o estado e preserva o
    histórico. Falha de banco não interrompe o fluxo (a decisão em si continua
    protegida pelos estados terminais do repositório).
    """
    try:
        return RepositorioTrocas().expirar_vencidas(
            getattr(config, "TROCAS_PRAZO_HORAS", None)
        )
    except Exception:
        logger.warning("TROCAS - falha ao expirar vencidas", exc_info=True)
        return 0


def _inteiro(valor, minimo, maximo):
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        return None
    if numero < minimo or numero > maximo:
        return None
    return numero


def _tipo_do_favorito(usuario_id, ticker):
    """Retorna ``(ativo_id, tipo)`` se ``ticker`` for favorito do usuário."""
    resolvido = RepositorioFavoritos().resolver_ativo(ticker)
    if resolvido is None:
        return None, None
    ativo_id, _ticker, tipo = resolvido
    if not RepositorioFavoritos().esta_acompanhado(usuario_id, ativo_id):
        return None, None
    return ativo_id, tipo


def _normalizar_tipo(tipo):
    """Normaliza o tipo vindo do DTO (``FII``/``ACAO``) ou do catálogo (``fii``)."""
    return str(tipo or "").strip().lower()


def _rotulo_filtro(tipo):
    return (
        "favoritos_fiis"
        if _normalizar_tipo(tipo) == "fii"
        else "favoritos_acoes"
    )


def _rotulo_tipo(tipo):
    return "FIIs" if _normalizar_tipo(tipo) == "fii" else "Ações"


# ---------------------------------------------------------------------------
# Tela do usuário: escolher destino
# ---------------------------------------------------------------------------


def _markup_escolha(saida, tipo, disponiveis, pagina, total_paginas):
    markup = InlineKeyboardMarkup(row_width=3)
    fatia = disponiveis[
        pagina * TAMANHO_PAGINA : pagina * TAMANHO_PAGINA + TAMANHO_PAGINA
    ]
    if fatia:
        markup.add(
            *[
                InlineKeyboardButton(
                    ticker, callback_data=f"{PREFIXO_USUARIO}sel_{saida}_{ticker}"
                )
                for ticker in fatia
            ]
        )
    navegacao = []
    if pagina > 0:
        navegacao.append(
            InlineKeyboardButton(
                "⬅️", callback_data=f"{PREFIXO_USUARIO}ini_{saida}_{pagina - 1}"
            )
        )
    if pagina < total_paginas - 1:
        navegacao.append(
            InlineKeyboardButton(
                "➡️", callback_data=f"{PREFIXO_USUARIO}ini_{saida}_{pagina + 1}"
            )
        )
    if navegacao:
        markup.row(*navegacao)
    markup.row(
        InlineKeyboardButton("🔙 Voltar aos favoritos", callback_data=_rotulo_filtro(tipo))
    )
    return markup


def _iniciar_troca(call, saida, pagina):
    telegram_id, usuario_id, _dto, erro = _usuario_do_callback(call)
    if erro:
        _responder(call, erro or TEXTO_ACESSO_NEGADO)
        return

    try:
        ativo_id, tipo = _tipo_do_favorito(usuario_id, saida)
    except Exception:
        logger.warning("TROCAS - falha ao validar favorito", exc_info=True)
        _responder(call, TEXTO_ERRO_BANCO)
        return
    if ativo_id is None:
        _responder(call, "❌ Este ativo não está entre os seus favoritos.")
        return

    _expirar_vencidas()
    try:
        pendente = RepositorioTrocas().pendente_do_usuario(usuario_id)
    except Exception:
        logger.warning("TROCAS - falha ao consultar pendente", exc_info=True)
        _responder(call, TEXTO_ERRO_BANCO)
        return

    if pendente is not None:
        texto = (
            "⏳ Você já possui uma solicitação de troca pendente:\n\n"
            f"• Trocar {pendente.ticker_saida} por {pendente.ticker_entrada}\n"
            f"• Situação: {_ROTULO_STATUS.get(pendente.status, pendente.status)}\n\n"
            "Aguarde a decisão do administrador."
        )
        markup = InlineKeyboardMarkup().add(
            InlineKeyboardButton(
                "🔙 Voltar aos favoritos", callback_data=_rotulo_filtro(pendente.tipo)
            )
        )
        _responder(call)
        _render(call, texto, markup)
        return

    try:
        disponiveis = RepositorioFavoritos().listar_disponiveis(usuario_id, tipo)
    except Exception:
        logger.warning("TROCAS - falha ao listar disponiveis", exc_info=True)
        _responder(call, TEXTO_ERRO_BANCO)
        return

    total = len(disponiveis)
    total_paginas = max(1, (total + TAMANHO_PAGINA - 1) // TAMANHO_PAGINA)
    pagina = max(0, min(pagina, total_paginas - 1))

    if disponiveis:
        linhas = [
            f"🔁 Trocar {saida}",
            "",
            f"Escolha o ativo que vai substituir {saida} "
            f"({_rotulo_tipo(tipo)}).",
            f"Página {pagina + 1}/{total_paginas}.",
        ]
    else:
        linhas = [
            f"🔁 Trocar {saida}",
            "",
            "📭 Nenhum outro ativo deste tipo disponível para troca no momento.",
        ]
    _responder(call)
    _render(
        call,
        "\n".join(linhas),
        _markup_escolha(saida, tipo, disponiveis, pagina, total_paginas),
    )


def _abrir_confirmacao(call, saida, entrada):
    _telegram_id, usuario_id, _dto, erro = _usuario_do_callback(call)
    if erro:
        _responder(call, erro or TEXTO_ACESSO_NEGADO)
        return

    try:
        saida_id, tipo_saida = _tipo_do_favorito(usuario_id, saida)
        resolvido_entrada = RepositorioFavoritos().resolver_ativo(entrada)
    except Exception:
        logger.warning("TROCAS - falha ao validar troca", exc_info=True)
        _responder(call, TEXTO_ERRO_BANCO)
        return

    if saida_id is None or resolvido_entrada is None:
        _responder(call, TEXTO_INVALIDO)
        return
    entrada_id, _ticker, tipo_entrada = resolvido_entrada
    if tipo_saida != tipo_entrada:
        _responder(call, "❌ Os ativos precisam ser do mesmo tipo.")
        return

    texto = (
        "🔁 Confirmar solicitação de troca\n\n"
        f"Deixar de acompanhar: {saida}\n"
        f"Passar a acompanhar: {entrada}\n\n"
        "A troca só será aplicada após a aprovação do administrador."
    )
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton(
            "✅ Solicitar troca",
            callback_data=f"{PREFIXO_USUARIO}conf_{saida}_{entrada}",
        )
    )
    markup.add(
        InlineKeyboardButton("❌ Cancelar", callback_data=_rotulo_filtro(tipo_saida))
    )
    _responder(call)
    _render(call, texto, markup)


def _criar_solicitacao(call, saida, entrada):
    _telegram_id, usuario_id, _dto, erro = _usuario_do_callback(call)
    if erro:
        _responder(call, erro or TEXTO_ACESSO_NEGADO)
        return

    try:
        saida_id, tipo_saida = _tipo_do_favorito(usuario_id, saida)
        resolvido_entrada = RepositorioFavoritos().resolver_ativo(entrada)
    except Exception:
        logger.warning("TROCAS - falha ao validar troca", exc_info=True)
        _responder(call, TEXTO_ERRO_BANCO)
        return

    if saida_id is None or resolvido_entrada is None:
        _responder(call, TEXTO_INVALIDO)
        return
    entrada_id, _ticker, tipo_entrada = resolvido_entrada
    if tipo_saida != tipo_entrada:
        _responder(call, "❌ Os ativos precisam ser do mesmo tipo.")
        return

    _expirar_vencidas()
    try:
        troca, criado = RepositorioTrocas().criar(usuario_id, saida_id, entrada_id)
    except TrocaInvalidaError as exc:
        _responder(call, f"❌ {exc}")
        return
    except Exception:
        logger.warning("TROCAS - falha ao criar solicitacao", exc_info=True)
        _responder(call, TEXTO_ERRO_BANCO)
        return

    if criado:
        _notificar_admin_nova(troca)
        texto = (
            "✅ Solicitação de troca enviada!\n\n"
            f"Deixar de acompanhar: {troca.ticker_saida}\n"
            f"Passar a acompanhar: {troca.ticker_entrada}\n\n"
            "Você será avisado quando o administrador decidir."
        )
    else:
        texto = (
            "ℹ️ Você já possui uma solicitação de troca pendente. "
            "Aguarde a decisão do administrador."
        )
    markup = InlineKeyboardMarkup().add(
        InlineKeyboardButton("🔙 Voltar aos favoritos", callback_data=_rotulo_filtro(tipo_saida))
    )
    _responder(call, "Solicitação registrada." if criado else None)
    _render(call, texto, markup)


# ---------------------------------------------------------------------------
# Telas administrativas
# ---------------------------------------------------------------------------


def _contagens_trocas():
    repositorio = RepositorioTrocas()
    return {
        status: repositorio.contar_por_status(status) for status in AREAS_TROCA
    }


def _texto_admin_home(contagens):
    linhas = ["🔁 SOLICITAÇÕES DE TROCA", "Gestão de trocas de favoritos.", ""]
    for status, (_chave, rotulo) in AREAS_TROCA.items():
        linhas.append(f"• {rotulo}: {contagens[status]}")
    linhas += ["", "Selecione uma área para gerenciar:"]
    return "\n".join(linhas)


def _markup_admin_home(contagens):
    markup = InlineKeyboardMarkup(row_width=1)
    for status, (chave, rotulo) in AREAS_TROCA.items():
        markup.add(
            InlineKeyboardButton(
                f"{rotulo} ({contagens[status]})",
                callback_data=f"{PREFIXO_ADMIN}area_{chave}_0",
            )
        )
    markup.add(InlineKeyboardButton("🔙 Central de Controles", callback_data="adm_home"))
    return markup


def _mostrar_admin_home(call):
    try:
        RepositorioTrocas().expirar_vencidas(getattr(config, "TROCAS_PRAZO_HORAS", None))
        contagens = _contagens_trocas()
    except Exception:
        logger.warning("TROCAS - falha ao montar home admin", exc_info=True)
        _render(call, TEXTO_ERRO_BANCO, InlineKeyboardMarkup())
        return
    _render(call, _texto_admin_home(contagens), _markup_admin_home(contagens))


def _rotulo_troca(dto):
    base = f"#{dto.id}: {dto.ticker_saida} → {dto.ticker_entrada}"
    return base[:60]


def _mostrar_admin_area(call, status, pagina):
    if status not in AREAS_TROCA:
        _mostrar_admin_home(call)
        return TEXTO_INVALIDO
    chave = AREAS_TROCA[status][0]
    try:
        RepositorioTrocas().expirar_vencidas(getattr(config, "TROCAS_PRAZO_HORAS", None))
        repositorio = RepositorioTrocas()
        total = repositorio.contar_por_status(status)
        total_paginas = max(1, (total + TAMANHO_PAGINA - 1) // TAMANHO_PAGINA)
        pagina = max(0, min(pagina, total_paginas - 1))
        trocas = repositorio.listar_por_status(
            status, limite=TAMANHO_PAGINA, deslocamento=pagina * TAMANHO_PAGINA
        )
    except Exception:
        logger.warning("TROCAS - falha ao listar area admin", exc_info=True)
        return TEXTO_ERRO_BANCO

    rotulo = AREAS_TROCA[status][1]
    markup = InlineKeyboardMarkup(row_width=1)
    if trocas:
        for dto in trocas:
            markup.add(
                InlineKeyboardButton(
                    _rotulo_troca(dto),
                    callback_data=f"{PREFIXO_ADMIN}ver_{dto.id}_{chave}_{pagina}",
                )
            )
    navegacao = []
    if pagina > 0:
        navegacao.append(
            InlineKeyboardButton(
                "⬅️ Anterior", callback_data=f"{PREFIXO_ADMIN}area_{chave}_{pagina - 1}"
            )
        )
    if pagina < total_paginas - 1:
        navegacao.append(
            InlineKeyboardButton(
                "Próxima ➡️", callback_data=f"{PREFIXO_ADMIN}area_{chave}_{pagina + 1}"
            )
        )
    if navegacao:
        markup.row(*navegacao)
    markup.add(
        InlineKeyboardButton("🔙 Solicitações de troca", callback_data=f"{PREFIXO_ADMIN}home")
    )

    linhas = [f"🔁 {rotulo}", ""]
    if not trocas:
        linhas.append("Nenhuma solicitação nesta área.")
    else:
        linhas.append(f"Página {pagina + 1}/{total_paginas} — {total} registro(s).")
        linhas.append("Toque em uma solicitação para ver os detalhes:")
    _render(call, "\n".join(linhas), markup)
    return None


def _texto_admin_troca(dto, usuario):
    nome = usuario.nome if usuario is not None else "Usuário desconhecido"
    linhas = [
        "🔁 SOLICITAÇÃO DE TROCA",
        f"#{dto.id}",
        "",
        f"Solicitante: {nome}",
        f"Categoria: {_rotulo_tipo(dto.tipo)}",
        f"Deixar de acompanhar: {dto.ticker_saida or '—'}",
        f"Passar a acompanhar: {dto.ticker_entrada or '—'}",
        f"Situação: {_ROTULO_STATUS.get(dto.status, dto.status)}",
        f"Criada em: {_data(dto.criado_em)}",
    ]
    if dto.decidido_em is not None:
        linhas.append(f"Decidida em: {_data(dto.decidido_em)}")
    if dto.esta_pendente():
        linhas += ["", "Ações disponíveis:"]
    return "\n".join(linhas)


def _data(valor):
    try:
        return valor.strftime("%d/%m/%Y %H:%M")
    except (AttributeError, ValueError):
        return "Não informada"


def _mostrar_admin_troca(call, troca_id, status, pagina):
    chave = AREAS_TROCA.get(status, (None, None))[0]
    if chave is None:
        _mostrar_admin_home(call)
        return TEXTO_INVALIDO
    try:
        dto = RepositorioTrocas().obter(troca_id)
        usuario = (
            RepositorioUsuarios().obter_por_id(dto.usuario_id) if dto is not None else None
        )
    except Exception:
        logger.warning("TROCAS - falha ao carregar troca", exc_info=True)
        return TEXTO_ERRO_BANCO
    if dto is None:
        return _mostrar_admin_area(call, status, pagina) or TEXTO_INVALIDO

    markup = InlineKeyboardMarkup(row_width=1)
    if dto.esta_pendente():
        markup.add(
            InlineKeyboardButton(
                "✅ Aprovar troca",
                callback_data=f"{PREFIXO_ADMIN}conf_{ACAO_APROVAR}_{dto.id}_{chave}_{pagina}",
            )
        )
        markup.add(
            InlineKeyboardButton(
                "🚫 Rejeitar troca",
                callback_data=f"{PREFIXO_ADMIN}conf_{ACAO_REJEITAR}_{dto.id}_{chave}_{pagina}",
            )
        )
    markup.add(
        InlineKeyboardButton(
            "🔙 Voltar à lista", callback_data=f"{PREFIXO_ADMIN}area_{chave}_{pagina}"
        )
    )
    _render(call, _texto_admin_troca(dto, usuario), markup)
    return None


def _confirmar_admin(call, acao, troca_id, status, pagina):
    chave = AREAS_TROCA.get(status, (None, None))[0]
    if chave is None or acao not in _ACAO_STATUS:
        _mostrar_admin_home(call)
        return TEXTO_INVALIDO
    try:
        dto = RepositorioTrocas().obter(troca_id)
    except Exception:
        logger.warning("TROCAS - falha ao carregar troca", exc_info=True)
        return TEXTO_ERRO_BANCO
    if dto is None:
        return _mostrar_admin_area(call, status, pagina) or TEXTO_INVALIDO
    if not dto.esta_pendente():
        _mostrar_admin_troca(call, troca_id, status, pagina)
        if dto.status == STATUS_TROCA_EXPIRADA:
            return "⌛ Esta solicitação expirou e não pode mais ser decidida."
        return "ℹ️ Esta solicitação já foi decidida."

    rotulo = _ROTULO_ACAO[acao]
    texto = (
        "⚠️ CONFIRMAÇÃO\n\n"
        f"Deseja realmente {rotulo} a troca:\n\n"
        f"Deixar de acompanhar: {dto.ticker_saida}\n"
        f"Passar a acompanhar: {dto.ticker_entrada}\n\n"
        "Esta ação será registrada na auditoria."
    )
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton(
            f"✅ Sim, {rotulo}",
            callback_data=(
                f"{PREFIXO_ADMIN}do_{acao}_{dto.id}_{chave}_{pagina}"
            ),
        )
    )
    markup.add(
        InlineKeyboardButton(
            "❌ Cancelar",
            callback_data=f"{PREFIXO_ADMIN}ver_{dto.id}_{chave}_{pagina}",
        )
    )
    _render(call, texto, markup)
    return None


def _executar_admin(call, acao, troca_id, status, pagina):
    chave = AREAS_TROCA.get(status, (None, None))[0]
    if chave is None or acao not in _ACAO_STATUS:
        _mostrar_admin_home(call)
        return TEXTO_INVALIDO
    autor_id = _id_do_autor(call)
    repositorio = RepositorioTrocas()
    # Pedido vencido não pode mais ser decidido: expira antes de aprovar/rejeitar.
    _expirar_vencidas()
    try:
        if acao == ACAO_APROVAR:
            dto, aplicado = repositorio.aplicar_aprovacao(troca_id, autor_id=autor_id)
        else:
            dto, aplicado = repositorio.decidir(
                troca_id,
                STATUS_TROCA_REJEITADA,
                autor_id=autor_id,
                origens_permitidas={STATUS_TROCA_PENDENTE},
            )
    except TrocaInvalidaError as exc:
        # Pedido desatualizado (ex.: ativo de saida deixou de ser favorito).
        # Nada foi alterado; a solicitacao continua pendente para nova decisao.
        logger.info("TROCAS - decisao recusada: %s", exc)
        cadastro.registrar_auditoria(
            autor_id, troca_id, f"troca_{acao}", "estado_invalido"
        )
        _mostrar_admin_troca(call, troca_id, status, pagina)
        return f"⚠️ Não foi possível aplicar: {exc}."
    except Exception:
        logger.warning("TROCAS - falha ao decidir", exc_info=True)
        cadastro.registrar_auditoria(autor_id, troca_id, f"troca_{acao}", "falha_banco")
        return TEXTO_ERRO_BANCO

    if dto is None:
        cadastro.registrar_auditoria(autor_id, troca_id, f"troca_{acao}", "inexistente")
        return _mostrar_admin_area(call, status, pagina) or "⚠️ Solicitação não encontrada."

    if not aplicado:
        cadastro.registrar_auditoria(
            autor_id, dto.id, f"troca_{acao}", "estado_invalido"
        )
        _mostrar_admin_troca(call, troca_id, status, pagina)
        return "ℹ️ Esta solicitação já foi decidida."

    cadastro.registrar_auditoria(autor_id, dto.id, f"troca_{acao}", "aplicada")
    _notificar_solicitante(dto, aprovada=(acao == ACAO_APROVAR))
    return _mostrar_admin_area(call, status, pagina) or (
        "✅ Troca aprovada." if acao == ACAO_APROVAR else "🚫 Troca rejeitada."
    )


# ---------------------------------------------------------------------------
# Notificações
# ---------------------------------------------------------------------------


def _notificar_admin_nova(dto):
    destino = cadastro._chat_do_administrador()
    if destino is None:
        return
    try:
        usuario = RepositorioUsuarios().obter_por_id(dto.usuario_id)
    except Exception:
        logger.warning("TROCAS - falha ao resolver solicitante", exc_info=True)
        usuario = None
    nome = (
        usuario.nome
        if usuario is not None and getattr(usuario, "nome", None)
        else "Usuário desconhecido"
    )
    texto = (
        "🔔 Nova solicitação de troca de favorito\n\n"
        f"Solicitante: {nome}\n"
        f"Categoria: {_rotulo_tipo(dto.tipo)}\n"
        f"Ativo atual: {dto.ticker_saida}\n"
        f"Ativo solicitado: {dto.ticker_entrada}\n"
        f"Data: {_data(dto.criado_em)}"
    )
    markup = InlineKeyboardMarkup().add(
        InlineKeyboardButton(
            "🔁 Abrir solicitações de troca",
            callback_data=f"{PREFIXO_ADMIN}home",
        )
    )
    try:
        cadastro.enviar_texto(destino, texto, reply_markup=markup)
    except Exception:
        logger.warning("TROCAS - falha ao notificar admin", exc_info=True)


def _notificar_solicitante(dto, aprovada):
    usuario = RepositorioUsuarios().obter_por_id(dto.usuario_id)
    if usuario is None:
        return
    destino = usuario.telegram_chat_id or usuario.telegram_user_id
    if destino is None:
        return
    if aprovada:
        texto = (
            "✅ Sua solicitação de troca foi aprovada!\n\n"
            f"Você deixou de acompanhar {dto.ticker_saida} e agora acompanha "
            f"{dto.ticker_entrada}."
        )
    else:
        texto = (
            "🚫 Sua solicitação de troca foi rejeitada.\n\n"
            f"A troca de {dto.ticker_saida} por {dto.ticker_entrada} não foi "
            "aplicada. Seus favoritos permanecem inalterados."
        )
    try:
        cadastro.enviar_texto(destino, texto)
    except Exception:
        logger.warning("TROCAS - falha ao notificar solicitante", exc_info=True)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


@bot.callback_query_handler(
    func=lambda call: bool(call.data)
    and call.data.startswith(PREFIXO_ADMIN)
)
def tratar_callback_admin(call):
    if not _e_admin(call):
        cadastro.registrar_auditoria(
            _id_do_autor(call), None, "troca_admin_negada", "autor_nao_admin"
        )
        _responder(call, TEXTO_ACESSO_NEGADO, alerta=True)
        return

    partes = (call.data or "").split("_")
    acao = partes[1] if len(partes) > 1 else ""
    try:
        if acao == "home":
            _mostrar_admin_home(call)
            toast = None
        elif acao == "area":
            if len(partes) != 4:
                toast = TEXTO_INVALIDO
            else:
                status = _AREA_POR_CHAVE.get(partes[2])
                pagina = _inteiro(partes[3], 0, _PAGINA_MAXIMA)
                if status is None or pagina is None:
                    toast = TEXTO_INVALIDO
                else:
                    toast = _mostrar_admin_area(call, status, pagina)
        elif acao == "ver":
            toast = _tratar_admin_ver(call, partes)
        elif acao == "conf":
            toast = _tratar_admin_conf(call, partes)
        elif acao == "do":
            toast = _tratar_admin_do(call, partes)
        else:
            _mostrar_admin_home(call)
            toast = TEXTO_INVALIDO
    except Exception:
        logger.warning("TROCAS - falha ao processar callback admin", exc_info=True)
        toast = TEXTO_ERRO_BANCO
    _responder(call, toast)


def _tratar_admin_ver(call, partes):
    # trocaadm_ver_<id>_<chave>_<pagina>
    if len(partes) != 5:
        return TEXTO_INVALIDO
    troca_id = _inteiro(partes[2], 1, _ID_MAXIMO)
    status = _AREA_POR_CHAVE.get(partes[3])
    pagina = _inteiro(partes[4], 0, _PAGINA_MAXIMA)
    if troca_id is None or status is None or pagina is None:
        return TEXTO_INVALIDO
    return _mostrar_admin_troca(call, troca_id, status, pagina)


def _tratar_admin_conf(call, partes):
    # trocaadm_conf_<acao>_<id>_<chave>_<pagina>
    if len(partes) != 6:
        return TEXTO_INVALIDO
    acao = partes[2]
    troca_id = _inteiro(partes[3], 1, _ID_MAXIMO)
    status = _AREA_POR_CHAVE.get(partes[4])
    pagina = _inteiro(partes[5], 0, _PAGINA_MAXIMA)
    if acao not in _ACAO_STATUS or troca_id is None or status is None or pagina is None:
        return TEXTO_INVALIDO
    return _confirmar_admin(call, acao, troca_id, status, pagina)


def _tratar_admin_do(call, partes):
    # trocaadm_do_<acao>_<id>_<chave>_<pagina>
    if len(partes) != 6:
        return TEXTO_INVALIDO
    acao = partes[2]
    troca_id = _inteiro(partes[3], 1, _ID_MAXIMO)
    status = _AREA_POR_CHAVE.get(partes[4])
    pagina = _inteiro(partes[5], 0, _PAGINA_MAXIMA)
    if acao not in _ACAO_STATUS or troca_id is None or status is None or pagina is None:
        return TEXTO_INVALIDO
    return _executar_admin(call, acao, troca_id, status, pagina)


@bot.callback_query_handler(
    func=lambda call: bool(call.data)
    and call.data.startswith(PREFIXO_USUARIO)
)
def tratar_callback_usuario(call):
    partes = (call.data or "").split("_")
    acao = partes[1] if len(partes) > 1 else ""
    try:
        if acao == "ini" and len(partes) == 4:
            pagina = _inteiro(partes[3], 0, _PAGINA_MAXIMA)
            if pagina is None:
                _responder(call, TEXTO_INVALIDO)
                return
            _iniciar_troca(call, partes[2].upper(), pagina)
        elif acao == "sel" and len(partes) == 4:
            _abrir_confirmacao(call, partes[2].upper(), partes[3].upper())
        elif acao == "conf" and len(partes) == 4:
            _criar_solicitacao(call, partes[2].upper(), partes[3].upper())
        else:
            _responder(call, TEXTO_INVALIDO)
    except Exception:
        logger.warning("TROCAS - falha ao processar callback usuario", exc_info=True)
        _responder(call, TEXTO_ERRO_BANCO)
