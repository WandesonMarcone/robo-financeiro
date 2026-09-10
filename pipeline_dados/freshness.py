"""Freshness e SLA dos dados — Fase 8, Etapa 8.4.

Camada única para classificar se um dado está FRESH, STALE ou MISSING.
Não altera o significado de ``data_referencia`` já persistido:

- snapshots: ``data_referencia`` continua sendo o dia da coleta em São Paulo;
- dados contábeis: ``data_referencia`` continua sendo a competência CVM;
- documentos: ``data_publicacao`` continua sendo a data do documento.

A idade do dado usa ``data_coleta`` (quando existe). Ausência de coleta não é
substituída por data de referência: nesse caso o status é avaliado só se houver
``data_coleta``; senão o registro legado sem coleta é STALE se o valor existe
e a competência já ultrapassou o SLA, MISSING se não há valor utilizável.

Zero real (0.0) é dado válido. None/NaN/Inf não são utilizáveis (8.2).
"""
from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from pipeline_dados.banco_dados import (
    DadosFinanceirosAcoes,
    DadosFinanceirosFiis,
    DocumentosQualitativos,
    IndicadorHistorico,
    SnapshotAcao,
    SnapshotFii,
)
from pipeline_dados.numerico import coerir_numero

FRESH = "FRESH"
STALE = "STALE"
MISSING = "MISSING"

STATUS_VALIDOS = (FRESH, STALE, MISSING)

PRECO = "preco"
INDICADORES_MERCADO = "indicadores_mercado"
CONTABIL = "contabil"
DOCUMENTOS = "documentos"
DADOS_FII = "dados_fii"

CATEGORIAS = (PRECO, INDICADORES_MERCADO, CONTABIL, DOCUMENTOS, DADOS_FII)

FONTE_SHEETS = "Google Sheets"
FONTE_CVM = "CVM"
FONTE_FNET = "FNET/B3"

SLA_PRECO = timedelta(hours=2)
SLA_INDICADORES_MERCADO = timedelta(hours=2)
SLA_CONTABIL_ACOES = timedelta(days=120)
SLA_CONTABIL_FIIS = timedelta(days=45)
SLA_DOCUMENTOS = timedelta(days=60)
SLA_DADOS_FII = timedelta(hours=2)

SLA_POR_CATEGORIA = {
    PRECO: SLA_PRECO,
    INDICADORES_MERCADO: SLA_INDICADORES_MERCADO,
    CONTABIL: SLA_CONTABIL_ACOES,
    DOCUMENTOS: SLA_DOCUMENTOS,
    DADOS_FII: SLA_DADOS_FII,
}

_CAMPOS_INDICADORES_FII = (
    "pvp", "dy", "liquidez", "vpa", "lucro_12m", "dividendo_mensal", "qtd_imoveis",
)
_CAMPOS_INDICADORES_ACAO = (
    "dy", "pl", "pvp", "p_ativo", "marg_bruta", "marg_ebit", "marg_liquida",
    "p_ebit", "ev_ebit", "div_liq_ebit", "div_liq_patrimonio", "psr",
    "p_cap_giro", "p_at_circ_liq", "liq_corrente", "roe", "roa", "roic",
    "cagr_rec_5a", "liq_media", "vpa", "lpa", "peg_ratio", "valor_mercado",
)
_CAMPOS_CONTABIL_ACAO = (
    "ativo_total", "patrimonio_liquido", "caixa", "passivo_total",
    "divida_bruta", "receita", "lucro_liquido", "ebitda", "fco",
)
_CAMPOS_CONTABIL_FII = (
    "patrimonio_liquido", "ativo_total", "disponibilidades_caixa",
    "cotistas", "cotas_emitidas", "valor_patrimonial_cotas",
    "percentual_dividend_yield_mes", "receita_imoveis", "despesas_taxas",
)


def sla_da_categoria(categoria, tipo_ativo=None) -> timedelta:
    """SLA da categoria; contábil de FII usa a janela mensal, não a do ITR."""
    if categoria == CONTABIL and tipo_ativo and str(tipo_ativo).upper() == "FII":
        return SLA_CONTABIL_FIIS
    return SLA_POR_CATEGORIA[categoria]


def justificada_sla() -> dict:
    """Política de SLA e a justificativa operacional de cada intervalo."""
    return {
        PRECO: {
            "sla": SLA_PRECO,
            "justificativa": (
                "GitHub Actions roda o scraper 5x em dias úteis (10/12/14/16/18 BRT) "
                "e precisa_atualizar já usa janela de 7200s."
            ),
        },
        INDICADORES_MERCADO: {
            "sla": SLA_INDICADORES_MERCADO,
            "justificativa": (
                "Indicadores de mercado entram no mesmo ciclo do scraper/5C "
                "que o preço (a cada ~2h em dias úteis)."
            ),
        },
        CONTABIL: {
            "sla_acoes": SLA_CONTABIL_ACOES,
            "sla_fiis": SLA_CONTABIL_FIIS,
            "justificativa": (
                "ITR é trimestral (coleta CVM 1x/dia útil às 08:00 BRT). "
                "INF_MENSAL de FII é mensal e hoje só roda via /forcar_fiis."
            ),
        },
        DOCUMENTOS: {
            "sla": SLA_DOCUMENTOS,
            "justificativa": (
                "FNET/B3 varre 60 dias de documentos 1x/dia útil às 08:00 BRT; "
                "publicação é dirigida a evento, não a pregão."
            ),
        },
        DADOS_FII: {
            "sla": SLA_DADOS_FII,
            "justificativa": (
                "Snapshot de mercado do FII segue o mesmo ciclo 5C/scraper de 2h."
            ),
        },
    }


def dado_utilizavel(valor) -> bool:
    """True para valor presente e finito, inclusive zero real."""
    if valor is None:
        return False
    if isinstance(valor, Decimal):
        return bool(valor.is_finite())
    if isinstance(valor, bool):
        return False
    if isinstance(valor, (int, float)):
        return math.isfinite(float(valor))
    if isinstance(valor, str):
        texto = valor.strip()
        if not texto:
            return False
        numero, motivo = coerir_numero(texto)
        if motivo is None and numero is not None:
            return True
        return True
    numero, motivo = coerir_numero(valor)
    if motivo is not None:
        return False
    return numero is not None


def _como_datetime(valor) -> datetime | None:
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.replace(tzinfo=None) if valor.tzinfo else valor
    if isinstance(valor, date):
        return datetime.combine(valor, time.min)
    return None


def classificar(coletado_em, sla: timedelta, agora=None, utilizavel=True) -> str:
    """FRESH/STALE/MISSING a partir da coleta e do SLA.

    ``data_referencia`` não entra no cálculo — só ``coletado_em``.
    """
    if not utilizavel:
        return MISSING
    momento = _como_datetime(coletado_em)
    if momento is None:
        return STALE
    agora_dt = _como_datetime(agora) or datetime.now()
    if agora_dt - momento <= sla:
        return FRESH
    return STALE


def url_origem_segura(url) -> str | None:
    """Persiste URL só quando o coletor de fato a utilizou. Nunca inventa."""
    if url is None:
        return None
    texto = str(url).strip()
    if not texto:
        return None
    if not (texto.startswith("http://") or texto.startswith("https://")):
        return None
    return texto


def proveniencia(fonte_primaria=None, fonte_intermediaria=None, url_origem=None, fonte=None) -> dict:
    """Proveniência explícita; ausência permanece None."""
    primaria = str(fonte_primaria).strip() if fonte_primaria else None
    intermediaria = str(fonte_intermediaria).strip() if fonte_intermediaria else None
    legado = str(fonte).strip() if fonte else None
    return {
        "fonte": legado,
        "fonte_primaria": primaria or None,
        "fonte_intermediaria": intermediaria or None,
        "url_origem": url_origem_segura(url_origem),
    }


def _primeiro_utilizavel(registro, campos) -> bool:
    for campo in campos:
        if dado_utilizavel(getattr(registro, campo, None)):
            return True
    return False


def _coleta_do_registro(registro) -> datetime | None:
    for attr in ("data_coleta", "ultima_coleta", "data_atualizacao"):
        valor = getattr(registro, attr, None)
        momento = _como_datetime(valor)
        if momento is not None:
            return momento
    return None


def _snapshot_mais_recente(session, ativo_id, tipo):
    modelo = SnapshotFii if tipo == "FII" else SnapshotAcao
    return (
        session.query(modelo)
        .filter(modelo.ativo_id == ativo_id)
        .order_by(modelo.data_referencia.desc(), modelo.id.desc())
        .first()
    )


def _contabil_mais_recente(session, ativo_id, tipo):
    modelo = DadosFinanceirosFiis if tipo == "FII" else DadosFinanceirosAcoes
    return (
        session.query(modelo)
        .filter(modelo.ativo_id == ativo_id)
        .order_by(modelo.data_referencia.desc(), modelo.id.desc())
        .first()
    )


def _documento_mais_recente(session, ativo_id):
    return (
        session.query(DocumentosQualitativos)
        .filter(DocumentosQualitativos.ativo_id == ativo_id)
        .order_by(
            DocumentosQualitativos.data_atualizacao.desc(),
            DocumentosQualitativos.data_publicacao.desc(),
            DocumentosQualitativos.id.desc(),
        )
        .first()
    )


def _montar_estado(
    categoria,
    registro,
    status,
    agora,
    sla,
    valor=None,
    extra=None,
) -> dict:
    coleta = _coleta_do_registro(registro) if registro is not None else None
    data_ref = getattr(registro, "data_referencia", None) if registro is not None else None
    if registro is not None and hasattr(registro, "data_publicacao") and categoria == DOCUMENTOS:
        data_ref = registro.data_publicacao
    estado = {
        "categoria": categoria,
        "status": status,
        "valor": valor,
        "data_referencia": data_ref,
        "data_coleta": coleta,
        "sla": sla,
        "avaliado_em": _como_datetime(agora) or datetime.now(),
        "fonte": getattr(registro, "fonte", None) if registro is not None else None,
        "fonte_primaria": getattr(registro, "fonte_primaria", None) if registro is not None else None,
        "fonte_intermediaria": getattr(registro, "fonte_intermediaria", None) if registro is not None else None,
        "url_origem": url_origem_segura(
            getattr(registro, "url_origem", None) if registro is not None else None
        ),
        "origem": getattr(registro, "origem", None) if registro is not None else None,
    }
    if extra:
        estado.update(extra)
    return estado


def avaliar_preco(snapshot, tipo="FII", agora=None) -> dict:
    sla = sla_da_categoria(PRECO, tipo)
    if snapshot is None:
        return _montar_estado(PRECO, None, MISSING, agora, sla)
    utilizavel = dado_utilizavel(snapshot.preco)
    status = classificar(_coleta_do_registro(snapshot), sla, agora, utilizavel)
    return _montar_estado(PRECO, snapshot, status, agora, sla, valor=snapshot.preco)


def avaliar_indicadores_mercado(snapshot, tipo="FII", agora=None) -> dict:
    sla = sla_da_categoria(INDICADORES_MERCADO, tipo)
    if snapshot is None:
        return _montar_estado(INDICADORES_MERCADO, None, MISSING, agora, sla)
    campos = _CAMPOS_INDICADORES_FII if tipo == "FII" else _CAMPOS_INDICADORES_ACAO
    utilizavel = _primeiro_utilizavel(snapshot, campos)
    status = classificar(_coleta_do_registro(snapshot), sla, agora, utilizavel)
    return _montar_estado(INDICADORES_MERCADO, snapshot, status, agora, sla)


def avaliar_contabil(registro, tipo="FII", agora=None) -> dict:
    sla = sla_da_categoria(CONTABIL, tipo)
    if registro is None:
        return _montar_estado(CONTABIL, None, MISSING, agora, sla)
    campos = _CAMPOS_CONTABIL_FII if tipo == "FII" else _CAMPOS_CONTABIL_ACAO
    utilizavel = _primeiro_utilizavel(registro, campos)
    status = classificar(_coleta_do_registro(registro), sla, agora, utilizavel)
    return _montar_estado(CONTABIL, registro, status, agora, sla)


def avaliar_documentos(documento, agora=None) -> dict:
    sla = sla_da_categoria(DOCUMENTOS)
    if documento is None:
        return _montar_estado(DOCUMENTOS, None, MISSING, agora, sla)
    coleta = _coleta_do_registro(documento) or _como_datetime(documento.data_publicacao)
    status = classificar(coleta, sla, agora, utilizavel=True)
    extra = {"data_publicacao": documento.data_publicacao}
    estado = _montar_estado(DOCUMENTOS, documento, status, agora, sla, extra=extra)
    estado["data_coleta"] = coleta
    return estado


def avaliar_dados_fii(snapshot, agora=None) -> dict:
    sla = sla_da_categoria(DADOS_FII, "FII")
    if snapshot is None:
        return _montar_estado(DADOS_FII, None, MISSING, agora, sla)
    utilizavel = dado_utilizavel(snapshot.preco) or _primeiro_utilizavel(
        snapshot, _CAMPOS_INDICADORES_FII
    )
    status = classificar(_coleta_do_registro(snapshot), sla, agora, utilizavel)
    return _montar_estado(DADOS_FII, snapshot, status, agora, sla, valor=snapshot.preco)


def avaliar_ativo(session, ativo, agora=None) -> dict:
    """Freshness independente por categoria para um ``Ativo`` persistido."""
    tipo = ativo.tipo.value if hasattr(ativo.tipo, "value") else str(ativo.tipo)
    snapshot = _snapshot_mais_recente(session, ativo.id, tipo)
    contabil = _contabil_mais_recente(session, ativo.id, tipo)
    documento = _documento_mais_recente(session, ativo.id)
    categorias = {
        PRECO: avaliar_preco(snapshot, tipo, agora),
        INDICADORES_MERCADO: avaliar_indicadores_mercado(snapshot, tipo, agora),
        CONTABIL: avaliar_contabil(contabil, tipo, agora),
        DOCUMENTOS: avaliar_documentos(documento, agora),
    }
    if tipo == "FII":
        categorias[DADOS_FII] = avaliar_dados_fii(snapshot, agora)
    return {
        "ticker": ativo.ticker,
        "tipo": tipo,
        "categorias": categorias,
    }


def avaliar_indicador_historico(registro: IndicadorHistorico | None, agora=None) -> dict:
    sla = SLA_INDICADORES_MERCADO
    if registro is None:
        return _montar_estado(INDICADORES_MERCADO, None, MISSING, agora, sla)
    utilizavel = dado_utilizavel(registro.valor_atual)
    status = classificar(registro.ultima_coleta, sla, agora, utilizavel)
    return _montar_estado(
        INDICADORES_MERCADO,
        registro,
        status,
        agora,
        sla,
        valor=registro.valor_atual,
    )
