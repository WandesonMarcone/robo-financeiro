"""Cobertura do universo cadastrado — Fase 8, Etapa 8.4.

Mede o que deveria ser coletado versus o que de fato foi coletado.
Não expande o universo: o catálogo (`ativos_catalogo` / MAPA_*) é a referência
declarativa; a coleta de mercado continua limitada pela planilha + filas
FIXAS/opps/novatos/aleatorios.

Uma execução parcial (amostra) nunca é cobertura total.
"""
from __future__ import annotations

from datetime import date, datetime

import config
from pipeline_dados.banco_dados import (
    Ativo,
    DadosFinanceirosAcoes,
    DadosFinanceirosFiis,
    DocumentosQualitativos,
    SnapshotAcao,
    SnapshotFii,
    TipoAtivo,
)
from pipeline_dados.catalogo_ativos import listar_tickers_catalogo
from pipeline_dados.freshness import (
    CONTABIL,
    DADOS_FII,
    DOCUMENTOS,
    FRESH,
    INDICADORES_MERCADO,
    MISSING,
    PRECO,
    STALE,
    avaliar_ativo,
)

FILA_FIXAS = "fixas"
FILA_OPORTUNIDADES = "oportunidades"
FILA_NOVATOS = "novatos"
FILA_ALEATORIOS = "aleatorios"
FILA_PLANILHA = "planilha"

LIMITE_NOVATOS_FII = 3
LIMITE_DESATUALIZADAS_FII = 2
LIMITE_OPPS_ACAO = 5
LIMITE_NOVATAS_ACAO = 2
LIMITE_ALEATORIAS_ACAO = 3


def _tipo_valor(tipo) -> str:
    if isinstance(tipo, TipoAtivo):
        return tipo.value
    return str(tipo).strip().upper()


def tickers_catalogo(session, tipo=None) -> list[str]:
    """Universo cadastrado (catálogo PostgreSQL, semeado se vazio)."""
    if tipo is not None:
        return listar_tickers_catalogo(session, tipo)
    fiis = listar_tickers_catalogo(session, TipoAtivo.FII)
    acoes = listar_tickers_catalogo(session, TipoAtivo.ACAO)
    return sorted(set(fiis) | set(acoes))


def contar_universo(session) -> dict:
    """Quantidade de FIIs e ações no catálogo (referência, não a coleta)."""
    fiis = tickers_catalogo(session, TipoAtivo.FII)
    acoes = tickers_catalogo(session, TipoAtivo.ACAO)
    return {
        "fiis_catalogo": len(fiis),
        "acoes_catalogo": len(acoes),
        "total_catalogo": len(fiis) + len(acoes),
        "fiis_fixas": len(config.FIXAS_FIIS),
        "acoes_fixas": len(config.FIXAS_ACOES),
        "mapa_iscas": len(config.MAPA_ISCAS_MASTER),
        "mapa_cnpj_b3": len(config.MAPA_CNPJ_B3),
    }


def capacidade_por_execucao() -> dict:
    """Teto amostral de uma execução de scraper (não é o universo)."""
    fiis = len(config.FIXAS_FIIS) + LIMITE_NOVATOS_FII + LIMITE_DESATUALIZADAS_FII
    acoes = (
        len(config.FIXAS_ACOES)
        + LIMITE_OPPS_ACAO
        + LIMITE_ALEATORIAS_ACAO
        + LIMITE_NOVATAS_ACAO
    )
    return {
        "fiis_por_execucao_max": fiis,
        "acoes_por_execucao_max": acoes,
        "filas_fii": {
            FILA_FIXAS: len(config.FIXAS_FIIS),
            FILA_NOVATOS: LIMITE_NOVATOS_FII,
            FILA_ALEATORIOS: LIMITE_DESATUALIZADAS_FII,
        },
        "filas_acao": {
            FILA_FIXAS: len(config.FIXAS_ACOES),
            FILA_OPORTUNIDADES: LIMITE_OPPS_ACAO,
            FILA_ALEATORIOS: LIMITE_ALEATORIAS_ACAO,
            FILA_NOVATOS: LIMITE_NOVATAS_ACAO,
        },
        "observacao": (
            "A coleta de mercado percorre a planilha + filas amostrais; "
            "não itera MAPA_ISCAS_MASTER/MAPA_CNPJ_B3. Execução parcial "
            "não equivale a cobertura total do catálogo."
        ),
    }


def _tickers_com_snapshot(session, tipo) -> set[str]:
    modelo = SnapshotFii if tipo == "FII" else SnapshotAcao
    linhas = (
        session.query(Ativo.ticker)
        .join(modelo, modelo.ativo_id == Ativo.id)
        .all()
    )
    return {linha[0] for linha in linhas}


def _tickers_com_contabil(session, tipo) -> set[str]:
    modelo = DadosFinanceirosFiis if tipo == "FII" else DadosFinanceirosAcoes
    linhas = (
        session.query(Ativo.ticker)
        .join(modelo, modelo.ativo_id == Ativo.id)
        .all()
    )
    return {linha[0] for linha in linhas}


def _tickers_com_documento(session) -> set[str]:
    linhas = (
        session.query(Ativo.ticker)
        .join(DocumentosQualitativos, DocumentosQualitativos.ativo_id == Ativo.id)
        .all()
    )
    return {linha[0] for linha in linhas}


def _ativos_por_ticker(session, tickers) -> dict:
    if not tickers:
        return {}
    linhas = session.query(Ativo).filter(Ativo.ticker.in_(list(tickers))).all()
    return {ativo.ticker: ativo for ativo in linhas}


def cobertura_tipo(
    session, tipo, categoria=PRECO, agora=None, coletados=None, avaliar_tickers=None
) -> dict:
    """Cobertura de um tipo (FII/ACAO) para uma categoria de dado.

    ``coletados`` é o conjunto realmente processado nesta execução (amostra).
    Sem ele, a cobertura usa o que já está persistido — ainda assim distinta
    do universo cadastrado.

    ``avaliar_tickers`` limita ``avaliar_ativo`` (e as listas devolvidas) a
    um recorte; totais do universo/fora permanecem do catálogo completo.
    """
    tipo_norm = _tipo_valor(tipo)
    universo = set(tickers_catalogo(session, tipo_norm))
    if categoria in (PRECO, INDICADORES_MERCADO, DADOS_FII):
        persistidos = _tickers_com_snapshot(session, tipo_norm)
    elif categoria == CONTABIL:
        persistidos = _tickers_com_contabil(session, tipo_norm)
    elif categoria == DOCUMENTOS:
        persistidos = _tickers_com_documento(session)
    else:
        persistidos = set()

    processados = set(coletados) if coletados is not None else persistidos
    processados_no_universo = processados & universo
    fora = sorted(universo - persistidos)
    alvos = universo if avaliar_tickers is None else (universo & set(avaliar_tickers))
    ativos = _ativos_por_ticker(session, persistidos & alvos)

    por_status = {FRESH: [], STALE: [], MISSING: [t for t in fora if t in alvos]}
    for ticker in sorted(alvos):
        ativo = ativos.get(ticker)
        if ativo is None:
            continue
        estado = avaliar_ativo(session, ativo, agora=agora)
        status = estado["categorias"].get(categoria, {}).get("status", MISSING)
        if categoria == DADOS_FII and tipo_norm != "FII":
            status = MISSING
        if status == MISSING and ticker not in por_status[MISSING]:
            por_status[MISSING].append(ticker)
        elif status != MISSING:
            por_status[status].append(ticker)

    cobertura_total = len(universo) > 0 and len(fora) == 0
    amostra = coletados is not None and not set(coletados) >= universo
    universo_lista = sorted(universo if avaliar_tickers is None else alvos)
    coletados_lista = sorted(
        processados_no_universo if avaliar_tickers is None
        else processados_no_universo & alvos
    )
    fora_lista = fora if avaliar_tickers is None else [t for t in fora if t in alvos]
    return {
        "tipo": tipo_norm,
        "categoria": categoria,
        "universo": universo_lista,
        "universo_total": len(universo),
        "coletados": coletados_lista,
        "coletados_total": len(processados_no_universo),
        "fora": fora_lista,
        "fora_total": len(fora),
        "fresh": por_status[FRESH],
        "stale": por_status[STALE],
        "missing": sorted(set(por_status[MISSING])),
        "cobertura_total": cobertura_total and not amostra,
        "execucao_parcial": amostra or not cobertura_total,
        "capacidade": capacidade_por_execucao(),
    }


def cobertura_catalogo(
    session, agora=None, coletados_fii=None, coletados_acao=None, limite=None, offset=0
) -> dict:
    """Relatório de cobertura do catálogo, por tipo e por categoria.

    Com ``limite``, avalia só a página do catálogo (teto HTTP). Totais do
    universo permanecem completos; ``avaliar_ativo`` nunca percorre o catálogo
    inteiro nesse modo.
    """
    universo = contar_universo(session)
    avaliar = None
    avaliados = None
    if limite is not None:
        todos = tickers_catalogo(session)
        inicio = max(int(offset or 0), 0)
        teto = max(int(limite), 0)
        avaliados = todos[inicio:inicio + teto]
        avaliar = set(avaliados)
    fiis_preco = cobertura_tipo(
        session, "FII", PRECO, agora, coletados_fii, avaliar_tickers=avaliar
    )
    acoes_preco = cobertura_tipo(
        session, "ACAO", PRECO, agora, coletados_acao, avaliar_tickers=avaliar
    )
    relatorio = {
        "universo": universo,
        "capacidade_por_execucao": capacidade_por_execucao(),
        "por_tipo": {
            "FII": {
                PRECO: fiis_preco,
                INDICADORES_MERCADO: cobertura_tipo(
                    session, "FII", INDICADORES_MERCADO, agora, coletados_fii,
                    avaliar_tickers=avaliar,
                ),
                CONTABIL: cobertura_tipo(
                    session, "FII", CONTABIL, agora, avaliar_tickers=avaliar
                ),
                DOCUMENTOS: cobertura_tipo(
                    session, "FII", DOCUMENTOS, agora, avaliar_tickers=avaliar
                ),
                DADOS_FII: cobertura_tipo(
                    session, "FII", DADOS_FII, agora, coletados_fii,
                    avaliar_tickers=avaliar,
                ),
            },
            "ACAO": {
                PRECO: acoes_preco,
                INDICADORES_MERCADO: cobertura_tipo(
                    session, "ACAO", INDICADORES_MERCADO, agora, coletados_acao,
                    avaliar_tickers=avaliar,
                ),
                CONTABIL: cobertura_tipo(
                    session, "ACAO", CONTABIL, agora, avaliar_tickers=avaliar
                ),
                DOCUMENTOS: cobertura_tipo(
                    session, "ACAO", DOCUMENTOS, agora, avaliar_tickers=avaliar
                ),
            },
        },
        "cobertura_total": (
            fiis_preco["cobertura_total"] and acoes_preco["cobertura_total"]
        ),
        "execucao_parcial": (
            fiis_preco["execucao_parcial"] or acoes_preco["execucao_parcial"]
        ),
    }
    if avaliados is not None:
        relatorio["avaliados"] = list(avaliados)
        relatorio["avaliados_total"] = len(avaliados)
        relatorio["total_paginavel"] = int(universo.get("total_catalogo") or 0)
    return relatorio


def registrar_execucao(tickers, tipo, origem="scraper") -> dict:
    """Marca uma execução amostral: o que entrou na fila nesta rodada."""
    limpos = sorted({str(t).strip().upper() for t in tickers if t and str(t).strip()})
    return {
        "tipo": _tipo_valor(tipo),
        "origem": origem,
        "coletados": limpos,
        "coletados_total": len(limpos),
        "executado_em": datetime.now(),
        "data_referencia": date.today(),
        "execucao_parcial": True,
    }
