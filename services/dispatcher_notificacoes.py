"""Dispatcher de entrega individual de notificações (Fase 6, Etapa 7).

Camada que processa notificações JÁ persistidas por ``services/notificacoes.py``
(motor da Etapa 6) e as entrega por canal, respeitando autorização, escopo e
preferências individuais no momento da entrega:

    EVENTO -> services/notificacoes.py -> Notificacao -> dispatcher
           -> preferências -> canal -> resultado da entrega

Reutiliza exclusivamente (nenhuma regra paralela):
- ``services/autorizacao.py``: usuário ativo e a permissão ``notificacoes.consultar``
  da matriz central são revalidados na entrega;
- ``services/escopo.py``: o destinatário é SEMPRE ``Notificacao.usuario_id``
  (dono do recurso); a entrega confirma o escopo de acesso (anti-IDOR/BOLA) —
  nenhum ``usuario_id`` ou ``telegram_chat_id`` vem do cliente;
- ``services/preferencias.py``: mestre ``notificacoes_ativas``, preferência do
  tipo de evento e ``web_ativo``/``telegram_ativo``;
- ``services/telegram.py``: entrega individual usando o vínculo Telegram
  existente (``telegram_user_id``/``telegram_chat_id``);
- ``services/auditoria.py``: trilha de eventos sem segredos;
- padrão de sessão do projeto (``services.usuarios._sessao``).

Garantias:
- Idempotência pelo identificador da notificação: notificação ENVIADA/LIDA nunca
  é reentregue; FALHA não é reprocessada (salvo ``forcar``).
- Retry controlado (``MAX_TENTATIVAS``) com backoff persistido em
  ``proxima_tentativa``; sem loops infinitos.
- Falha de um usuário/canal não interrompe os demais (``despachar_pendentes``).
- Nenhum segredo (API Key, token, senha, token Telegram, credencial) é
  persistido no banco, na auditoria ou em logs.
"""
import logging
from datetime import datetime, timedelta

from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import or_

from pipeline_dados.banco_dados import Notificacao, Usuario
from services import auditoria, autorizacao, escopo, notificacoes, preferencias, telegram
from services.usuarios import _sessao

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CONFIGURAÇÃO DE RETRY (controlado; sem loops infinitos)
# ---------------------------------------------------------------------------
# Máximo de tentativas de entrega por notificação antes de FALHA permanente.
MAX_TENTATIVAS = 3

# Espera base (segundos) antes de reprocessar uma falha transitória.
INTERVALO_RETRY_SEGUNDOS = 60

# ---------------------------------------------------------------------------
# RESULTADOS DA ENTREGA (expostos no resumo de cada notificação)
# ---------------------------------------------------------------------------
RESULTADO_ENTREGUE = "ENTREGUE"
RESULTADO_FALHA = "FALHA"
RESULTADO_RETRY = "RETRY"
RESULTADO_IGNORADA = "IGNORADA"

# ---------------------------------------------------------------------------
# AUDITORIA (sem segredos)
# ---------------------------------------------------------------------------
ACAO_ENTREGUE = "NOTIFICACAO_ENTREGUE"
ACAO_FALHA = "NOTIFICACAO_ENTREGA_FALHOU"


def _pref(prefs, nome, padrao=True):
    """Lê uma preferência de um ORM ou de um dict de defaults, sem segredos."""
    if isinstance(prefs, dict):
        return prefs.get(nome, padrao)
    return getattr(prefs, nome, padrao)


def _resumo(resultado, motivo, notificacao):
    """Resumo estruturado do resultado de entrega de uma notificação."""
    return {
        "resultado": resultado,
        "motivo": motivo,
        "notificacao_id": notificacao.id,
        "usuario_id": notificacao.usuario_id,
        "canal": notificacao.canal,
        "status": notificacao.status,
        "tentativas": notificacao.tentativas,
        "entregue": notificacao.status == notificacoes.STATUS_ENVIADA,
    }


def _aguardando_retry(notificacao):
    """True quando a notificação está aguardando a janela de retry."""
    proxima = getattr(notificacao, "proxima_tentativa", None)
    if proxima is None:
        return False
    return proxima > datetime.now()


def _canal_valido(canal):
    """True quando o canal está no catálogo controlado do motor."""
    return canal in notificacoes.CANAIS_VALIDOS


def _motivo_inelegivel(usuario, notificacao, session):
    """Motivo de inelegibilidade no momento da entrega, ou ``None``.

    Reutiliza a matriz central (``autorizacao``) e as preferências
    (``services/preferencias``): usuário desativado, sem a permissão
    ``notificacoes.consultar``, preferências desativadas ou canal indisponível.
    Nenhum segredo é lido ou registrado.
    """
    if autorizacao.papel_de(usuario) is None:
        return "usuario_desativado"
    if not autorizacao.tem_permissao(usuario, "notificacoes.consultar"):
        return "usuario_nao_elegivel"

    prefs = preferencias.buscar_preferencias(usuario, session=session)
    if prefs is None:
        prefs = preferencias.preferencias_padrao()
    if not _pref(prefs, "notificacoes_ativas"):
        return "preferencias_desativadas"
    campo = notificacoes.PREFERENCIA_POR_EVENTO.get(notificacao.tipo)
    if campo is not None and not _pref(prefs, campo):
        return "preferencias_desativadas"

    if notificacao.canal == notificacoes.CANAL_WEB:
        if not _pref(prefs, "web_ativo"):
            return "canal_desativado"
        return None

    # Canal TELEGRAM: vínculo real exigido (nunca chat id arbitrário).
    if not _pref(prefs, "telegram_ativo"):
        return "telegram_desativado"
    if getattr(usuario, "telegram_user_id", None) is None:
        return "telegram_sem_vinculo"
    if getattr(usuario, "telegram_chat_id", None) is None:
        return "telegram_sem_chat"
    return None


def _marcar_falha(sessao, notificacao, motivo):
    """Marca FALHA permanente (sem entrega) e audita sem segredos."""
    notificacao.status = notificacoes.STATUS_FALHA
    notificacao.ultimo_erro = motivo
    notificacao.tentativas += 1
    sessao.commit()
    auditoria.registrar_evento(
        acao=ACAO_FALHA,
        alvo=f"notificacao:{notificacao.id}",
        detalhe=(
            f"canal={notificacao.canal}, motivo={motivo}, "
            f"tentativas={notificacao.tentativas}"
        ),
        usuario_id=notificacao.usuario_id,
        session=sessao,
    )
    return _resumo(RESULTADO_FALHA, motivo, notificacao)


def _entregar_web(sessao, notificacao):
    """Entrega WEB: torna a notificação disponível ao usuário autenticado.

    A disponibilidade para o usuário já é a persistência (consultável pela API
    existente); o dispatcher apenas registra o estado de entrega
    (``ENVIADA`` + ``enviada_em``), sem envio externo.
    """
    notificacao.status = notificacoes.STATUS_ENVIADA
    notificacao.enviada_em = datetime.now()
    notificacao.ultimo_erro = None
    sessao.commit()
    auditoria.registrar_evento(
        acao=ACAO_ENTREGUE,
        alvo=f"notificacao:{notificacao.id}",
        detalhe=f"canal=WEB, tentativas={notificacao.tentativas}",
        usuario_id=notificacao.usuario_id,
        session=sessao,
    )
    return _resumo(RESULTADO_ENTREGUE, "entregue", notificacao)


def _entregar_telegram(sessao, notificacao, usuario):
    """Entrega individual via Telegram usando o vínculo do usuário.

    Reutiliza ``services/telegram.enviar_notificacao``. Falha transitória:
    incrementa tentativas e agenda retry; ao atingir o limite, marca FALHA
    permanente. A falha nunca é propagada para o chamador.
    """
    try:
        sucesso = telegram.enviar_notificacao(
            usuario, notificacao.titulo, notificacao.mensagem, session=sessao
        )
    except Exception:
        sucesso = False

    if sucesso:
        notificacao.status = notificacoes.STATUS_ENVIADA
        notificacao.enviada_em = datetime.now()
        notificacao.ultimo_erro = None
        sessao.commit()
        auditoria.registrar_evento(
            acao=ACAO_ENTREGUE,
            alvo=f"notificacao:{notificacao.id}",
            detalhe=f"canal=TELEGRAM, tentativas={notificacao.tentativas}",
            usuario_id=notificacao.usuario_id,
            session=sessao,
        )
        return _resumo(RESULTADO_ENTREGUE, "entregue", notificacao)

    motivo = "falha_transitoria"
    if notificacao.tentativas >= MAX_TENTATIVAS:
        notificacao.status = notificacoes.STATUS_FALHA
        notificacao.ultimo_erro = motivo
        sessao.commit()
        auditoria.registrar_evento(
            acao=ACAO_FALHA,
            alvo=f"notificacao:{notificacao.id}",
            detalhe=(
                f"canal=TELEGRAM, motivo={motivo}, "
                f"tentativas={notificacao.tentativas}"
            ),
            usuario_id=notificacao.usuario_id,
            session=sessao,
        )
        return _resumo(RESULTADO_FALHA, motivo, notificacao)

    notificacao.ultimo_erro = motivo
    notificacao.proxima_tentativa = datetime.now() + timedelta(
        seconds=INTERVALO_RETRY_SEGUNDOS
    )
    sessao.commit()
    auditoria.registrar_evento(
        acao=ACAO_FALHA,
        alvo=f"notificacao:{notificacao.id}",
        detalhe=(
            f"canal=TELEGRAM, motivo={motivo}, tentativas={notificacao.tentativas}"
        ),
        usuario_id=notificacao.usuario_id,
        session=sessao,
    )
    return _resumo(RESULTADO_RETRY, motivo, notificacao)


def _despachar(sessao, notificacao, forcar=False):
    """Pipeline de entrega de uma notificação (sessão externa já aberta)."""
    if notificacao.status in (
        notificacoes.STATUS_ENVIADA,
        notificacoes.STATUS_LIDA,
    ):
        return _resumo(RESULTADO_IGNORADA, "ja_entregue", notificacao)
    if notificacao.status == notificacoes.STATUS_FALHA and not forcar:
        return _resumo(RESULTADO_IGNORADA, "falha_permanente", notificacao)
    if not forcar and _aguardando_retry(notificacao):
        return _resumo(RESULTADO_IGNORADA, "aguardando_retry", notificacao)

    if not _canal_valido(notificacao.canal):
        return _marcar_falha(sessao, notificacao, "canal_invalido")

    usuario = sessao.get(Usuario, notificacao.usuario_id)
    if usuario is None:
        return _marcar_falha(sessao, notificacao, "usuario_inexistente")

    # Elegibilidade no momento da entrega (autorização + preferências).
    motivo = _motivo_inelegivel(usuario, notificacao, session=sessao)
    if motivo is not None:
        return _marcar_falha(sessao, notificacao, motivo)

    # Escopo (anti-IDOR/BOLA): o destinatário é sempre o dono da notificação.
    if not escopo.usuario_pode_acessar(usuario, notificacao):
        return _marcar_falha(sessao, notificacao, "escopo_negado")

    notificacao.tentativas += 1
    if notificacao.canal == notificacoes.CANAL_WEB:
        return _entregar_web(sessao, notificacao)
    return _entregar_telegram(sessao, notificacao, usuario)


# ===========================================================================
# API PÚBLICA
# ===========================================================================


def despachar_notificacao(notificacao_id, session=None, forcar=False):
    """Processa a entrega de uma notificação existente pelo ``notificacao_id``.

    ``forcar=True`` ignora o estado (reprocessa inclusive FALHA e retry
    agendado). Retorna um resumo com ``resultado``, ``motivo``, ``canal``,
    ``status``, ``tentativas`` e ``entregue``. Não levanta para falhas de
    usuário/canal — apenas persiste o resultado.
    """
    with _sessao(session) as s:
        notificacao = s.get(Notificacao, notificacao_id)
        if notificacao is None:
            return {
                "resultado": RESULTADO_IGNORADA,
                "motivo": "nao_encontrada",
                "notificacao_id": notificacao_id,
            }
        return _despachar(s, notificacao, forcar=forcar)


def despachar_pendentes(session=None, limite=None):
    """Entrega as notificações pendentes (``GERADA``) elegíveis neste momento.

    Considera apenas notificações sem retry agendado ou com janela vencida.
    Falhas são isoladas por notificação: uma falha não interrompe as demais.
    Retorna um resumo agregado (processadas, entregues, falhas, retries,
    ignoradas e o detalhe por notificação).
    """
    with _sessao(session) as s:
        query = s.query(Notificacao).filter(
            Notificacao.status == notificacoes.STATUS_GERADA,
            or_(
                Notificacao.proxima_tentativa.is_(None),
                Notificacao.proxima_tentativa <= datetime.now(),
            ),
        )
        if limite is not None:
            query = query.limit(limite)
        pendentes = query.order_by(Notificacao.id).all()

        resumo = {
            "processadas": 0,
            "entregues": 0,
            "falhas": 0,
            "retries": 0,
            "ignoradas": 0,
            "notificacoes": [],
        }
        for notificacao in pendentes:
            try:
                resultado = _despachar(s, notificacao)
            except Exception as e:  # isolamento por notificação
                logger.error(
                    "Falha inesperada ao despachar notificação %s: %s",
                    notificacao.id,
                    type(e).__name__,
                )
                resumo["falhas"] += 1
                continue
            resumo["processadas"] += 1
            if resultado["resultado"] == RESULTADO_ENTREGUE:
                resumo["entregues"] += 1
            elif resultado["resultado"] == RESULTADO_RETRY:
                resumo["retries"] += 1
            elif resultado["resultado"] == RESULTADO_FALHA:
                resumo["falhas"] += 1
            else:
                resumo["ignoradas"] += 1
            resumo["notificacoes"].append(resultado)
        return resumo


def processar_evento_e_despachar(evento, session=None):
    """Pipeline completo: gera notificações e entrega imediatamente.

    Encadeia ``services/notificacoes.processar_evento`` (evento -> Notificacao)
    com ``despachar_pendentes`` (Notificacao -> canais). Retorna os resumos da
    geração e da entrega.
    """
    with _sessao(session) as s:
        geracao = notificacoes.processar_evento(evento, session=s)
        entrega = despachar_pendentes(session=s)
    return {"geracao": geracao, "entrega": entrega}


# ===========================================================================
# INTEGRAÇÃO COM O AGENDADOR (BackgroundScheduler existente)
# ===========================================================================
# Aditivo e desativável (config ``DISPATCHER_NOTIFICACOES_ATIVO``). Reutiliza o
# scheduler já criado em main.py — nunca cria um segundo agendador, não duplica
# jobs (id fixo) e não altera os jobs legados (``varredura_diaria``). O ciclo
# é executado em thread própria do APScheduler, sem bloquear o pipeline
# financeiro nem o webhook do bot.

# Id fixo do job no scheduler (usado para idempotência do registro).
JOB_DISPATCHER_ID = "dispatcher_notificacoes"

# Intervalo padrão (minutos) usado quando ``interval_minutos`` não é informado
# ou é inválido — espelha o padrão da configuração.
INTERVALO_PADRAO_MINUTOS = 5


def executar_ciclo_pendentes(session=None):
    """Executa ``despachar_pendentes`` com proteção para o agendador.

    Nunca levanta: qualquer exceção inesperada é registrada em log e um resumo
    vazio (com ``falhas=1``) é retornado, para que o job do APScheduler nunca
    morra nem derrube o agendador. Respeita retry/``proxima_tentativa`` (via
    ``despachar_pendentes``) e o isolamento por notificação.
    """
    try:
        return despachar_pendentes(session=session)
    except Exception as e:
        logger.error(
            "Falha inesperada no ciclo automático do dispatcher (não bloqueia): %s",
            type(e).__name__,
        )
        return {
            "processadas": 0,
            "entregues": 0,
            "falhas": 1,
            "retries": 0,
            "ignoradas": 0,
            "notificacoes": [],
        }


def registrar_dispatcher_no_scheduler(scheduler, interval_minutos=None, ativo=True):
    """Registra (idempotente) o job do dispatcher no scheduler existente.

    Reutiliza o ``scheduler`` informado pelo chamador — nunca cria um segundo
    agendador. Usa ``id`` fixo (``JOB_DISPATCHER_ID``) para não duplicar jobs
    (segunda chamada retorna ``False`` sem novo registro) e
    ``max_instances=1``/``coalesce`` para impedir execuções concorrentes do
    dispatcher. Não altera jobs legados. Desativável via ``ativo=False``.

    Retorna ``True`` quando o job foi registrado e ``False`` quando desativado,
    já existente ou o scheduler não foi informado.
    """
    if not ativo or scheduler is None:
        return False
    if scheduler.get_job(JOB_DISPATCHER_ID) is not None:
        return False
    if interval_minutos is None or interval_minutos < 1:
        interval_minutos = INTERVALO_PADRAO_MINUTOS
    scheduler.add_job(
        executar_ciclo_pendentes,
        IntervalTrigger(minutes=interval_minutos),
        id=JOB_DISPATCHER_ID,
        replace_existing=False,
        max_instances=1,
        coalesce=True,
    )
    return True
