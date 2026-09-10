"""Motor de qualidade, detecção de mudanças e alertas — Fase 4 + Etapa 10.4.

Implementa a camada de inteligência determinística do Estratégia Financeira
para AÇÕES e FUNDOS IMOBILIÁRIOS de forma genérica (um único motor):

    EVENTO -> VALIDAR DADO -> RELEVÂNCIA -> PRIORIDADE
           -> PREFERÊNCIAS/FREQUÊNCIA -> DEDUPLICAÇÃO
           -> DISPATCHER -> Telegram individual

A arquitetura é única para ambos os tipos de ativo, baseada em
``tipo_ativo + ativo + indicador + valor + histórico + regra + severidade``,
permitindo que novos tipos de ativo sejam adicionados depois apenas com um
novo catálogo de regras (pipeline_dados.regras_indicadores).

Garantias:
- Negativo legítimo (ROE, margens, dívida líquida, LPA etc.) NÃO gera erro.
- O valor original nunca é alterado para silenciar um alerta.
- Sem histórico (primeira observação) não há alerta de mercado; o valor é
  registrado para comparações futuras.
- Sem alteração de valor, nada é re-armazenado e nenhum alerta de mercado
  é emitido.
- Alertas pequenos não disparam: apenas variações acima dos limiares da regra.
- AUSENTE / INVALIDO / NAO_APLICAVEL nunca viram evento financeiro positivo.
- Alertas repetidos do mesmo evento (mesmo ativo, indicador, tipo, regra e
  valores) não são re-gerados.
- Prioridade CRITICO/ALTO/MEDIO/BAIXO é determinística (sem LLM).
- Alertas individuais não usam ``TELEGRAM_CHAT_ID`` (Etapa 10.3): a entrega
  privada é o dispatcher via ``Usuario.telegram_chat_id``.
- Preferências e frequência da Etapa 10.3 continuam no motor de notificações.
- Todos os eventos ficam em ``alertas_eventos``.
"""
import logging
from datetime import date, datetime
from decimal import Decimal

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
from pipeline_dados.semantica_indicadores import (
    AUSENTE,
    INVALIDO,
    NAO_APLICAVEL,
    PRESENTE,
    ZERO,
    classificar_semantica,
)

logger = logging.getLogger(__name__)

TIPO_QUALIDADE = "QUALIDADE"
TIPO_MERCADO = "MERCADO"
TIPO_CRITICO = "CRITICO"

PRIORIDADE_CRITICO = "CRITICO"
PRIORIDADE_ALTO = "ALTO"
PRIORIDADE_MEDIO = "MEDIO"
PRIORIDADE_BAIXO = "BAIXO"
PRIORIDADES_VALIDAS = (
    PRIORIDADE_CRITICO,
    PRIORIDADE_ALTO,
    PRIORIDADE_MEDIO,
    PRIORIDADE_BAIXO,
)

MOTIVO_IRRELEVANTE = "evento_irrelevante"
MOTIVO_SEMANTICA = "semantica_nao_utilizavel"
MOTIVO_FRESHNESS = "freshness_incompativel"
MOTIVO_SEM_MUDANCA = "sem_mudanca_relevante"
MOTIVO_DUPLICADO = "alerta_repetido"
MOTIVO_IGNORADO_CLASSIFICACAO = "classificacao_ignorada"

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
# VALIDAÇÃO DE DADO / RELEVÂNCIA / PRIORIDADE (Etapa 10.4)
# ===========================================================================

def _variacao_fracao(mudanca: dict) -> float:
    """Converte ``variacao_percentual`` (ex.: 16.51) em fração (0.1651)."""
    variacao_pct = mudanca.get("variacao_percentual") if mudanca else None
    if variacao_pct is None:
        return 0.0
    return abs(float(variacao_pct)) / 100.0


def _freshness_do_historico(session, ativo, indicador: str, agora=None) -> str | None:
    """FRESH/STALE/MISSING do histórico do indicador, ou None sem registro.

    Reusa ``pipeline_dados.freshness`` (SLA de preço vs indicadores de mercado).
    Sem histórico ainda não há dado para recusar por staleness.
    """
    from pipeline_dados.freshness import (
        INDICADORES_MERCADO,
        PRECO,
        classificar,
        dado_utilizavel,
        sla_da_categoria,
    )

    registro = (
        session.query(IndicadorHistorico)
        .filter_by(ativo_id=ativo.id, indicador=indicador)
        .first()
    )
    if registro is None:
        return None
    categoria = PRECO if indicador == "preco" else INDICADORES_MERCADO
    return classificar(
        registro.ultima_coleta,
        sla_da_categoria(categoria),
        agora=agora,
        utilizavel=dado_utilizavel(registro.valor_atual),
    )


def avaliar_dado(tipo_ativo: str, indicador: str, valor) -> dict:
    """Valida o valor bruto sem inventar número nem evento financeiro.

    Distingue PRESENTE / ZERO / AUSENTE / NAO_APLICAVEL / INVALIDO.
    AUSENTE e INVALIDO nunca viram evento financeiro positivo.
    """
    classificacao = classificar_indicador(tipo_ativo, indicador, valor)
    semantica = classificacao.get("semantica") or classificar_semantica(valor)
    utilizavel = semantica in (PRESENTE, ZERO)
    recusar = semantica in (AUSENTE, INVALIDO, NAO_APLICAVEL)
    return {
        "semantica": semantica,
        "utilizavel": utilizavel,
        "recusar": recusar,
        "classificacao": classificacao,
        "regra": classificacao.get("regra"),
        "severidade": classificacao.get("severidade"),
    }


def classificar_prioridade(
    tipo_alerta: str,
    classificacao: dict,
    mudanca: dict,
) -> str:
    """Prioridade determinística CRITICO / ALTO / MEDIO / BAIXO.

    Critérios objetivos (somente dados já existentes no motor):

    - CRITICO: qualidade crítica (valor implausível) OU variação acima do
      limiar crítico da regra do indicador.
    - ALTO: qualidade ERRO (valor impossível, ex. preço negativo).
    - MEDIO: variação de mercado acima do limiar da regra (dado provavelmente
      real) OU qualidade WARNING com mudança de valor.
    - BAIXO: qualidade WARNING sem mudança de valor (dado suspeito persistente).
    """
    severidade = (classificacao or {}).get("severidade")
    mudou = bool(mudanca and mudanca.get("mudou"))
    variacao_frac = _variacao_fracao(mudanca or {})
    limite_crit = float((mudanca or {}).get("limite_variacao_critica_pct") or 0.50)

    if tipo_alerta == TIPO_CRITICO or severidade == CRITICO:
        return PRIORIDADE_CRITICO
    if mudou and variacao_frac >= limite_crit:
        return PRIORIDADE_CRITICO
    if tipo_alerta == TIPO_QUALIDADE and severidade == ERRO:
        return PRIORIDADE_ALTO
    if tipo_alerta == TIPO_MERCADO:
        return PRIORIDADE_MEDIO
    if tipo_alerta == TIPO_QUALIDADE and mudou:
        return PRIORIDADE_MEDIO
    return PRIORIDADE_BAIXO


def evento_relevante(
    tipo_alerta: str | None,
    classificacao: dict,
    mudanca: dict,
    semantica: str | None = None,
    freshness: str | None = None,
) -> tuple[bool, str | None]:
    """True somente quando o evento representa mudança relevante e utilizável.

    Recusa:
    - classificação IGNORADO (sem regra aplicável);
    - AUSENTE / INVALIDO / NAO_APLICAVEL (nunca evento financeiro positivo);
    - dado STALE/MISSING (freshness incompatível), salvo alerta CRITICO de
      qualidade já classificado no valor atual;
    - ausência de tipo de alerta (variação abaixo do limiar / sem mudança).
    ZERO real permanece utilizável (não é ausência).
    """
    if semantica in (AUSENTE, INVALIDO, NAO_APLICAVEL):
        return False, MOTIVO_SEMANTICA
    if (classificacao or {}).get("severidade") == "IGNORADO":
        return False, MOTIVO_IGNORADO_CLASSIFICACAO
    if tipo_alerta is None:
        return False, MOTIVO_IRRELEVANTE
    if freshness in ("STALE", "MISSING") and tipo_alerta != TIPO_CRITICO:
        return False, MOTIVO_FRESHNESS
    if tipo_alerta == TIPO_MERCADO and not (mudanca or {}).get("mudou"):
        return False, MOTIVO_SEM_MUDANCA
    return True, None


def chave_deduplicacao(ativo_id, indicador: str, tipo_alerta: str, regra: str, valor_atual) -> tuple:
    """Identidade do evento para recusar repetição sem mudança relevante."""
    valor_norm = None
    decimal_atual = _decimal(valor_atual)
    if decimal_atual is not None:
        valor_norm = decimal_atual.quantize(Decimal("0.00000001"))
    return (ativo_id, indicador, tipo_alerta, regra, valor_norm)


def alerta_duplicado(session, ativo, indicador: str, tipo_alerta: str, regra: str, valor) -> bool:
    """True se já existe ``AlertaEvento`` equivalente (mesmo evento, mesmo valor).

    Compara o último alerta do par ``(ativo, indicador)``. Repetir a mesma
    classificação com o mesmo valor atual é ruído; mudança de valor, regra ou
    tipo gera um evento novo. Alertas críticos também são deduplicados quando
    o valor não mudou — a preservação do crítico é não silenciar a primeira
    ocorrência nem variações novas acima do limiar crítico.
    """
    anterior = (
        session.query(AlertaEvento)
        .filter_by(ativo_id=ativo.id, indicador=indicador)
        .order_by(AlertaEvento.id.desc())
        .first()
    )
    if anterior is None:
        return False
    return chave_deduplicacao(
        ativo.id, indicador, tipo_alerta, regra, valor
    ) == chave_deduplicacao(
        anterior.ativo_id,
        anterior.indicador,
        anterior.tipo_alerta,
        anterior.regra,
        anterior.valor_atual,
    )


def decidir_alerta(
    session,
    ativo,
    tipo_ativo: str,
    indicador: str,
    valor,
    mudanca: dict,
    agora=None,
    freshness=None,
) -> dict:
    """Pipeline determinístico: dado -> relevância -> prioridade -> dedup.

    Não consulta preferências (Etapa 10.3 permanece na camada de notificação).
    Não publica nem persiste: só decide se o ``AlertaEvento`` deve nascer.
    ``freshness`` deve ser lido ANTES de ``detectar_mudanca`` atualizar
    ``ultima_coleta``; se omitido, é consultado no histórico atual.
    """
    avaliacao = avaliar_dado(tipo_ativo, indicador, valor)
    classificacao = avaliacao["classificacao"]
    tipo_alerta = _tipo_alerta_candidato(classificacao, mudanca)
    if freshness is None:
        freshness = _freshness_do_historico(session, ativo, indicador, agora=agora)
    relevante, motivo_irrelevante = evento_relevante(
        tipo_alerta,
        classificacao,
        mudanca,
        semantica=avaliacao["semantica"],
        freshness=freshness,
    )
    prioridade = (
        classificar_prioridade(tipo_alerta, classificacao, mudanca)
        if tipo_alerta
        else None
    )
    duplicado = False
    if relevante and tipo_alerta is not None:
        duplicado = alerta_duplicado(
            session, ativo, indicador, tipo_alerta, classificacao.get("regra"), valor
        )
        if duplicado:
            relevante = False
            motivo_irrelevante = MOTIVO_DUPLICADO
    return {
        "avaliacao": avaliacao,
        "classificacao": classificacao,
        "tipo_alerta": tipo_alerta,
        "prioridade": prioridade,
        "freshness": freshness,
        "relevante": relevante,
        "motivo_irrelevante": motivo_irrelevante,
        "duplicado": duplicado,
        "semantica": avaliacao["semantica"],
    }


def _tipo_alerta_candidato(classificacao: dict, mudanca: dict) -> str | None:
    """Tipo QUALIDADE/MERCADO/CRITICO a partir da classificação e da mudança.

    Mesma prioridade histórica de ``gerar_alerta`` (Fase 4), isolada para
    decisão de relevância antes da persistência.
    """
    if classificacao.get("severidade") == "IGNORADO":
        return None
    variacao_frac = _variacao_fracao(mudanca)
    limite_var = float(mudanca.get("limite_variacao_pct") or 0.20)
    limite_crit = float(mudanca.get("limite_variacao_critica_pct") or 0.50)
    severidade = classificacao.get("severidade")
    if severidade == CRITICO:
        return TIPO_CRITICO
    if severidade == ERRO:
        return TIPO_QUALIDADE
    if mudanca.get("mudou") and variacao_frac >= limite_crit:
        return TIPO_CRITICO
    if severidade == WARNING:
        return TIPO_QUALIDADE
    if mudanca.get("mudou") and variacao_frac >= limite_var:
        return TIPO_MERCADO
    return None


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
    decisao: dict | None = None,
) -> AlertaEvento | None:
    """Classifica a ocorrência e, se relevante, persiste um ``AlertaEvento``.

    Fluxo 10.4 (determinístico, sem LLM):
    validação do dado -> relevância -> prioridade -> deduplicação.

    Tipo de alerta (legado Fase 4, preservado):
    1. CRITICO: qualidade crítica (valor implausível) ou variação acima do
       limiar crítico;
    2. QUALIDADE: valor com WARNING/ERRO (possível dado incorreto);
    3. MERCADO: variação relevante acima do limiar da regra (dado provavelmente
       real).

    Na primeira observação (sem histórico) e sem mudança de valor, nenhum
    alerta de mercado é emitido; um problema de qualidade, porém, é sinalizado
    uma vez (dedup evita repetição do mesmo valor).
    AUSENTE/INVALIDO/NAO_APLICAVEL nunca geram evento financeiro positivo.
    """
    if decisao is None:
        decisao = decidir_alerta(session, ativo, tipo_ativo, indicador, valor, mudanca)
    if not decisao.get("relevante"):
        return None

    classificacao = decisao["classificacao"]
    tipo_alerta = decisao["tipo_alerta"]
    variacao_pct = mudanca["variacao_percentual"]
    if tipo_alerta == TIPO_MERCADO or (
        tipo_alerta == TIPO_CRITICO and mudanca.get("mudou")
        and classificacao.get("severidade") != CRITICO
    ):
        motivo = _motivo_mudanca(classificacao, variacao_pct)
    else:
        motivo = classificacao.get("motivo") or _motivo_mudanca(classificacao, variacao_pct)

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
        severidade=classificacao["severidade"],
        recomendacao=_recomendacao(tipo_alerta),
        origem=origem,
        data_referencia=data_referencia,
        data_evento=datetime.now(),
        telegram_enviado=False,
    )
    session.add(alerta)
    alerta._prioridade = decisao.get("prioridade")
    alerta._semantica = decisao.get("semantica")
    alerta._freshness = decisao.get("freshness")
    return alerta


# ===========================================================================
# MENSAGEM PARA O TELEGRAM
# ===========================================================================

def _fmt_numero_alerta(valor) -> str:
    if valor is None:
        return "-"
    numero = float(valor)
    if abs(numero) >= 1000:
        return f"{numero:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{numero:.4f}".rstrip("0").rstrip(".")


def _rotulo_alerta(tipo_alerta: str) -> str:
    """Rotulo unico do tipo (titulo e corpo da mensagem)."""
    return {
        TIPO_MERCADO: "ALERTA DE MERCADO",
        TIPO_QUALIDADE: "ALERTA DE QUALIDADE",
        TIPO_CRITICO: "ALERTA CRITICO",
    }.get(tipo_alerta, "ALERTA")


def _nome_indicador(tipo_ativo: str, indicador: str) -> str:
    regra = obter_regra(tipo_ativo, indicador)
    if regra is None:
        return indicador
    if regra.nome_exibicao and regra.nome_exibicao != indicador:
        return f"{regra.nome_exibicao} ({indicador})"
    return indicador


def formatar_mensagem(alerta: AlertaEvento, ticker: str) -> str:
    """Monta a mensagem objetiva do alerta para o Telegram.

    Inclui apenas dados ja existentes no evento: ativo, tipo, indicador,
    valores, variacao, motivo, severidade, prioridade, data, origem e
    freshness. Nao inventa numero, data nem estado de dado.
    """
    marca = {"MERCADO": "*", "QUALIDADE": "!", "CRITICO": "!!"}.get(alerta.tipo_alerta, "-")
    rotulo = _rotulo_alerta(alerta.tipo_alerta)
    prioridade = getattr(alerta, "_prioridade", None)
    freshness = getattr(alerta, "_freshness", None)

    linhas = [
        f"{marca} {rotulo}",
        "",
        f"Ativo: {ticker}",
        f"Tipo: {alerta.tipo_ativo}",
        f"Indicador: {_nome_indicador(alerta.tipo_ativo, alerta.indicador)}",
    ]
    if alerta.valor_anterior is not None:
        linhas.append(f"Anterior: {_fmt_numero_alerta(alerta.valor_anterior)}")
    linhas.append(f"Atual: {_fmt_numero_alerta(alerta.valor_atual)}")
    if alerta.variacao_percentual is not None:
        linhas.append(f"Variacao: {_fmt_numero_alerta(alerta.variacao_percentual)}%")
    linhas.append("")
    linhas.append(f"Motivo: {alerta.motivo}")
    linhas.append(f"Severidade: {alerta.severidade}")
    if prioridade:
        linhas.append(f"Prioridade: {prioridade}")
    if alerta.data_referencia is not None:
        linhas.append(f"Data: {alerta.data_referencia.isoformat()}")
    if alerta.origem:
        linhas.append(f"Origem: {alerta.origem}")
    if freshness:
        linhas.append(f"Freshness: {freshness}")
    if alerta.recomendacao:
        linhas.append("")
        linhas.append(alerta.recomendacao)
    return "\n".join(linhas)


def notificar_telegram(alerta: AlertaEvento, ticker: str) -> bool:
    """Não envia alerta individual ao ``TELEGRAM_CHAT_ID`` (Etapa 10.3).

    Alertas privados seguem o caminho C: ``notificar_individual`` ->
    ``services.notificacoes`` -> dispatcher -> ``Usuario.telegram_chat_id``.
    ``TELEGRAM_CHAT_ID`` permanece só para mensagens OPERACIONAIS (orquestrador,
    varredura). Esta função não faz fan-out: retorna ``False`` sem marcar
    ``telegram_enviado``.
    """
    logger.info(
        "Alerta individual %s/%s não usa TELEGRAM_CHAT_ID; entrega via dispatcher.",
        ticker,
        getattr(alerta, "indicador", None),
    )
    return False


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
    ``ALERTA_MERCADO`` publicado via ``services.publicador_eventos.publicar_evento``
    (Fase 7, Etapa 7.7) — a interface de publicação de eventos do Financial Core.
    O publicador chama ``services.notificacoes.processar_evento``, que decide os
    usuários elegíveis (permissão central, acompanhamento do ativo, preferência,
    limite do plano e canais) e persiste as notificações individualizadas de
    forma idempotente. O fan-out legado para ``TELEGRAM_CHAT_ID`` não ocorre
    (Etapa 10.3): alertas individuais não vão ao chat do operador. Erros são
    isolados no publicador: uma falha aqui nunca derruba o espelhamento 5C
    nem a detecção de alertas.
    """
    from services.publicador_eventos import publicar_evento

    session.flush()
    prioridade = getattr(alerta, "_prioridade", None)
    freshness = getattr(alerta, "_freshness", None)
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
            "prioridade": prioridade,
            "freshness": freshness,
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
    publicar_evento(evento, session=session)


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
            avaliacao = avaliar_dado(tipo_ativo, indicador, valor)
            if avaliacao["recusar"]:
                logger_efetivo.info(
                    "FASE4 dado recusado semantica=%s ativo=%s indicador=%s",
                    avaliacao["semantica"], ativo.ticker, indicador,
                )
                continue
            freshness = _freshness_do_historico(session, ativo, indicador)
            mudanca = detectar_mudanca(
                session, ativo, tipo_ativo, indicador, valor, data_referencia, origem
            )
            decisao = decidir_alerta(
                session, ativo, tipo_ativo, indicador, valor, mudanca,
                freshness=freshness,
            )
            alerta = gerar_alerta(
                session, ativo, tipo_ativo, indicador, valor, mudanca,
                data_referencia, origem, decisao=decisao,
            )
            if alerta is None:
                continue
            if notificar:
                notificar_individual(session, alerta, ativo, tipo_ativo)
            alertas_gerados.append(alerta)
            logger_efetivo.info(
                "FASE4 alerta=%s prioridade=%s ativo=%s tipo=%s indicador=%s regra=%s "
                "anterior=%s atual=%s variacao=%s origem=%s",
                alerta.tipo_alerta, decisao.get("prioridade"), ativo.ticker,
                tipo_ativo, indicador, alerta.regra, alerta.valor_anterior,
                alerta.valor_atual, alerta.variacao_percentual, origem,
            )
        except Exception as e:
            logger_efetivo.warning(
                "FASE4 falha ao processar indicador=%s ativo=%s: %s",
                indicador, ativo.ticker, e,
            )
            continue

    return alertas_gerados
