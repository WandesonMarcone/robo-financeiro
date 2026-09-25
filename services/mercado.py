"""Consulta de dados de mercado persistidos — Fase 7, Etapa 7.3.

Camada de leitura de produção dos dados de mercado persistidos pelo Bloco 5C
(``snapshots_fiis``/``snapshots_acoes``) e pelos coletores contábeis CVM
(``dados_financeiros_fiis``/``dados_financeiros_acoes``). É o leitor que o
Financial Intelligence Core usa para consumir a camada PostgreSQL persistida —
antes desta etapa nenhum leitor de produção consumia essas tabelas.

Garantias do serviço:
- Somente leitura: nunca cria, altera ou apaga registros; nunca inventa valor
  (campos ausentes permanecem ``None``, nunca viram ``0.0``).
- Filtros seguros: ``ticker`` (igualdade exata, normalizado), ``ativo_id``, ``tipo``
  (apenas ACAO/FII — os tipos com dados de mercado persistidos), ``tipo_doc``
  (ações) e ``data_referencia`` (data exata).
- ``limite`` com teto seguro (máximo 500), consistente com a camada HTTP.
- Ordenação cronológica decrescente (mais recente primeiro).
- Reutiliza a sessão informada pelo chamador (nunca a fecha) ou abre e fecha
  uma sessão própria via ``services.db.sessao_db`` — o contexto canônico de
  acesso ao banco (Fase 7, Etapa 7.4).
"""
import logging

from sqlalchemy.orm import joinedload

from pipeline_dados.banco_dados import (
    Ativo,
    DadosFinanceirosAcoes,
    DadosFinanceirosFiis,
    SnapshotAcao,
    SnapshotFii,
    TipoAtivo,
)
from pipeline_dados.cobertura import cobertura_catalogo, contar_universo
from pipeline_dados.cobertura_fiis import (
    CAMPOS_FII,
    avaliar_campos_fii,
    campos_pendentes,
    cobertura_campos_fii,
)
from pipeline_dados.freshness import avaliar_ativo
from pipeline_dados.semantica_indicadores import interpretar_valor
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


def _com_ativo(query, modelo):
    """Carrega ``ativo`` na mesma consulta da listagem (evita N+1)."""
    return query.options(joinedload(modelo.ativo))


_MODELOS_SNAPSHOTS = {"FII": SnapshotFii, "ACAO": SnapshotAcao}
_MODELOS_DADOS = {"FII": DadosFinanceirosFiis, "ACAO": DadosFinanceirosAcoes}


def obter_snapshots(
    ticker=None,
    ativo_id=None,
    tipo=None,
    data_referencia=None,
    limite=LIMITE_PADRAO,
    offset=0,
    session=None,
    com_total=False,
) -> list:
    """Snapshots de mercado persistidos, ordenados do mais recente para o mais antigo.

    Filtros: ``ticker`` (exato, normalizado), ``ativo_id``, ``tipo`` (ACAO/FII)
    e ``data_referencia`` (data exata). Retorna lista de objetos ORM
    (``SnapshotFii``/``SnapshotAcao``); vazio quando nada corresponde. Valores
    ausentes na origem permanecem ``None`` — nunca ``0.0``. Com ``com_total``,
    devolve ``(registros, total)``.
    """
    tipo_norm = _tipo_normalizado(tipo)
    teto = _limite_valido(limite)
    inicio = max(int(offset or 0), 0)
    with sessao_db(session) as s:
        if tipo_norm is not None:
            modelo = _MODELOS_SNAPSHOTS[tipo_norm]
            query = _filtro_base(
                s.query(modelo), modelo, ticker, ativo_id, data_referencia
            )
            total = query.count()
            registros = (
                _com_ativo(query, modelo)
                .order_by(modelo.data_referencia.desc(), modelo.id.desc())
                .offset(inicio)
                .limit(teto)
                .all()
            )
            return (registros, total) if com_total else registros

        resultados = []
        total = 0
        fetch = inicio + teto
        for modelo in (SnapshotFii, SnapshotAcao):
            query = _filtro_base(
                s.query(modelo), modelo, ticker, ativo_id, data_referencia
            )
            total += query.count()
            resultados.extend(
                _com_ativo(query, modelo)
                .order_by(modelo.data_referencia.desc(), modelo.id.desc())
                .limit(fetch)
                .all()
            )
        resultados.sort(key=lambda r: (r.data_referencia, r.id), reverse=True)
        registros = resultados[inicio:inicio + teto]
        return (registros, total) if com_total else registros


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
    offset=0,
    session=None,
    com_total=False,
) -> list:
    """Dados contábeis persistidos (CVM), do mais recente para o mais antigo.

    Filtros: ``ticker`` (exato, normalizado), ``ativo_id``, ``tipo`` (ACAO/FII),
    ``tipo_doc`` (ex.: ``ITR``/``DFP`` — apenas ações) e ``data_referencia``.
    Retorna lista de objetos ORM (``DadosFinanceirosFiis``/``DadosFinanceirosAcoes``).
    Com ``com_total``, devolve ``(registros, total)``.
    """
    tipo_norm = _tipo_normalizado(tipo)
    if tipo_doc is not None and tipo_norm == "FII":
        raise ValueError("'tipo_doc' só se aplica a dados financeiros de ações (tipo=ACAO).")
    teto = _limite_valido(limite)
    inicio = max(int(offset or 0), 0)

    def _aplicar_tipo_doc(query, modelo):
        if tipo_doc is not None and hasattr(modelo, "tipo_doc"):
            return query.filter(modelo.tipo_doc == str(tipo_doc).strip().upper())
        return query

    with sessao_db(session) as s:
        if tipo_norm is not None:
            modelo = _MODELOS_DADOS[tipo_norm]
            query = _aplicar_tipo_doc(
                _filtro_base(s.query(modelo), modelo, ticker, ativo_id, data_referencia),
                modelo,
            )
            total = query.count()
            registros = (
                _com_ativo(query, modelo)
                .order_by(modelo.data_referencia.desc(), modelo.id.desc())
                .offset(inicio)
                .limit(teto)
                .all()
            )
            return (registros, total) if com_total else registros

        resultados = []
        total = 0
        fetch = inicio + teto
        for modelo in (DadosFinanceirosFiis, DadosFinanceirosAcoes):
            query = _aplicar_tipo_doc(
                _filtro_base(s.query(modelo), modelo, ticker, ativo_id, data_referencia),
                modelo,
            )
            total += query.count()
            resultados.extend(
                _com_ativo(query, modelo)
                .order_by(modelo.data_referencia.desc(), modelo.id.desc())
                .limit(fetch)
                .all()
            )
        resultados.sort(key=lambda r: (r.data_referencia, r.id), reverse=True)
        registros = resultados[inicio:inicio + teto]
        return (registros, total) if com_total else registros


def obter_freshness(ticker=None, ativo_id=None, tipo=None, agora=None, session=None) -> dict | None:
    """Estado FRESH/STALE/MISSING por categoria do ativo, ou None se ausente."""
    ticker_limpo = _ticker_normalizado(ticker)
    tipo_norm = _tipo_normalizado(tipo) if tipo is not None else None
    with sessao_db(session) as s:
        query = s.query(Ativo)
        if ativo_id is not None:
            query = query.filter(Ativo.id == ativo_id)
        elif ticker_limpo is not None:
            query = query.filter(Ativo.ticker == ticker_limpo)
        else:
            return None
        if tipo_norm is not None:
            query = query.filter(Ativo.tipo == TipoAtivo(tipo_norm))
        ativo = query.first()
        if ativo is None:
            return None
        return avaliar_ativo(s, ativo, agora=agora)


def obter_cobertura(
    agora=None,
    coletados_fii=None,
    coletados_acao=None,
    session=None,
    limite=None,
    offset=0,
) -> dict:
    """Cobertura do catálogo: universo vs coletados vs fora, por tipo/categoria.

    Com ``limite`` (HTTP), avalia só a página — nunca percorre o catálogo
    inteiro. Totais de universo permanecem completos.
    """
    teto = _limite_valido(limite) if limite is not None else None
    inicio = max(int(offset or 0), 0)
    with sessao_db(session) as s:
        return cobertura_catalogo(
            s,
            agora=agora,
            coletados_fii=coletados_fii,
            coletados_acao=coletados_acao,
            limite=teto,
            offset=inicio,
        )


def obter_universo(session=None) -> dict:
    """Contagens do universo cadastrado (catálogo), sem expandir coleta."""
    with sessao_db(session) as s:
        return contar_universo(s)


def obter_cobertura_fii(
    agora=None, ticker=None, session=None, limite=None, offset=0
) -> dict:
    """Cobertura por campo dos FIIs já cadastrados. Não expande o universo.

    Com ``ticker``, avalia só aquele FII. Sem filtro, aplica teto/offset sobre
    o catálogo e avalia apenas a página — nunca percorre a tabela inteira.
    """
    teto = _limite_valido(limite)
    inicio = max(int(offset or 0), 0)
    with sessao_db(session) as s:
        if ticker:
            relatorio = cobertura_campos_fii(s, agora=agora, ticker=ticker)
            relatorio["total_paginavel"] = relatorio.get("avaliados_total") or 0
            return relatorio

        query = s.query(Ativo).filter(Ativo.tipo == TipoAtivo.FII).order_by(Ativo.ticker)
        total = query.count()
        ativos = query.offset(inicio).limit(teto).all()
        por_ticker = {
            ativo.ticker: avaliar_campos_fii(s, ativo, agora=agora) for ativo in ativos
        }
        totais = {
            "esperados": 0,
            "preenchidos": 0,
            "ausentes": 0,
            "derivados": 0,
            "fonte_inexistente": 0,
            "nao_mapeados": 0,
            "placeholders": 0,
        }
        for relatorio in por_ticker.values():
            for chave in totais:
                totais[chave] += int((relatorio.get("resumo") or {}).get(chave) or 0)
        percentual = (
            totais["preenchidos"] / totais["esperados"] if totais["esperados"] else None
        )
        return {
            "tipo": "FII",
            "universo_total": total,
            "avaliados": sorted(por_ticker),
            "avaliados_total": len(por_ticker),
            "fora": [],
            "fora_total": 0,
            "por_ticker": por_ticker,
            "campos": [campo.nome for campo in CAMPOS_FII],
            "pendentes": campos_pendentes(),
            "resumo": {**totais, "percentual_preenchido": percentual},
            "total_paginavel": total,
        }


def interpretar_indicador(tipo_ativo, indicador, valor, *, ticker=None, setor=None) -> dict:
    """Semântica 8.5 do valor já coletado. Não inventa número nem escala.

    Distingue ZERO / AUSENTE / NAO_APLICAVEL / INVALIDO / PRESENTE. Indicador
    não aplicável ao tipo (ex.: ROE de FII) permanece N/A, nunca 0.
    Matriz F.1 (ticker) preserva NAO_APLICAVEL setorial.
    """
    return interpretar_valor(tipo_ativo, indicador, valor, ticker=ticker, setor=setor)
