import logging

import telebot

import config
from bot.telegram_utils import (
    NotificadorDeFalhas,
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

    A execução é verificável pelos logs: cada update autorizado e o resultado
    final dos handlers (sem falha / com falha) são registrados.
    """

    def _chat_autorizado(self, update):
        return chat_autorizado(update)

    def process_new_updates(self, updates):
        logger.info("TELEGRAM - updates recebidos: %d", len(updates))

        autorizados = []
        for update in updates:
            descricao = descrever_update(update)
            if self._chat_autorizado(update):
                logger.info("TELEGRAM - update autorizado: %s", descricao)
                autorizados.append(update)
            else:
                logger.warning(
                    "TELEGRAM - update descartado (chat nao autorizado): %s",
                    descricao,
                )

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


# O objeto 'bot' nasce aqui e será importado pelos outros módulos
bot = BotAutorizado(obter_token_obrigatorio(), threaded=False)
bot.exception_handler = NotificadorDeFalhas()
bot.exception_handler.bot = bot
