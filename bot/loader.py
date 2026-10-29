import logging
import os
import time

import telebot

import config
from bot import permissoes
from bot.telegram_utils import (
    NotificadorDeFalhas,
    TEXTO_ACESSO_NEGADO,
    chat_autorizado,
    descrever_update,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("robo.telegram")


def obter_token_obrigatorio():
    """Retorna o token do bot ou falha com um erro claro.

    O bot não inicia sem ``TELEGRAM_BOT_TOKEN``; não há token padrão nem
    configuração de produção embutida. A mensagem de erro nunca inclui o valor
    da credencial.
    """
    token = (config.TELEGRAM_BOT_TOKEN or "").strip()
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN ausente ou vazio. Defina a variavel de ambiente "
            "TELEGRAM_BOT_TOKEN antes de iniciar o bot (veja 'Configuracao Rapida' "
            "no README). Nenhum token padrao e fornecido."
        )
    return token


class BotAutorizado(telebot.TeleBot):
    """Bot que descarta atualizações de chats não autorizados e registra a execução.

    Além da allowlist de chats, cada update é submetido ao controle centralizado
    de permissões (``bot.permissoes``): o usuário é identificado pelo Telegram ID,
    seu papel é resolvido e a operação (comando ou callback) é liberada ou negada
    antes de qualquer handler produzir efeito. A execução é verificável pelos
    logs: cada update autorizado e o resultado final dos handlers são
    registrados; tentativas negadas também são registradas, sem expor tokens.
    """

    def _auditoria_chat(self, chat_id):
        """Retorna um identificador seguro para os logs de auditoria."""
        if chat_id is None:
            return "-"
        valor = str(chat_id)
        return f"***{valor[-4:]}" if len(valor) > 4 else "***"

    def _auditoria_conteudo_ativa(self, chat_id):
        """Libera texto completo apenas para o chat de auditoria configurado.

        O registro estrutural continua ativo para todos os chats. O conteúdo
        completo fica restrito ao chat definido em TELEGRAM_AUDITORIA_CHAT_ID
        (por padrão, o administrador) ou quando TELEGRAM_AUDITORIA_DETALHADA
        estiver explicitamente habilitado.
        """
        detalhada = str(
            os.environ.get("TELEGRAM_AUDITORIA_DETALHADA", "")
        ).strip().lower() in {"1", "true", "yes", "on"}
        chat_auditoria = (
            os.environ.get("TELEGRAM_AUDITORIA_CHAT_ID")
            or getattr(config, "TELEGRAM_ADMIN_ID", "")
        ).strip()
        return detalhada or (chat_id is not None and str(chat_id) == chat_auditoria)

    def _auditoria_saida(self, acao, executor, chat_id=None, texto=None, **dados):
        """Registra início, sucesso e falha de cada resposta enviada."""
        chat_log = self._auditoria_chat(chat_id)
        update = getattr(self, "_update_em_processamento", None)
        origem = descrever_update(update) if update is not None else "sem_update"
        conteudo = ""
        if texto is not None and self._auditoria_conteudo_ativa(chat_id):
            conteudo = f" texto={str(texto)!r}"
        inicio = time.perf_counter()
        logger.info(
            "TELEGRAM AUDITORIA - inicio acao=%s chat=%s origem=%s%s dados=%s",
            acao,
            chat_log,
            origem,
            conteudo,
            dados or "-",
        )
        try:
            resultado = executor()
        except Exception as erro:
            logger.exception(
                "TELEGRAM AUDITORIA - falha acao=%s chat=%s origem=%s "
                "duracao_ms=%.1f erro=%s",
                acao,
                chat_log,
                origem,
                (time.perf_counter() - inicio) * 1000,
                str(erro),
            )
            raise
        logger.info(
            "TELEGRAM AUDITORIA - sucesso acao=%s chat=%s origem=%s "
            "duracao_ms=%.1f resultado=%s",
            acao,
            chat_log,
            origem,
            (time.perf_counter() - inicio) * 1000,
            type(resultado).__name__,
        )
        return resultado

    def send_message(self, chat_id, text, *args, **kwargs):
        return self._auditoria_saida(
            "send_message",
            lambda: telebot.TeleBot.send_message(
                self, chat_id, text, *args, **kwargs
            ),
            chat_id,
            text,
            parse_mode=kwargs.get("parse_mode"),
        )

    def send_photo(self, chat_id, photo, *args, **kwargs):
        return self._auditoria_saida(
            "send_photo",
            lambda: telebot.TeleBot.send_photo(
                self, chat_id, photo, *args, **kwargs
            ),
            chat_id,
            kwargs.get("caption"),
            tipo_midia=type(photo).__name__,
        )

    def edit_message_text(self, text, chat_id=None, message_id=None, *args, **kwargs):
        return self._auditoria_saida(
            "edit_message_text",
            lambda: telebot.TeleBot.edit_message_text(
                self, text, chat_id, message_id, *args, **kwargs
            ),
            chat_id,
            text,
            message_id=message_id,
            parse_mode=kwargs.get("parse_mode"),
        )

    def edit_message_caption(
        self, caption, chat_id=None, message_id=None, *args, **kwargs
    ):
        return self._auditoria_saida(
            "edit_message_caption",
            lambda: telebot.TeleBot.edit_message_caption(
                self, caption, chat_id, message_id, *args, **kwargs
            ),
            chat_id,
            caption,
            message_id=message_id,
            parse_mode=kwargs.get("parse_mode"),
        )

    def edit_message_media(self, media, chat_id=None, message_id=None, *args, **kwargs):
        caption = getattr(media, "caption", None)
        return self._auditoria_saida(
            "edit_message_media",
            lambda: telebot.TeleBot.edit_message_media(
                self, media, chat_id, message_id, *args, **kwargs
            ),
            chat_id,
            caption,
            message_id=message_id,
            tipo_midia=type(media).__name__,
        )

    def answer_callback_query(self, callback_query_id, *args, **kwargs):
        return self._auditoria_saida(
            "answer_callback_query",
            lambda: telebot.TeleBot.answer_callback_query(
                self, callback_query_id, *args, **kwargs
            ),
            texto=kwargs.get("text") or (args[0] if args else None),
            show_alert=kwargs.get("show_alert"),
        )

    def _chat_autorizado(self, update):
        """Allowlist de chats, ampliada pelo autocadastro.

        Além da lista estática de ``config.CHATS_AUTORIZADOS``, são aceitos:

        * o comando público ``/start`` (entrada do autocadastro), de qualquer
          chat, para que um usuário novo consiga se registrar;
        * mensagens/callbacks de chats com um formulário de autocadastro ativo
          (ex.: respostas de nome/e-mail antes de existir registro no banco);
        * mensagens/callbacks de chats cujo Telegram ID já conste como usuário
          cadastrado (para receber as mensagens de status).

        A decisão de acesso efetiva continua em ``bot.permissoes``; chats
        desconhecidos e sem formulário ativo seguem sendo descartados.
        """
        if chat_autorizado(update):
            return True
        if permissoes.e_comando_start(update) or permissoes.e_comando_ajuda(update):
            return True
        # Texto livre (ou mídia) em conversa privada é a entrada do autocadastro
        # (o visitante recebe o formulário em vez de ser descartado). O gate de
        # permissões continua valendo para todos os comandos e callbacks.
        if permissoes.e_texto_publico(update) or permissoes.e_mensagem_publica(update):
            return True
        usuario_id = permissoes.usuario_id_do_update(update)
        if permissoes.tem_fluxo_cadastro_ativo(usuario_id):
            return True
        return permissoes.usuario_reconhecido(usuario_id)

    def process_new_updates(self, updates):
        logger.info("TELEGRAM - updates recebidos: %d", len(updates))

        autorizados = []
        for update in updates:
            descricao = descrever_update(update)
            if not self._chat_autorizado(update):
                logger.warning(
                    "TELEGRAM - update descartado (chat nao autorizado): %s",
                    descricao,
                )
                continue

            try:
                permitido, operacao = permissoes.verificar_update(update)
            except Exception:
                logger.exception(
                    "TELEGRAM - falha ao verificar permissao: %s", descricao
                )
                permitido, operacao = False, None

            if not permitido:
                self._negar_acesso(update, operacao)
                continue

            logger.info("TELEGRAM - update autorizado: %s", descricao)
            autorizados.append(update)

        logger.info(
            "TELEGRAM - enviando %d update(s) para os handlers", len(autorizados)
        )

        for update in autorizados:
            self._update_em_processamento = update
            self._falha_no_update = None
            try:
                super().process_new_updates([update])
            finally:
                if self._falha_no_update is None:
                    logger.info(
                        "TELEGRAM - handlers concluidos sem falha: %s",
                        descrever_update(update),
                    )
                else:
                    logger.error(
                        "TELEGRAM - handlers concluidos com falha: %s",
                        descrever_update(update),
                    )
                self._update_em_processamento = None
        return None

    def _negar_acesso(self, update, operacao):
        """Avisa o usuário que a operação não é permitida e registra a tentativa."""
        usuario_id = permissoes.usuario_id_do_update(update)
        papel = permissoes.obter_papel(usuario_id)
        logger.warning(
            "TELEGRAM - acesso negado: usuario=%s papel=%s operacao=%s",
            usuario_id,
            papel,
            operacao,
        )
        try:
            message = getattr(update, "message", None)
            callback = getattr(update, "callback_query", None)
            if message is not None:
                self.send_message(message.chat.id, TEXTO_ACESSO_NEGADO)
            elif callback is not None:
                self.answer_callback_query(callback.id, text=TEXTO_ACESSO_NEGADO)
        except Exception:
            logger.debug(
                "TELEGRAM - falha ao notificar acesso negado", exc_info=True
            )


class BotPreguicoso:
    """Proxy que adia a criacao real do bot e a exigencia do token.

    Importar ``bot.loader`` (e, portanto, qualquer modulo que registre handlers)
    **nao** deve exigir ``TELEGRAM_BOT_TOKEN``. Este proxy:

    * aceita o registro de handlers de mensagem/callback no import, guardando-os
      para repetir no bot real (preservando a ordem de registro);
    * guarda atribuicoes (ex.: ``exception_handler``) para aplicar no bot real;
    * delega qualquer outro acesso ao bot real, criando-o na primeira vez -- e
      somente entao validando/exigindo o token; e
    * nao usa nenhum token ficticio: o token vem exclusivamente de
      ``obter_token_obrigatorio``.

    A exigencia de configuracao permanece integral: a inicializacao efetiva
    (primeira operacao real ou :func:`inicializar_bot`) falha com erro claro se o
    token estiver ausente/vazio, sem enfraquecer a validacao de producao.
    """

    # Nomes que pertencem ao proprio proxy. Qualquer OUTRO nome (mesmo iniciado
    # por "_", como "_falha_no_update" ou "_update_em_processamento") pertence ao
    # bot real e deve ser roteado para ele.
    _INTERNOS = frozenset({"_construtor", "_real", "_registros", "_atributos"})

    def __init__(self, construtor):
        object.__setattr__(self, "_construtor", construtor)
        object.__setattr__(self, "_real", None)
        object.__setattr__(self, "_registros", [])
        object.__setattr__(self, "_atributos", {})

    def _obter_real(self):
        real = object.__getattribute__(self, "_real")
        if real is None:
            real = object.__getattribute__(self, "_construtor")()
            object.__setattr__(self, "_real", real)
            registros = object.__getattribute__(self, "_registros")
            for nome, args, kwargs, func in registros:
                getattr(real, nome)(*args, **kwargs)(func)
            registros.clear()
            for nome, valor in object.__getattribute__(self, "_atributos").items():
                setattr(real, nome, valor)
        return real

    def inicializar(self):
        """Forca a criacao do bot real (validando o token) e o devolve."""
        return self._obter_real()

    def _registrar_handler(self, nome, args, kwargs, func):
        real = object.__getattribute__(self, "_real")
        if real is None:
            object.__getattribute__(self, "_registros").append(
                (nome, args, kwargs, func)
            )
        else:
            getattr(real, nome)(*args, **kwargs)(func)
        return func

    def message_handler(self, *args, **kwargs):
        return lambda func: self._registrar_handler(
            "message_handler", args, kwargs, func
        )

    def callback_query_handler(self, *args, **kwargs):
        return lambda func: self._registrar_handler(
            "callback_query_handler", args, kwargs, func
        )

    def __getattr__(self, nome):
        # Enquanto o bot real nao existe, atributos guardados (ex.: fakes de
        # teste ou ``exception_handler``) sao devolvidos diretamente. Assim que o
        # bot real e criado, TODO acesso passa a ser delegado a ele -- inclusive
        # para nomes presentes no cache --, evitando que valores definidos antes
        # da inicializacao ofusquem os definidos depois (o que quebraria a
        # substituicao de metodos feita pelos testes).
        if object.__getattribute__(self, "_real") is None:
            atributos = object.__getattribute__(self, "_atributos")
            if nome in atributos:
                return atributos[nome]
        return getattr(self._obter_real(), nome)

    def __setattr__(self, nome, valor):
        if nome in BotPreguicoso._INTERNOS:
            object.__setattr__(self, nome, valor)
            return
        real = object.__getattribute__(self, "_real")
        if real is None:
            object.__getattribute__(self, "_atributos")[nome] = valor
        else:
            setattr(real, nome, valor)

    def __repr__(self):  # pragma: no cover - diagnostico
        real = object.__getattribute__(self, "_real")
        return f"<BotPreguicoso inicializado={real is not None}>"


def criar_bot():
    """Cria a instancia real do bot, exigindo o token configurado."""
    return BotAutorizado(obter_token_obrigatorio(), threaded=False)


# O objeto 'bot' nasce aqui como proxy preguicoso e sera importado pelos outros
# modulos. Importar este modulo NAO exige TELEGRAM_BOT_TOKEN; a exigencia ocorre
# na primeira operacao real (ou em `inicializar_bot`).
bot = BotPreguicoso(criar_bot)

# Notificador ligado ao proxy: quando o bot real existir, o proxy delega os
# acessos (idioma de falhas do telebot), sem exigir o token no import.
_notificador_de_falhas = NotificadorDeFalhas()
_notificador_de_falhas.bot = bot
bot.exception_handler = _notificador_de_falhas


def inicializar_bot():
    """Inicializa efetivamente o bot do Telegram (valida/exige o token).

    Ponto unico e explicito para a inicializacao real. Deve ser chamado na
    subida da aplicacao (producao), nunca como efeito colateral de import.
    Retorna a instancia real de :class:`BotAutorizado`.
    """
    return bot.inicializar()
