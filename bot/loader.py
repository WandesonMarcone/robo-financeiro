import logging

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

    def _chat_autorizado(self, update):
        return chat_autorizado(update)

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


# O objeto 'bot' nasce aqui e será importado pelos outros módulos
bot = BotAutorizado(obter_token_obrigatorio(), threaded=False)
bot.exception_handler = NotificadorDeFalhas()
bot.exception_handler.bot = bot
