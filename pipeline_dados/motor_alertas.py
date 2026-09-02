"""Motor de qualidade, detecção de mudanças e alertas — Fase 4 (aditivo).

Implementa a primeira camada de inteligência do Estratégia Financeira para
AÇÕES e FUNDOS IMOBILIÁRIOS de forma genérica:

    COLETAR -> VALIDAR -> COMPARAR -> DETECTAR ALTERAÇÕES -> CLASSIFICAR -> ALERTAR

A arquitetura é única para ambos os tipos de ativo, baseada em
``tipo_ativo + ativo + indicador + valor + histórico + regra + severidade``,
permitindo que novos tipos de ativo sejam adicionados depois apenas com um
novo catálogo de regras (pipeline_dados.regras_indicadores).

Garantias:
- Negativo legítimo (ROE, margens, dívida líquida, LPA etc.) NÃO gera erro.
- O valor original nunca é alterado para silenciar um alerta.
- Sem histórico (primeira observação) não há alerta de mercado; o valor é
  registrado para comparações futuras.
- Sem alteração de valor, nada é re-armazenado e nenhum alerta é emitido.
- Alertas pequenos não disparam: apenas variações acima dos limiares da regra.
- Ausência de Telegram não derruba nada: a notificação usa a função guardada
  ``bot.loader.enviar_mensagem`` (TELEGRAM = SKIPPED quando não configurado).
- Todos os eventos ficam em ``alertas_eventos`` (base para a inteligência
  futura: motor de IA, site, dashboards, relatórios e publicações).
"""
import logging
from datetime import date, datetime
from decimal import Decimal

import config
from pipeline_dados.banco_dados import AlertaEvento, IndicadorHistorico
from pipeline_dados.mapeamento_sheets import ORIGEM_GOOGLE_SHEETS
from pipeline_dados.qualidade_dados import parsear_numero
from pipeline_dados.regras_indicadores import (
    CRITICO,
    ERRO,
    WARNING,
    classificar_indicador,
    obter_regra,
)

logger = logging.getLogger(__name__)

TIPO_QUALIDADE = "QUALIDADE"
TIPO_MERCADO = "MERCADO"
TIPO_CRITICO = "CRITICO"

# Indicadores monitorados por tipo de ativo (chaves usadas nos dicts do 5C).
INDICADORES_FII = (
    "preco", "pvp", "dy", "liquidez", "vpa", "lucro_12m", "dividendo_mensal", "qtd_imoveis",
)
INDICADORES_ACAO = (
    "preco", "dy", "pl", "pvp", "p_ativo", "marg_bruta", "marg_ebit", "marg_liquida",
    "p_ebit", "ev_ebit", "div_liq_patrimonio", "psr", "p_cap_giro", "p_at_circ_liq",
    "liq_corrente", "roe", "roa", "roic", "cagr_rec_5a", "liq_media", "vpa", "lpa",
    "peg_ratio", "valor_mercado",
)

INDICADORES_POR_TIPO: dict[str, tuple[str, ...]] = {
    "FII": INDICADORES_FII,
    "ACAO": INDICADORES_ACAO,
}


def _decimal(valor) -> Decimal | None:
    if valor is None:
        return None
    if isinstance(valor, Decimal):
        return valor
    numero = parsear_numero(valor)
    if numero is None:
        return None
    return Decimal(str(numero))


def _variacao_percentual(anterior: float, atual: float) -> Decimal | None:
    """Variação percentual (atual - anterior)/|anterior|, ou None se indefinida."""
    if anterior == 0:
        return None
    variacao = (atual - anterior) / abs(anterior)
    return Decimal(f"{variacao * 100:.2f}")


def _valores_iguais(a, b, tolerancia: float = 1e-9) -> bool:
    if a is None or b is None:
        return a is b
    return abs(float(a) - float(b)) <= tolerancia


# ===========================================================================
# DETECÇÃO DE MUDANÇAS E REGISTRO DE HISTÓRICO
# ===========================================================================

def detectar_mudanca(session, ativo, tipo_ativo: str, indicador: str, valor, data_referencia, origem):
    """Compara o valor atual com o registrado e atualiza ``indicadores_historico``.

    Retorna um dict com o resultado da comparação:
    - ``mudou``: True se o valor mudou em relação ao histórico;
    - ``valor_anterior``: valor anterior (None na primeira observação);
    - ``variacao_percentual``: Decimal ou None;
    - ``regra``/``limite``: limiares da regra do indicador.
    O registro não é re-escrito quando o valor não muda (apenas ``ultima_coleta``).
    """
    regra = obter_regra(tipo_ativo, indicador)
    resultado = {
        "mudou": False,
        "valor_anterior": None,
        "variacao_percentual": None,
        "regra": regra.indicador if regra else indicador,
        "limite_variacao_pct": regra.limite_variacao_pct if regra else 0.20,
        "limite_variacao_critica_pct": regra.limite_variacao_critica_pct if regra else 0.50,
    }

    valor_atual = _decimal(valor)
    if valor_atual is None:
        # Valor ausente/ilegível: não avalia, não regrava histórico e não
        # corrompe o valor anterior já registrado.
        return resultado

    registro = (
        session.query(IndicadorHistorico)
        .filter_by(ativo_id=ativo.id, indicador=indicador)
        .first()
    )

    agora = datetime.now()

    if registro is None:
        registro = IndicadorHistorico(
            ativo_id=ativo.id,
            tipo_ativo=tipo_ativo,
            indicador=indicador,
            valor_atual=valor_atual,
            valor_anterior=None,
            variacao_percentual=None,
            data_referencia=data_referencia,
            data_ultima_alteracao=data_referencia if valor_atual is not None else None,
            ultima_coleta=agora,
            origem=origem,
        )
        session.add(registro)
        resultado["valor_anterior"] = None
        return resultado

    resultado["valor_anterior"] = registro.valor_atual
    if _valores_iguais(registro.valor_atual, valor_atual):
        registro.ultima_coleta = agora
        registro.data_referencia = data_referencia or registro.data_referencia
        return resultado

    registro.valor_anterior = registro.valor_atual
    registro.valor_atual = valor_atual
    registro.variacao_percentual = None
    if valor_atual is not None and registro.valor_anterior is not None:
        anterior_float = float(registro.valor_anterior)
        atual_float = float(valor_atual)
        registro.variacao_percentual = _variacao_percentual(anterior_float, atual_float)
    registro.data_ultima_alteracao = data_referencia
    registro.data_referencia = data_referencia or registro.data_referencia
    registro.ultima_coleta = agora
    registro.origem = origem
    resultado["mudou"] = True
    resultado["variacao_percentual"] = registro.variacao_percentual
    return resultado


# ===========================================================================
# GERAÇÃO DE ALERTAS
# ===========================================================================

def _recomendacao(tipo_alerta: str) -> str:
    if tipo_alerta == TIPO_CRITICO:
        return "Exigir análise imediata; verificar a fonte e o contexto antes de qualquer decisão."
    if tipo_alerta == TIPO_QUALIDADE:
        return "Conferir a fonte antes de considerar o dado como real."
    return "Analisar antes de considerar o dado como evento real."


def _motivo_mudanca(classificacao: dict, variacao_pct) -> str:
    if variacao_pct is None:
        return f"Alteração relevante detectada em {classificacao['nome_exibicao']}."
    return (f"Alteração relevante de {variacao_pct}% em "
            f"{classificacao['nome_exibicao']}.")


def gerar_alerta(
    session,
    ativo,
    tipo_ativo: str,
    indicador: str,
    valor,
    mudanca: dict,
    data_referencia,
    origem: str = ORIGEM_GOOGLE_SHEETS,
) -> AlertaEvento | None:
    """Classifica a ocorrência e, se relevante, persiste um ``AlertaEvento``.

    Prioridade de tipo de alerta:
    1. CRITICO: qualidade crítica (valor implausível) ou variação acima do
       limiar crítico;
    2. QUALIDADE: valor com WARNING/ERRO (possível dado incorreto);
    3. MERCADO: variação relevante acima do limiar da regra (dado provavelmente
       real).

    Na primeira observação (sem histórico) e sem mudança de valor, nenhum
    alerta de mercado é emitido; um problema de qualidade, porém, é sinalizado.
    """
    classificacao = classificar_indicador(tipo_ativo, indicador, valor)
    if classificacao["severidade"] == "IGNORADO":
        return None

    variacao_pct = mudanca["variacao_percentual"]
    # variacao_percentual é percentual (ex.: 16.51 = 16,51%); os limiares da
    # regra são frações (ex.: 0.10 = 10%), portanto normaliza para fração.
    variacao_frac = abs(float(variacao_pct)) / 100.0 if variacao_pct is not None else 0.0
    limite_var = float(mudanca["limite_variacao_pct"])
    limite_crit = float(mudanca["limite_variacao_critica_pct"])

    severidade = classificacao["severidade"]

    if severidade == CRITICO:
        tipo_alerta = TIPO_CRITICO
        motivo = classificacao["motivo"]
    elif severidade == ERRO:
        tipo_alerta = TIPO_QUALIDADE
        motivo = classificacao["motivo"]
    elif mudanca["mudou"] and variacao_frac >= limite_crit:
        tipo_alerta = TIPO_CRITICO
        motivo = _motivo_mudanca(classificacao, variacao_pct)
    elif severidade == WARNING:
        tipo_alerta = TIPO_QUALIDADE
        motivo = classificacao["motivo"]
    elif mudanca["mudou"] and variacao_frac >= limite_var:
        tipo_alerta = TIPO_MERCADO
        motivo = _motivo_mudanca(classificacao, variacao_pct)
    else:
        return None

    alerta = AlertaEvento(
        tipo_alerta=tipo_alerta,
        tipo_ativo=tipo_ativo,
        ativo_id=ativo.id,
        indicador=indicador,
        valor_anterior=_decimal(mudanca["valor_anterior"]),
        valor_atual=_decimal(valor),
        variacao_percentual=variacao_pct,
        regra=classificacao["regra"],
        motivo=motivo[:255],
        severidade=severidade,
        recomendacao=_recomendacao(tipo_alerta),
        origem=origem,
        data_referencia=data_referencia,
        data_evento=datetime.now(),
        telegram_enviado=False,
    )
    session.add(alerta)
    return alerta


# ===========================================================================
# MENSAGEM PARA O TELEGRAM
# ===========================================================================

def formatar_mensagem(alerta: AlertaEvento, ticker: str) -> str:
    """Monta a mensagem objetiva do alerta para o Telegram."""
    emoji = {"MERCADO": "🔵", "QUALIDADE": "🟠", "CRITICO": "🔴"}.get(alerta.tipo_alerta, "⚪")
    rotulo = {"MERCADO": "ALERTA DE MERCADO",
              "QUALIDADE": "ALERTA DE QUALIDADE",
              "CRITICO": "ALERTA CRÍTICO"}.get(alerta.tipo_alerta, alerta.tipo_alerta)

    def _fmt(valor) -> str:
        if valor is None:
            return "—"
        numero = float(valor)
        if abs(numero) >= 1000:
            return f"{numero:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{numero:.4f}".rstrip("0").rstrip(".")

    linhas = [f"{emoji} {rotulo}", "", f"📌 {ticker}", f"📄 {alerta.tipo_ativo}",
              "", f"📊 {alerta.indicador}"]
    if alerta.valor_anterior is not None:
        linhas.append(f"Anterior: {_fmt(alerta.valor_anterior)}")
    linhas.append(f"Atual: {_fmt(alerta.valor_atual)}")
    if alerta.variacao_percentual is not None:
        linhas.append(f"Variação: {_fmt(alerta.variacao_percentual)}%")
    linhas.append("")
    linhas.append(f"Motivo: {alerta.motivo}")
    linhas.append(f"Severidade: {alerta.severidade}")
    linhas.append("")
    linhas.append(f"⚠️ {alerta.recomendacao}")
    return "\n".join(linhas)


def notificar_telegram(alerta: AlertaEvento, ticker: str) -> bool:
    """Envia o alerta ao Telegram de forma segura (SKIPPED quando não configurado)."""
    try:
        from bot.loader import enviar_mensagem

        resultado = enviar_mensagem(config.TELEGRAM_CHAT_ID, formatar_mensagem(alerta, ticker))
    except Exception as e:
        logger.warning("[Telegram] Falha ao notificar alerta: %s", e)
        return False
    if resultado is None:
        return False
    alerta.telegram_enviado = True
    return True


def _rotulo_alerta(tipo_alerta: str) -> str:
    """Rótulo amigável do alerta (reaproveitado na notificação individual)."""
    return {
        TIPO_MERCADO: "ALERTA DE MERCADO",
        TIPO_QUALIDADE: "ALERTA DE QUALIDADE",
        TIPO_CRITICO: "ALERTA CRÍTICO",
    }.get(tipo_alerta, "ALERTA")


def _para_float(valor):
    """Converte valor numérico para float (payload JSON do motor individual)."""
    if valor is None:
        return None
    return float(valor)


def notificar_individual(
    session,
    alerta: AlertaEvento,
    ativo,
    tipo_ativo: str,
) -> None:
    """Alimenta o motor individual de notificações (Fase 6) sem quebrar o fluxo.

    O alerta real detectado pelo pipeline (Fase 4) vira um evento
    ``ALERTA_MERCADO`` para ``services.notificacoes.processar_evento``, que
    decide os usuários elegíveis (permissão central, acompanhamento do ativo,
    preferência, limite do plano e canais) e persiste as notificações
    individualizadas de forma idempotente. O envio legado ao Telegram é
    preservado — este é um passo aditivo. Erros são isolados: uma falha aqui
    nunca derruba o espelhamento 5C nem a detecção de alertas.
    """
    try:
        from services.notificacoes import processar_evento

        session.flush()
        evento = {
            "tipo": "ALERTA_MERCADO",
            "titulo": f"{ativo.ticker} — {_rotulo_alerta(alerta.tipo_alerta)}",
            "mensagem": formatar_mensagem(alerta, ativo.ticker),
            "ativo_id": alerta.ativo_id,
            "evento_id": f"alerta:{alerta.id}",
            "dados": {
                "ticker": ativo.ticker,
                "tipo_ativo": tipo_ativo,
                "indicador": alerta.indicador,
                "tipo_alerta": alerta.tipo_alerta,
                "severidade": alerta.severidade,
                "regra": alerta.regra,
                "data_referencia": (
                    str(alerta.data_referencia) if alerta.data_referencia else None
                ),
                "valor_anterior": _para_float(alerta.valor_anterior),
                "valor_atual": _para_float(alerta.valor_atual),
                "variacao_percentual": _para_float(alerta.variacao_percentual),
                "origem": alerta.origem,
            },
        }
        resumo = processar_evento(evento, session=session)
        logger.info(
            "FASE4 notificações individuais alerta=%s ativo=%s "
            "elegiveis=%s geradas=%s",
            alerta.id, ativo.ticker, resumo["elegiveis"], resumo["geradas"],
        )
    except Exception as e:
        logger.warning(
            "FASE4 notificações individuais falharam sem impedir o fluxo "
            "alerta=%s ativo=%s: %s",
            alerta.id, ativo.ticker, e,
        )


# ===========================================================================
# API PÚBLICA (genérica para AÇÕES e FIIs)
# ===========================================================================

def processar_indicadores_ativo(
    session,
    ativo,
    dados: dict,
    tipo_ativo: str,
    data_referencia: date | None = None,
    origem: str = ORIGEM_GOOGLE_SHEETS,
    log=None,
    notificar: bool = True,
) -> list[AlertaEvento]:
    """Processa todos os indicadores monitorados de um ativo (Fase 4).

    Para cada indicador: classifica a qualidade, detecta mudança em relação ao
    histórico e gera o alerta correspondente (sem alterar os dados originais).
    Erros são isolados por indicador (um problema não derruba os demais).
    Retorna a lista de alertas gerados nesta execução.
    """
    alertas_gerados: list[AlertaEvento] = []
    indicadores = INDICADORES_POR_TIPO.get(tipo_ativo, ())
    logger_efetivo = log or logger

    for indicador in indicadores:
        valor = dados.get(indicador)
        if valor is None:
            continue
        try:
            mudanca = detectar_mudanca(
                session, ativo, tipo_ativo, indicador, valor, data_referencia, origem
            )
            alerta = gerar_alerta(
                session, ativo, tipo_ativo, indicador, valor, mudanca, data_referencia, origem
            )
            if alerta is None:
                continue
            if notificar:
                notificar_telegram(alerta, ativo.ticker)
                notificar_individual(session, alerta, ativo, tipo_ativo)
            alertas_gerados.append(alerta)
            logger_efetivo.info(
                "FASE4 alerta=%s ativo=%s tipo=%s indicador=%s regra=%s "
                "anterior=%s atual=%s variacao=%s origem=%s",
                alerta.tipo_alerta, ativo.ticker, tipo_ativo, indicador,
                alerta.regra, alerta.valor_anterior, alerta.valor_atual,
                alerta.variacao_percentual, origem,
            )
        except Exception as e:
            logger_efetivo.warning(
                "FASE4 falha ao processar indicador=%s ativo=%s: %s",
                indicador, ativo.ticker, e,
            )
            continue

    return alertas_gerados
