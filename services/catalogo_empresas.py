"""Servicos do catalogo central de empresas e da taxonomia setorial.

Reutiliza as fontes que o projeto ja possui:

* ``config.MAPA_SETORES_B3`` para macro-setor/subsetor dos tickers da B3;
* ``pipeline_dados.coletor_catalogo_cvm`` para o cadastro oficial completo
  (empresa, CNPJ, ticker, setor e atividade) da CVM;
* ``pipeline_dados.repositorio_catalogo`` para upserts e historico.

Importante: aplicar o mapa setorial NAO copia todas as atividades do setor para
a empresa. Atividades so sao vinculadas quando uma fonte oficial/validada as
declara individualmente.
"""

import logging

import config
from pipeline_dados.repositorio_catalogo import (
    RepositorioCatalogo,
    normalizar_ticker,
)

logger = logging.getLogger("robo.catalogo.servico")

FONTE_MAPA_B3 = "config.MAPA_SETORES_B3"


def aplicar_mapa_setores_b3(repositorio=None, mapa=None, fonte=FONTE_MAPA_B3):
    """Cria setores/subsetores e classifica empresas ja cadastradas.

    Empresas sem vinculo conhecido (ticker ainda nao importado de fonte oficial)
    sao ignoradas — o mapa nao e usado para inventar CNPJ, empresa ou atividade.
    """
    repositorio = repositorio or RepositorioCatalogo()
    mapa = mapa if mapa is not None else config.MAPA_SETORES_B3
    resumo = {
        "setores": 0,
        "subsetores": 0,
        "empresas_classificadas": 0,
        "empresas_ignoradas": 0,
        "erros": 0,
    }

    for nome_setor, subsetores in (mapa or {}).items():
        try:
            setor_id = repositorio.obter_ou_criar_setor(nome_setor, fonte=fonte)
            resumo["setores"] += 1
        except Exception:
            resumo["erros"] += 1
            logger.warning("Falha ao criar setor %s", nome_setor, exc_info=True)
            continue

        for nome_subsetor, tickers in (subsetores or {}).items():
            try:
                subsetor_id = repositorio.obter_ou_criar_subsetor(
                    setor_id, nome_subsetor, fonte=fonte
                )
                resumo["subsetores"] += 1
            except Exception:
                resumo["erros"] += 1
                logger.warning(
                    "Falha ao criar subsetor %s/%s",
                    nome_setor,
                    nome_subsetor,
                    exc_info=True,
                )
                continue

            for ticker in tickers or []:
                chave = normalizar_ticker(ticker)
                if not chave:
                    continue
                try:
                    empresa = repositorio.obter_empresa_por_ticker(chave)
                    if empresa is None:
                        resumo["empresas_ignoradas"] += 1
                        continue
                    _, alterou = repositorio.classificar_empresa(
                        empresa.id,
                        setor_id,
                        subsetor_id=subsetor_id,
                        fonte=fonte,
                        evidencia=(
                            f"{fonte}: {nome_setor} > {nome_subsetor} "
                            f"(ticker {chave})"
                        ),
                    )
                    if alterou:
                        resumo["empresas_classificadas"] += 1
                except Exception:
                    resumo["erros"] += 1
                    logger.warning(
                        "Falha ao classificar %s pelo mapa B3",
                        chave,
                        exc_info=True,
                    )
    return resumo


def obter_resumo_empresa(ticker, repositorio=None):
    """Resumo pronto para painel/administracao (ou ``None`` se nao existir)."""
    repositorio = repositorio or RepositorioCatalogo()
    return repositorio.obter_resumo_empresa(ticker)


__all__ = [
    "FONTE_MAPA_B3",
    "aplicar_mapa_setores_b3",
    "obter_resumo_empresa",
]
