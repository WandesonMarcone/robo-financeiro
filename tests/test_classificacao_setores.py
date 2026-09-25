"""Classificação de setores — PARTE E.

Reutiliza config.MAPA_SETORES_B3. Não inventa setor. Sheets legado continua
devolvendo ("Outros", "Não Classificado"); o catálogo interno não trata isso
como setor econômico confiável.
"""

from modules.scraper_acoes import classificar_setor_por_mapa
from pipeline_dados.catalogo_ativos import (
    SETOR_NAO_CLASSIFICADO,
    classificar_setor_catalogo,
    setor_confiavel,
)


def test_classificar_setor_por_mapa_conhecido():
    assert classificar_setor_por_mapa("PETR4") == (
        "Petróleo, Gás & Biocombustíveis",
        "Exploração e Refino",
    )
    assert classificar_setor_por_mapa("bbas3") == ("Financeiro", "Bancos")


def test_classificar_setor_por_mapa_legado_outros():
    assert classificar_setor_por_mapa("EMBR3") == ("Outros", "Não Classificado")
    assert classificar_setor_por_mapa("ZZZZ3") == ("Outros", "Não Classificado")


def test_legado_outros_nao_e_confiavel_no_catalogo():
    macro, sub = classificar_setor_por_mapa("EMBR3")
    assert setor_confiavel(macro) is False
    assert setor_confiavel(sub) is False
    assert classificar_setor_catalogo("EMBR3") == SETOR_NAO_CLASSIFICADO
