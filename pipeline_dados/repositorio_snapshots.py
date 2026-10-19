"""Persistencia idempotente de snapshots EOD nas tabelas existentes.

Nao cria tabelas, nao aplica migracoes e nao toca em
``indicadores_historico``, alertas, notificacoes ou documentos.

Regras:
* unique real ``(ativo_id, data_referencia)`` — uma linha por ativo por dia;
* ausencia/invalido vira omitido (NULL), nunca 0 sentinela;
* update nao substitui valor valido por ausencia;
* ticker sem ``ativos.id`` e ignorado (nada e inventado).
"""

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from pipeline_dados.banco_dados import Ativo
from pipeline_dados.conexao import obter_session_factory
from pipeline_dados.modelos_snapshots import SnapshotAcao, SnapshotFii

logger = logging.getLogger("robo.eod")

CAMPOS_META_UPDATE = ("data_coleta", "fonte", "url_origem", "fonte_primaria")

INDICADORES_ACAO = (
    "preco",
    "dy",
    "pl",
    "pvp",
    "p_ativo",
    "marg_bruta",
    "marg_ebit",
    "marg_liquida",
    "p_ebit",
    "ev_ebit",
    "div_liq_patrimonio",
    "psr",
    "p_cap_giro",
    "p_at_circ_liq",
    "liq_corrente",
    "roe",
    "roa",
    "roic",
    "cagr_rec_5a",
    "liq_media",
    "vpa",
    "lpa",
    "peg_ratio",
    "valor_mercado",
)

INDICADORES_FII = (
    "preco",
    "pvp",
    "dy",
    "qtd_imoveis",
    "liquidez",
    "vpa",
    "lucro_12m",
    "dividendo_mensal",
)


def _tem_indicador(payload, indicadores):
    return any(payload.get(nome) is not None for nome in indicadores)


def _aplicar_update(registro, payload, indicadores):
    for nome in CAMPOS_META_UPDATE:
        valor = payload.get(nome)
        if valor is not None:
            setattr(registro, nome, valor)
    for nome in indicadores:
        valor = payload.get(nome)
        if valor is not None:
            setattr(registro, nome, valor)


def _mapa_tickers(sessao, tickers):
    if not tickers:
        return {}
    normalizados = {str(t).strip().upper() for t in tickers if t}
    linhas = sessao.execute(
        select(Ativo.ticker, Ativo.id).where(Ativo.ticker.in_(normalizados))
    ).all()
    return {ticker.upper(): ativo_id for ticker, ativo_id in linhas}


def _upsert_lote(sessao, modelo, payloads, indicadores, data_referencia):
    gravados = 0
    omitidos_sem_ativo = 0
    omitidos_sem_dados = 0
    tickers = [p.get("ticker") for p in payloads]
    ids = _mapa_tickers(sessao, tickers)

    for payload in payloads:
        ticker = str(payload.get("ticker") or "").strip().upper()
        ativo_id = ids.get(ticker)
        if ativo_id is None:
            omitidos_sem_ativo += 1
            logger.info("EOD: ticker %s sem cadastro em ativos; omitido", ticker)
            continue
        if not _tem_indicador(payload, indicadores):
            omitidos_sem_dados += 1
            continue

        existente = sessao.execute(
            select(modelo).where(
                modelo.ativo_id == ativo_id,
                modelo.data_referencia == data_referencia,
            )
        ).scalar_one_or_none()

        if existente is None:
            novo = modelo(
                ativo_id=ativo_id,
                data_referencia=data_referencia,
                data_coleta=payload["data_coleta"],
                fonte=payload.get("fonte"),
                url_origem=payload.get("url_origem"),
                fonte_primaria=payload.get("fonte_primaria"),
            )
            for nome in indicadores:
                valor = payload.get(nome)
                if valor is not None:
                    setattr(novo, nome, valor)
            try:
                with sessao.begin_nested():
                    sessao.add(novo)
                    sessao.flush()
            except IntegrityError:
                existente = sessao.execute(
                    select(modelo).where(
                        modelo.ativo_id == ativo_id,
                        modelo.data_referencia == data_referencia,
                    )
                ).scalar_one()
                _aplicar_update(existente, payload, indicadores)
        else:
            _aplicar_update(existente, payload, indicadores)
        gravados += 1
    return gravados, omitidos_sem_ativo, omitidos_sem_dados


def persistir_snapshots(payloads_acoes, payloads_fiis, data_referencia, session_factory=None):
    """Grava os lotes EOD. Levanta excecao de banco para o chamador isolar."""
    fabrica = session_factory or obter_session_factory()
    resumo = {
        "acoes_gravadas": 0,
        "fiis_gravados": 0,
        "omitidos_sem_ativo": 0,
        "omitidos_sem_dados": 0,
        "data_referencia": data_referencia,
    }
    sessao = fabrica()
    try:
        a_g, a_sa, a_sd = _upsert_lote(
            sessao, SnapshotAcao, payloads_acoes, INDICADORES_ACAO, data_referencia
        )
        f_g, f_sa, f_sd = _upsert_lote(
            sessao, SnapshotFii, payloads_fiis, INDICADORES_FII, data_referencia
        )
        sessao.commit()
        resumo["acoes_gravadas"] = a_g
        resumo["fiis_gravados"] = f_g
        resumo["omitidos_sem_ativo"] = a_sa + f_sa
        resumo["omitidos_sem_dados"] = a_sd + f_sd
        return resumo
    except Exception:
        sessao.rollback()
        raise
    finally:
        sessao.close()
