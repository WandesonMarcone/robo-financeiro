"""Consulta de dados de mercado persistidos — Fase 7, Etapa 7.3.

Camada de leitura de produção dos dados de mercado persistidos pelo Bloco 5C
(``snapshots_fiis``/``snapshots_acoes``) e pelos coletores contábeis CVM
(``dados_financeiros_fiis``/``dados_financeiros_acoes``). É o leitor que o
Financial Intelligence Core usa para consumir a camada PostgreSQL persistida —
antes desta etapa nenhum leitor de produção consumia essas tabelas.

Garantias do serviço:
- Somente leitura: nunca cria, altera ou apaga registros; nunca inventa valor
  (campos ausentes permanecem ``None``, nunca viram ``0.0``).
- Filtros seguros: ``ticker`` (parcial, normalizado), ``ativo_id``, ``tipo``
  (apenas ACAO/FII — os tipos com dados de mercado persistidos), ``tipo_doc``
  (ações) e ``data_referencia`` (data exata).
- ``limite`` com teto seguro (máximo 500), consistente com a camada HTTP.
- Ordenação cronológica decrescente (mais recente primeiro).
- Reutiliza a sessão informada pelo chamador (nunca a fecha) ou abre e fecha
  uma sessão própria via ``services.db.sessao_db`` — o contexto canônico de
  acesso ao banco (Fase 7, Etapa 7.4).
"""
import logging

from pipeline_dados.banco_dados import (
    Ativo,
    DadosFinanceirosAcoes,
    DadosFinanceirosFiis,
    SnapshotAcao,
    SnapshotFii,
)
from services.db import sessao_db

logger = logging.getLogger(__name__)

# Tipos de ativo com dados de mercado persistidos (snapshots/dados financeiros).
TIPOS_MERCADO = ("ACAO", "FII")

# Teto máximo de registros por consulta (consistente com api.dependencias).
LIMITE_PADRAO = 100
LIMITE_MAXIMO = 500


def _tipo_normalizado(tipo) -> str | None:
    """Normaliza o tipo para ACAO/FII; None quando ausente; ValueError se inválido."""
    if tipo is None:
        return None
    texto = str(tipo).strip().upper()
    if texto not in TIPOS_MERCADO:
        raise ValueError(
            f"Tipo de ativo inválido para dados de mercado: {tipo!r}. "
            "Use ACAO ou FII."
        )
    return texto


def _limite_valido(limite) -> int:
    """Teto seguro para o número de registros retornados."""
    if limite is None:
        return LIMITE_PADRAO
    try:
        valor = int(limite)
    except (TypeError, ValueError):
        return LIMITE_PADRAO
    if valor <= 0:
        return LIMITE_PADRAO
    return min(valor, LIMITE_MAXIMO)


def _ticker_normalizado(ticker) -> str | None:
    if ticker is None or not str(ticker).strip():
        return None
    return str(ticker).strip().upper()


def _filtro_base(query, modelo, ticker, ativo_id, data_referencia):
    """Aplica os filtros comuns de um snapshot/dado financeiro à query."""
    if ativo_id is not None:
        query = query.filter(modelo.ativo_id == ativo_id)
    else:
        ticker_limpo = _ticker_normalizado(ticker)
        if ticker_limpo is not None:
            query = query.filter(modelo.ativo.has(Ativo.ticker == ticker_limpo))
    if data_referencia is not None:
        query = query.filter(modelo.data_referencia == data_referencia)
    return query


_MODELOS_SNAPSHOTS = {"FII": SnapshotFii, "ACAO": SnapshotAcao}
_MODELOS_DADOS = {"FII": DadosFinanceirosFiis, "ACAO": DadosFinanceirosAcoes}


def obter_snapshots(
    ticker=None,
    ativo_id=None,
    tipo=None,
    data_referencia=None,
    limite=LIMITE_PADRAO,
    session=None,
) -> list:
    """Snapshots de mercado persistidos, ordenados do mais recente para o mais antigo.

    Filtros: ``ticker`` (exato, normalizado), ``ativo_id``, ``tipo`` (ACAO/FII)
    e ``data_referencia`` (data exata). Retorna lista de objetos ORM
    (``SnapshotFii``/``SnapshotAcao``); vazio quando nada corresponde. Valores
    ausentes na origem permanecem ``None`` — nunca ``0.0``.
    """
    tipo_norm = _tipo_normalizado(tipo)
    teto = _limite_valido(limite)
    with sessao_db(session) as s:
        if tipo_norm is not None:
            modelo = _MODELOS_SNAPSHOTS[tipo_norm]
            return (
                _filtro_base(s.query(modelo), modelo, ticker, ativo_id, data_referencia)
                .order_by(modelo.data_referencia.desc(), modelo.id.desc())
                .limit(teto)
                .all()
            )

        resultados = []
        for modelo in (SnapshotFii, SnapshotAcao):
            resultados.extend(
                _filtro_base(
                    s.query(modelo), modelo, ticker, ativo_id, data_referencia
                ).all()
            )
        resultados.sort(key=lambda r: (r.data_referencia, r.id), reverse=True)
        return resultados[:teto]


def obter_snapshot_mais_recente(ticker=None, ativo_id=None, tipo=None, session=None):
    """Snapshot de mercado mais recente para o filtro informado, ou ``None``.

    Útil para o core obter o estado atual de mercado de um ativo sem conhecer a
    ``data_referencia``. Retorna objeto ORM (``SnapshotFii``/``SnapshotAcao``).
    """
    registros = obter_snapshots(
        ticker=ticker,
        ativo_id=ativo_id,
        tipo=tipo,
        limite=1,
        session=session,
    )
    return registros[0] if registros else None


def obter_dados_financeiros(
    ticker=None,
    ativo_id=None,
    tipo=None,
    tipo_doc=None,
    data_referencia=None,
    limite=LIMITE_PADRAO,
    session=None,
) -> list:
    """Dados contábeis persistidos (CVM), do mais recente para o mais antigo.

    Filtros: ``ticker`` (exato, normalizado), ``ativo_id``, ``tipo`` (ACAO/FII),
    ``tipo_doc`` (ex.: ``ITR``/``DFP`` — apenas ações) e ``data_referencia``.
    Retorna lista de objetos ORM (``DadosFinanceirosFiis``/``DadosFinanceirosAcoes``).
    """
    tipo_norm = _tipo_normalizado(tipo)
    if tipo_doc is not None and tipo_norm == "FII":
        raise ValueError("'tipo_doc' só se aplica a dados financeiros de ações (tipo=ACAO).")
    teto = _limite_valido(limite)
    with sessao_db(session) as s:
        if tipo_norm is not None:
            modelo = _MODELOS_DADOS[tipo_norm]
            query = _filtro_base(
                s.query(modelo), modelo, ticker, ativo_id, data_referencia
            )
            if tipo_doc is not None and hasattr(modelo, "tipo_doc"):
                query = query.filter(modelo.tipo_doc == str(tipo_doc).strip().upper())
            return (
                query.order_by(modelo.data_referencia.desc(), modelo.id.desc())
                .limit(teto)
                .all()
            )

        resultados = []
        for modelo in (DadosFinanceirosFiis, DadosFinanceirosAcoes):
            query = _filtro_base(
                s.query(modelo), modelo, ticker, ativo_id, data_referencia
            )
            if tipo_doc is not None and hasattr(modelo, "tipo_doc"):
                query = query.filter(modelo.tipo_doc == str(tipo_doc).strip().upper())
            resultados.extend(query.all())
        resultados.sort(key=lambda r: (r.data_referencia, r.id), reverse=True)
        return resultados[:teto]
