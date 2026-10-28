import logging
import os
import sys
import time

import pytz
import telebot
from flask import Flask, request
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# 1. Configurações Globais
import config

# 2. O Loader (Coração do bot - NÃO instanciar o bot novamente!)
from bot.loader import bot, bot as tele_bot

# 3. Registrando os Comandos e Menus (Essencial para o bot "ouvir" o Telegram)
# Ordem importante: bot.cadastro, bot.central_controles, bot.favoritos e
# bot.menu_principal sao registrados ANTES de bot.callbacks_menus. O telebot
# executa apenas o primeiro handler de callback cujo filtro casa, e
# bot.callbacks_menus registra um handler generico (func=lambda call: True).
# Registrar os modulos de fluxo especifico primeiro garante que seus callbacks
# (cad_*, adm_*, favoritos_*, favadd_*, favnew_*, favrem_*, troca_*, trocaadm_*,
# minha_*, etc.) sejam
# tratados por eles, e nao engolidos pelo handler generico (que responderia
# "botao invalido" a Central de Controles).
import bot.cadastro
import bot.central_controles
import bot.favoritos
import bot.trocas
import bot.menu_principal
import bot.comandos
import bot.handlers
import bot.callbacks_revisao
import bot.callbacks_menus

# 4. Serviços (Orquestrador)
from services.orquestrador import (
    alimentar_ia,
    auditar_drive,
    coleta_docs_acoes,
    coleta_informes_fiis,
    processar_ia_acoes,
    snapshot_eod,
    varredura_diaria,
)

# 5. Banco de Dados (conexão centralizada e normalizada)
from pipeline_dados.banco_dados import Base
from pipeline_dados.conexao import obter_engine
from pipeline_dados.modelos_catalogo import BaseCatalogo

logger = logging.getLogger("robo.main")

URL_WEBHOOK_PADRAO = "https://robo-fii-v2.onrender.com"

# ==========================================
# 🌐 SERVIDOR WEB E WEBHOOK (RENDER)
# ==========================================
app = Flask(__name__)


@app.route('/' + (config.TELEGRAM_BOT_TOKEN or ""), methods=['POST'])
def webhook_handler():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)

        chat_id = None
        if update.message:
            chat_id = update.message.chat.id
        elif update.callback_query and update.callback_query.message:
            chat_id = update.callback_query.message.chat.id
        if chat_id is not None:
            logger.info("TELEGRAM DIAGNOSTICO - chat_id recebido: %s", chat_id)

        # CORREÇÃO: Usamos tele_bot para processar as mensagens, e não a pasta 'bot'
        tele_bot.process_new_updates([update])

        return "OK", 200
    return "Erro", 403


@app.route('/')
def index():
    return "Bot Institucional Ativo e Operante!", 200


# ==========================================
# ⏰ AGENDADOR DE TAREFAS (DESPERTADOR)
# ==========================================
fuso_horario = pytz.timezone('America/Sao_Paulo')
scheduler = BackgroundScheduler(timezone=fuso_horario)


def _flag_ativa(nome):
    return str(os.environ.get(nome, "")).strip().lower() in {"1", "true", "yes", "on"}


def criar_tabelas_se_solicitado():
    """Cria as tabelas dos modelos SOMENTE se explicitamente solicitado.

    Decisão (correção de inicialização): a aplicação NÃO executa
    ``Base.metadata.create_all`` automaticamente. O banco Neon já possui as
    tabelas (inclusive tabelas que não são representadas pelos modelos) e a
    criação de schema no boot poderia alterar um banco de produção. A criação
    permanece disponível de forma opt-in (``CRIAR_TABELAS=1``) para ambientes de
    desenvolvimento limpos.
    """
    if not _flag_ativa("CRIAR_TABELAS"):
        logger.info(
            "Criacao automatica de tabelas desativada "
            "(defina CRIAR_TABELAS=1 para habilitar em desenvolvimento)."
        )
        return
    engine = obter_engine()
    Base.metadata.create_all(engine)
    BaseCatalogo.metadata.create_all(engine)
    logger.info("Tabelas verificadas/criadas a pedido (CRIAR_TABELAS=1).")


def configurar_webhook():
    """Registra o webhook do Telegram. O token nunca é exposto em log."""
    base = (os.environ.get("WEBHOOK_BASE_URL") or URL_WEBHOOK_PADRAO).rstrip("/")
    nova_url = f"{base}/{config.TELEGRAM_BOT_TOKEN}"
    tele_bot.remove_webhook()
    time.sleep(1)
    tele_bot.set_webhook(url=nova_url)
    logger.info("Webhook configurado para %s/<token oculto>", base)


def _em_teste():
    """Importacao em unittest/pytest nao deve agendar jobs nem registrar webhook."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    return any(
        nome in sys.modules
        for nome in ("unittest", "pytest", "_pytest")
    )


def _eh_wsgi_producao():
    """Gunicorn (e equivalentes) importam o modulo sem ``__main__``.

    Sem isso o agendador so subia com ``ROBO_INICIAR_NO_IMPORT=1`` ou
    ``python main.py``, e o cron das 08:00 nunca disparava no Render.
    """
    if _em_teste():
        return False
    if __name__ == "__main__":
        return False
    if "gunicorn" in sys.modules:
        return True
    servidor = (os.environ.get("SERVER_SOFTWARE") or "").lower()
    if "gunicorn" in servidor:
        return True
    if os.environ.get("RENDER"):
        return True
    return any(
        chave.startswith("GUNICORN_") or chave.startswith("RENDER_")
        for chave in os.environ
    )


def registrar_jobs():
    """Jobs combinados; ids fixos para reentrada segura no mesmo processo."""
    jobs = (
        (
            "varredura_diaria",
            varredura_diaria,
            CronTrigger(day_of_week="mon-fri", hour=8, minute=0),
        ),
        (
            "coleta_informes_fiis",
            coleta_informes_fiis,
            CronTrigger(day=12, hour=9, minute=0),
        ),
        (
            "coleta_docs_acoes",
            coleta_docs_acoes,
            CronTrigger(day_of_week="tue", hour=9, minute=30),
        ),
        (
            "processar_ia_acoes",
            processar_ia_acoes,
            CronTrigger(day_of_week="tue", hour=10, minute=0),
        ),
        (
            "alimentar_ia",
            alimentar_ia,
            CronTrigger(day_of_week="mon-fri", hour=10, minute=0),
        ),
        (
            "auditar_drive",
            auditar_drive,
            CronTrigger(day_of_week="sat", hour=9, minute=0),
        ),
        (
            "snapshot_eod",
            snapshot_eod,
            CronTrigger(day_of_week="mon-fri", hour=19, minute=0),
        ),
    )
    for job_id, funcao, trigger in jobs:
        scheduler.add_job(
            funcao,
            trigger,
            id=job_id,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )


def iniciar_agendador():
    """Registra os crons e inicia o APScheduler (timezone America/Sao_Paulo)."""
    if scheduler.running:
        logger.info("Agendador ja em execucao; jobs nao reinsercidos.")
        return
    registrar_jobs()
    scheduler.start()
    logger.info(
        "Agendador iniciado: varredura_diaria seg-sex 08:00; "
        "fiis dia 12 09:00; docs_acoes ter 09:30; ia_acoes ter 10:00; "
        "alimentar_ia seg-sex 10:00; auditar_drive sab 09:00; "
        "snapshot_eod seg-sex 19:00."
    )


def inicializar_aplicacao():
    """Efeitos colaterais de produção (chamados explicitamente no boot)."""
    criar_tabelas_se_solicitado()
    iniciar_agendador()
    configurar_webhook()


def main():
    inicializar_aplicacao()
    porta = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=porta)


# Importacao em testes permanece limpa. Em Gunicorn/Render o boot completo
# roda sem exigir ROBO_INICIAR_NO_IMPORT. A flag continua como opt-in extra.
if _flag_ativa("ROBO_INICIAR_NO_IMPORT") or _eh_wsgi_producao():
    inicializar_aplicacao()


if __name__ == "__main__":
    main()
