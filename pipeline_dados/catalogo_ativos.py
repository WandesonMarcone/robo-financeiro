"""Catálogo central de ativos — Fase 7, Etapa 7.2 (aditivo).

Camada única de consulta/seed do catálogo financeiro no PostgreSQL. O
PostgreSQL passa progressivamente a ser a fonte ativa do catálogo; o Google
Sheets permanece como fallback/legado para os consumidores ainda dependentes
da planilha (o fallback fica explícito em ``obter_tickers_com_fallback``).

Fontes de seed (sem inventar identificadores):
- ``config.MAPA_CNPJ_B3``      -> ACAO  (ticker, cnpj, setor via MAPA_SETORES_B3)
- ``config.MAPA_ISCAS_MASTER`` -> FII   (ticker, nome_emissor; cnpj NULL)

Nenhum dado existente é alterado: a tabela ``ativos_catalogo`` é nova e o
seed é idempotente (insert-only por ticker).
"""

import logging

import config
from pipeline_dados.banco_dados import AtivoCatalogo, TipoAtivo
from pipeline_dados.normalizacao import formatar_cnpj, normalizar_cnpj

logger = logging.getLogger(__name__)

# Origem dos registros semeado a partir dos mapas de config.py.
FONTE_CONFIG = "config"

_TIPOS_VALIDOS = {t.value for t in TipoAtivo}

# Mapa reverso ticker -> CNPJ (ACAO) usado como fallback offline do seed.
_TICKER_PARA_CNPJ = {ticker.upper(): cnpj for cnpj, ticker in config.MAPA_CNPJ_B3.items()}


def _normalizar_tipo(tipo) -> str | None:
    """Normaliza o tipo para a string do catálogo (ACAO/FII/ETF/CRIPTO)."""
    if isinstance(tipo, TipoAtivo):
        return tipo.value
    if tipo is None:
        return None
    texto = str(tipo).strip().upper()
    return texto if texto in _TIPOS_VALIDOS else None


def _cnpj_normalizado(cnpj) -> str | None:
    """CNPJ no formato XX.XXX.XXX/XXXX-XX; None quando não tem 14 dígitos."""
    if normalizar_cnpj(cnpj) is None:
        return None
    return formatar_cnpj(cnpj)


def _setor_por_ticker() -> dict[str, str]:
    """Mapa reverso ticker -> setor macro a partir de config.MAPA_SETORES_B3."""
    mapa = {}
    for setor, sub_setores in config.MAPA_SETORES_B3.items():
        for tickers in sub_setores.values():
            for ticker in tickers:
                mapa[ticker.upper()] = setor
    return mapa


def _entradas_acao() -> list[dict]:
    """Entradas ACAO do catálogo derivadas de config.MAPA_CNPJ_B3."""
    setor_por_ticker = _setor_por_ticker()
    entradas = []
    for cnpj, ticker in config.MAPA_CNPJ_B3.items():
        ticker_norm = str(ticker).strip().upper()
        entradas.append({
            "ticker": ticker_norm,
            "tipo": TipoAtivo.ACAO.value,
            "cnpj": _cnpj_normalizado(cnpj),
            "nome_emissor": None,
            "setor": setor_por_ticker.get(ticker_norm),
            "fonte": FONTE_CONFIG,
        })
    return entradas


def _entradas_fii() -> list[dict]:
    """Entradas FII do catálogo derivadas de config.MAPA_ISCAS_MASTER."""
    entradas = []
    for ticker, nome in config.MAPA_ISCAS_MASTER.items():
        entradas.append({
            "ticker": str(ticker).strip().upper(),
            "tipo": TipoAtivo.FII.value,
            "cnpj": None,
            "nome_emissor": nome,
            "setor": None,
            "fonte": FONTE_CONFIG,
        })
    return entradas


def _inserir_se_ausente(session, entrada: dict) -> int:
    """Insere um registro de catálogo somente se o ticker ainda não existir."""
    existente = (
        session.query(AtivoCatalogo)
        .filter(AtivoCatalogo.ticker == entrada["ticker"])
        .first()
    )
    if existente is not None:
        return 0
    session.add(AtivoCatalogo(**entrada))
    return 1


def seed_catalogo(session) -> int:
    """Seed idempotente do catálogo a partir de config.

    Cria apenas os tickers ainda ausentes (chave de identidade: ticker).
    Nunca sobrescreve, apaga ou altera registros existentes. Retorna a
    quantidade de registros criados.
    """
    criados = 0
    for entrada in _entradas_acao():
        criados += _inserir_se_ausente(session, entrada)
    for entrada in _entradas_fii():
        criados += _inserir_se_ausente(session, entrada)
    session.commit()
    if criados:
        logger.info("Catálogo de ativos semeado: %s registros criados.", criados)
    return criados


def _garantir_catalogo_semeado(session) -> None:
    """Semeia o catálogo uma única vez (quando a tabela está vazia)."""
    if session.query(AtivoCatalogo).first() is None:
        seed_catalogo(session)


def registrar_no_catalogo(
    session,
    ticker,
    tipo,
    cnpj=None,
    nome_emissor=None,
    setor=None,
    fonte=None,
) -> AtivoCatalogo:
    """Registra/atualiza um ativo no catálogo (idempotente por ticker).

    ``cnpj`` é armazenado apenas quando tem 14 dígitos; caso contrário vira
    NULL (nunca se inventa identificador).
    """
    ticker_norm = str(ticker).strip().upper()
    tipo_norm = _normalizar_tipo(tipo)
    if not ticker_norm or tipo_norm is None:
        raise ValueError(f"ticker/tipo inválidos para o catálogo: {ticker!r}, {tipo!r}")

    registro = consultar_por_ticker(session, ticker_norm)
    if registro is None:
        registro = AtivoCatalogo(ticker=ticker_norm, tipo=tipo_norm)
        session.add(registro)
    registro.tipo = tipo_norm
    registro.cnpj = _cnpj_normalizado(cnpj) if cnpj is not None else None
    registro.nome_emissor = nome_emissor
    registro.setor = setor
    if fonte is not None:
        registro.fonte = fonte
    session.commit()
    return registro


def consultar_por_ticker(session, ticker) -> AtivoCatalogo | None:
    """Registro do catálogo por ticker (normalizado para maiúsculas)."""
    if not ticker:
        return None
    return (
        session.query(AtivoCatalogo)
        .filter(AtivoCatalogo.ticker == str(ticker).strip().upper())
        .first()
    )


def consultar_por_cnpj(session, cnpj) -> AtivoCatalogo | None:
    """Registro do catálogo por CNPJ (qualquer máscara de 14 dígitos)."""
    digitos = normalizar_cnpj(cnpj)
    if digitos is None:
        return None
    return (
        session.query(AtivoCatalogo)
        .filter(AtivoCatalogo.cnpj == formatar_cnpj(digitos))
        .first()
    )


def resolver_cnpj(session, ticker, tipo=None) -> str | None:
    """CNPJ do ativo: catálogo PostgreSQL primeiro; config como fallback.

    Retorna ``None`` quando o CNPJ não é conhecido — nunca inventa CNPJ nem
    devolve placeholder.
    """
    registro = consultar_por_ticker(session, ticker)
    if registro is not None:
        return registro.cnpj
    if tipo is None or _normalizar_tipo(tipo) == TipoAtivo.ACAO.value:
        return _cnpj_normalizado(_TICKER_PARA_CNPJ.get(str(ticker).strip().upper()))
    return None


def listar_tickers_catalogo(session, tipo) -> list[str]:
    """Tickers do catálogo PostgreSQL para um tipo (semeado idempotente).

    Vazio quando o catálogo ainda não possui o tipo solicitado.
    """
    tipo_norm = _normalizar_tipo(tipo)
    if tipo_norm is None:
        return []
    _garantir_catalogo_semeado(session)
    linhas = (
        session.query(AtivoCatalogo.ticker)
        .filter(AtivoCatalogo.tipo == tipo_norm)
        .all()
    )
    return sorted({linha[0] for linha in linhas})


def obter_tickers_com_fallback(session, tipo, fallback) -> list[str]:
    """Tickers do catálogo PostgreSQL; se vazio/indisponível, chama ``fallback``.

    ``fallback`` é um callable sem argumentos retornando ``list[str]`` (ex.:
    leitura da aba do Google Sheets). Centraliza a estratégia "catálogo
    primeiro, Sheets como fallback" para os consumidores: qualquer falha do
    catálogo (banco indisponível, seed com erro) também cai no fallback, para
    nunca bloquear o fluxo legado.
    """
    try:
        tickers = listar_tickers_catalogo(session, tipo)
    except Exception:
        logger.exception(
            "Catálogo PostgreSQL indisponível para tipo %s; usando fallback.",
            tipo,
        )
        tickers = []
    if tickers:
        return tickers
    if callable(fallback):
        return fallback()
    return []
