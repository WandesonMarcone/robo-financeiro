"""Painel inicial personalizado do Robô Financeiro.

Substitui o menu genérico de ``/start`` e ``/menu`` por um painel que:

* saúda o usuário pelo nome completo cadastrado (ou pelo nome de exibição do
  Telegram, ou por um fallback seguro);
* lista **os favoritos individuais do próprio usuário** (FIIs e Ações),
  reaproveitando ``pipeline_dados.repositorio_favoritos`` (nenhuma lista global
  fixa é usada);
* oferece atalhos apenas para funcionalidades que realmente existem (novos
  documentos, minha carteira, alertas, gerenciar favoritos, consultar
  indicadores, minha conta, ajuda e, para o admin, a Central de Controles).

Regras de projeto respeitadas:

* nenhuma tabela/schema é criado ou alterado; o banco de produção não é tocado;
* a identidade vem sempre do Telegram ID autenticado (nunca de parâmetros do
  cliente);
* falhas de banco/serviços são tratadas de forma segura: o painel cai no menu
  básico em vez de propagar exceção, e os favoritos simplesmente não aparecem;
* o botão administrativo só é anexado quando o papel resolvido é ``admin`` e o
  callback ainda é revalidado por ``bot.permissoes``/``bot.central_controles``;
* os callbacks do painel editam a mensagem existente (evitando mensagens
  duplicadas) e revalidam a autorização/conta antes de exibir qualquer dado.

Este módulo é deliberadamente livre de estado do bot no import: o objeto ``bot``
é resolvido de forma preguiçosa (``_bot``) apenas quando uma mensagem precisa ser
enviada/editada. Assim, importar o módulo (inclusive por ``bot.cadastro``) não
captura uma instância de bot que possa ficar desatualizada entre reinícios de
testes, e o registro dos callbacks do painel fica em ``bot.callbacks_menus``.

Limitações conhecidas (informadas ao usuário, não inventadas):

* os alertas listam apenas eventos já persistidos em ``alertas_eventos`` para
  os favoritos do próprio usuário; ausência de evento não vira zero inventado;
* a fila ``notificacoes`` e as flags de ``preferencias_usuarios`` não são
  usadas (vocabulario ainda desconhecido);
* os ativos aparecem pelo ticker, pois a tabela ``ativos`` não guarda o nome
  de mercado do fundo/empresa.
"""

import logging

from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import permissoes
from bot.telegram_utils import (
    TEXTO_ACESSO_NEGADO,
    TEXTO_MENU_INICIAL,
    construir_menu_inicial,
    escapar_markdown,
    montar_painel_inicial,
    nome_de_exibicao_do_telegram,
)
from pipeline_dados.repositorio_alertas import RepositorioAlertas
from pipeline_dados.repositorio_favoritos import RepositorioFavoritos
from pipeline_dados.repositorio_usuarios import RepositorioUsuarios

logger = logging.getLogger("robo.menu")

TEXTO_SEM_CONTA = (
    "🔒 Este recurso exige uma conta aprovada. "
    "Envie /start para iniciar o cadastro."
)
TEXTO_ERRO_BANCO = "⚠️ Não foi possível acessar seus dados agora. Tente novamente."
TEXTO_ATIVOS_VAZIOS = (
    "📭 Você ainda não acompanha nenhum ativo.\n"
    "Use ⭐ Gerenciar favoritos para escolher seus FIIs e ações."
)
TEXTO_ALERTAS_VAZIOS = (
    "🔔 *Alertas*\n\n"
    "Nenhum evento encontrado para os seus favoritos."
)
TEXTO_GERENCIAR_FAVORITOS = (
    "⭐ *Gerenciar favoritos*\n\n"
    "Escolha o tipo de ativo para adicionar, consultar ou remover dos seus "
    "favoritos:"
)
TEXTO_CONSULTAR_INDICADORES = (
    "📈 *Consultar indicadores*\n\n"
    "Escolha o módulo de análise. Navegue por setor até o painel de indicadores "
    "do ativo:"
)


def _bot():
    """Resolve o bot atual de forma preguiçosa (evita capturar instância velha)."""
    from bot.loader import bot

    return bot


# ---------------------------------------------------------------------------
# Resolução de identidade / acesso
# ---------------------------------------------------------------------------


def _resolver_papel(telegram_id):
    try:
        return permissoes.obter_papel(telegram_id)
    except Exception:
        logger.warning("MENU - falha ao resolver papel", exc_info=True)
        return None


def _resolver_cadastro(telegram_id):
    try:
        return RepositorioUsuarios().obter_por_telegram_id(telegram_id)
    except Exception:
        logger.warning("MENU - falha ao consultar cadastro", exc_info=True)
        return None


def _resolver_nome(dto, from_user):
    if dto is not None and getattr(dto, "nome", None):
        nome = str(dto.nome).strip()
        if nome:
            return nome
    return nome_de_exibicao_do_telegram(from_user)


def _resolver_favoritos(usuario_id, papel, dto):
    """Retorna ``(favoritos_fii, favoritos_acao)`` do usuário (ou vazio).

    Só consulta quando existe conta persistente (``usuario_id``) e o acesso é
    permitido: admin autorizado pela config ou conta aprovada e ativa. Qualquer
    falha resulta em listas vazias (falha segura), sem quebrar o menu.
    """
    if usuario_id is None:
        return [], []
    permitido = papel == permissoes.PAPEL_ADMIN or (
        dto is not None and dto.esta_aprovado() and dto.ativo
    )
    if not permitido:
        return [], []
    try:
        repositorio = RepositorioFavoritos()
        return repositorio.listar(usuario_id, "fii"), repositorio.listar(
            usuario_id, "acao"
        )
    except Exception:
        logger.warning("MENU - falha ao carregar favoritos", exc_info=True)
        return [], []


def usuario_autorizado(message_or_call):
    """Resolve ``(telegram_id, papel, dto, erro)`` revalidando o acesso.

    Nunca aceita identidade vinda de parâmetros do cliente: o Telegram ID é
    sempre extraído do próprio update. Em falha ou negativa, ``erro`` traz o
    texto a responder ao usuário e os demais campos ficam ``None``.
    """
    autor = getattr(message_or_call, "from_user", None)
    telegram_id = getattr(autor, "id", None)
    if telegram_id is None:
        return None, None, None, TEXTO_ACESSO_NEGADO

    papel = _resolver_papel(telegram_id)
    if papel is None:
        return None, None, None, TEXTO_ACESSO_NEGADO

    dto = _resolver_cadastro(telegram_id)
    if papel == permissoes.PAPEL_ADMIN:
        return telegram_id, papel, dto, None
    if dto is None:
        return None, None, None, TEXTO_SEM_CONTA
    if not (dto.esta_aprovado() and dto.ativo):
        return None, None, None, TEXTO_SEM_CONTA
    return telegram_id, papel, dto, None


# ---------------------------------------------------------------------------
# Envio / edição do painel
# ---------------------------------------------------------------------------


def montar_painel(telegram_id, from_user=None):
    """Resolve o painel personalizado ``(texto, markup)`` para o usuário."""
    papel = _resolver_papel(telegram_id)
    incluir_admin = papel == permissoes.PAPEL_ADMIN
    dto = _resolver_cadastro(telegram_id)
    nome = _resolver_nome(dto, from_user)
    usuario_id = dto.id if dto is not None else None
    favoritos_fii, favoritos_acao = _resolver_favoritos(usuario_id, papel, dto)
    return montar_painel_inicial(
        nome,
        favoritos_fii=favoritos_fii,
        favoritos_acao=favoritos_acao,
        incluir_admin=incluir_admin,
    )


def _markup_basico(telegram_id):
    incluir_admin = _resolver_papel(telegram_id) == permissoes.PAPEL_ADMIN
    return TEXTO_MENU_INICIAL, construir_menu_inicial(incluir_admin=incluir_admin)


def enviar_painel(chat_id, telegram_id, from_user=None):
    """Envia o painel personalizado; em falha, recorre ao menu básico."""
    if chat_id is None:
        return
    try:
        texto, markup = montar_painel(telegram_id, from_user)
    except Exception:
        logger.warning("MENU - falha ao montar painel", exc_info=True)
        texto, markup = _markup_basico(telegram_id)
    try:
        _bot().send_message(
            chat_id, texto, reply_markup=markup, parse_mode="Markdown"
        )
    except Exception:
        logger.warning("MENU - falha ao enviar painel", exc_info=True)


def editar_painel(chat_id, message_id, telegram_id, from_user=None):
    """Atualiza (edita) a mensagem atual com o painel personalizado.

    Evita mensagens duplicadas nos retornos por callback. Se a edição não for
    possível (ex.: conteúdo idêntico), nada é feito.
    """
    if chat_id is None or message_id is None:
        return
    try:
        texto, markup = montar_painel(telegram_id, from_user)
    except Exception:
        logger.warning("MENU - falha ao montar painel", exc_info=True)
        texto, markup = _markup_basico(telegram_id)
    editar_mensagem(chat_id, message_id, texto, markup)


def editar_mensagem(chat_id, message_id, texto, markup):
    try:
        _bot().edit_message_text(
            texto, chat_id, message_id, reply_markup=markup, parse_mode="Markdown"
        )
    except Exception as erro:
        if "message is not modified" in str(erro):
            return
        logger.warning("MENU - falha ao editar painel", exc_info=True)


# ---------------------------------------------------------------------------
# Helpers de callback (reutilizados pelos handlers em bot.callbacks_menus)
# ---------------------------------------------------------------------------


def chat_e_message(message_or_call):
    message = getattr(message_or_call, "message", None)
    if message is not None:
        chat = getattr(message, "chat", None)
        return (
            getattr(chat, "id", None) if chat is not None else None,
            getattr(message, "message_id", None),
        )
    chat = getattr(message_or_call, "chat", None)
    return (getattr(chat, "id", None) if chat is not None else None, None)


def responder_callback(call, texto=None):
    try:
        _bot().answer_callback_query(call.id, text=texto)
    except Exception:
        logger.debug("MENU - falha ao responder callback", exc_info=True)


def editar_callback(call, texto, markup):
    chat_id, message_id = chat_e_message(call)
    if chat_id is None:
        return
    if message_id is not None:
        editar_mensagem(chat_id, message_id, texto, markup)
    else:
        try:
            _bot().send_message(
                chat_id, texto, reply_markup=markup, parse_mode="Markdown"
            )
        except Exception:
            logger.warning("MENU - falha ao enviar tela", exc_info=True)


def markup_voltar(voltar="voltar_painel"):
    return InlineKeyboardMarkup().add(
        InlineKeyboardButton("🔙 Voltar ao painel", callback_data=voltar)
    )


# ---------------------------------------------------------------------------
# Montagem de telas
# ---------------------------------------------------------------------------


def texto_carteira(favoritos_fii, favoritos_acao):
    """Monta a tela da carteira com botões para cada ativo favoritado."""
    if not favoritos_fii and not favoritos_acao:
        return TEXTO_ATIVOS_VAZIOS, markup_voltar()

    markup = InlineKeyboardMarkup()
    linhas = ["📊 *Minha carteira*", ""]
    if favoritos_fii:
        linhas += ["🏢 *Fundos Imobiliários*"]
        linhas += [f"• {escapar_markdown(f.ticker)}" for f in favoritos_fii]
        linhas.append("")
    if favoritos_acao:
        linhas += ["📈 *Ações*"]
        linhas += [f"• {escapar_markdown(f.ticker)}" for f in favoritos_acao]
        linhas.append("")
    linhas.append("Toque em um ativo para abrir o painel de indicadores:")

    for favorito in list(favoritos_fii) + list(favoritos_acao):
        markup.row(
            InlineKeyboardButton(
                f"📊 {favorito.ticker}",
                callback_data=f"painel_{favorito.ticker}_{favorito.tipo}",
            )
        )
    markup.row(InlineKeyboardButton("🔙 Voltar ao painel", callback_data="voltar_painel"))
    return "\n".join(linhas), markup


def texto_minha_conta(telegram_id, papel, dto):
    """Monta a tela de conta usando os dados já existentes no cadastro."""
    linhas = ["⚙️ *Minha conta*", ""]
    linhas.append(f"👤 Telegram ID: `{escapar_markdown(telegram_id)}`")
    if dto is None:
        linhas += [
            "",
            "ℹ️ Não há cadastro persistente vinculado a este Telegram ID. "
            "Seu acesso é concedido pela configuração do sistema.",
            f"🔑 Papel: {escapar_markdown(papel)}",
        ]
        return "\n".join(linhas)

    if dto.nome:
        linhas.append(f"📝 Nome: {escapar_markdown(dto.nome)}")
    if dto.email:
        linhas.append(f"📧 E-mail: {escapar_markdown(dto.email)}")
    linhas.append(f"🔑 Papel: {escapar_markdown(dto.papel or papel)}")
    linhas.append(f"📌 Status: {escapar_markdown(dto.status)}")
    return "\n".join(linhas)


def texto_novos_documentos(limite=10, tickers_permitidos=None):
    """Lista os últimos documentos capturados, reutilizando a base existente.

    ``tickers_permitidos``: ``None`` = visão ampla (administrador); um conjunto
    restringe a lista aos tickers informados (favoritos ativos do usuário
    comum). Conjunto vazio resulta em lista vazia, sem consultar o banco.
    """
    if tickers_permitidos is not None and not tickers_permitidos:
        return TEXTO_ATIVOS_VAZIOS
    try:
        from atualizador_documentos import SessionDB
        from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos
    except Exception:
        logger.warning("MENU - base de documentos indisponível", exc_info=True)
        return TEXTO_ERRO_BANCO

    session = None
    try:
        session = SessionDB()
        consulta = session.query(DocumentosQualitativos, Ativo).join(
            Ativo, DocumentosQualitativos.ativo_id == Ativo.id
        )
        if tickers_permitidos is not None:
            consulta = consulta.filter(Ativo.ticker.in_(sorted(tickers_permitidos)))
        ultimos = (
            consulta.order_by(DocumentosQualitativos.data_publicacao.desc())
            .limit(limite)
            .all()
        )
    except Exception:
        logger.warning("MENU - falha ao consultar documentos", exc_info=True)
        return TEXTO_ERRO_BANCO
    finally:
        if session is not None:
            session.close()

    if not ultimos:
        return "📄 *Novos documentos*\n\n📭 Nenhum documento encontrado no banco ainda."

    linhas = ["📄 *Novos documentos*", "", "Últimos relatórios capturados:"]
    for doc, ativo in ultimos:
        data = (
            doc.data_publicacao.strftime("%d/%m/%Y")
            if doc.data_publicacao
            else "Data N/A"
        )
        linhas.append("")
        linhas.append(
            f"🏢 *{escapar_markdown(ativo.ticker)}* — {escapar_markdown(data)}"
        )
        linhas.append(f"🏷️ {escapar_markdown(doc.tipo_documento)}")
    return "\n".join(linhas)


def _formatar_valor_alerta(valor):
    """Formata um valor persistido; ``None`` permanece ausente (nao vira zero)."""
    if valor is None:
        return None
    texto = format(valor, "f") if hasattr(valor, "as_tuple") else str(valor)
    if "." in texto:
        texto = texto.rstrip("0").rstrip(".")
    return texto or "0"


def texto_meus_alertas(usuario_id, limite=10):
    """Lista eventos persistidos dos favoritos do usuario.

    Sem favoritos, nao consulta ``alertas_eventos``. Falha de banco devolve
    texto seguro. Nenhum status de ``notificacoes`` e inventado.
    """
    try:
        favoritos = RepositorioFavoritos().listar(usuario_id)
    except Exception:
        logger.warning("MENU - falha ao carregar favoritos para alertas", exc_info=True)
        return TEXTO_ERRO_BANCO
    if not favoritos:
        return TEXTO_ATIVOS_VAZIOS
    ids = [favorito.ativo_id for favorito in favoritos]
    try:
        eventos = RepositorioAlertas().listar_por_ativos(ids, limite=limite)
    except Exception:
        logger.warning("MENU - falha ao consultar alertas", exc_info=True)
        return TEXTO_ERRO_BANCO
    if not eventos:
        return TEXTO_ALERTAS_VAZIOS

    linhas = ["🔔 *Alertas*", "", "Eventos recentes dos seus favoritos:"]
    for evento in eventos:
        data = (
            evento.data_evento.strftime("%d/%m/%Y %H:%M")
            if evento.data_evento
            else "Data N/A"
        )
        linhas.append("")
        linhas.append(
            f"🏢 *{escapar_markdown(evento.ticker)}* — {escapar_markdown(data)}"
        )
        linhas.append(
            f"🏷️ {escapar_markdown(evento.indicador)} · "
            f"{escapar_markdown(evento.regra)} · "
            f"{escapar_markdown(evento.severidade)}"
        )
        if evento.motivo:
            linhas.append(f"📝 {escapar_markdown(evento.motivo)}")
        atual = _formatar_valor_alerta(evento.valor_atual)
        anterior = _formatar_valor_alerta(evento.valor_anterior)
        if atual is not None or anterior is not None:
            partes = []
            if atual is not None:
                partes.append(f"atual {atual}")
            if anterior is not None:
                partes.append(f"anterior {anterior}")
            linhas.append(f"📌 {escapar_markdown(' · '.join(partes))}")
    return "\n".join(linhas)
