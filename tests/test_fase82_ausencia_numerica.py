"""Fase 8.2: ausência/erro numérico não vira 0.0; zero real é preservado."""
import pandas as pd

from modules.scraper_acoes import (
    _bloco_telegram_acao,
    derivar_pl,
    derivar_pvp,
    limpar_porcentagem_df,
    montar_linha_acao,
)
from modules.scraper_fiis import montar_linha_fii
from modules.utils import celula_planilha, formatar
from pipeline_dados.coletor_cvm import derivar_indicadores_cvm


def test_formatar_zero_real_versus_ausencia():
    assert formatar(0) == 0.0
    assert formatar("0") == 0.0
    assert formatar("0%") == 0.0
    assert formatar(None) is None
    assert formatar("") is None
    assert formatar("   ") is None
    assert formatar("abc") is None
    assert formatar(float("nan")) is None
    assert formatar(float("inf")) is None
    assert formatar("-") is None
    assert formatar("12,5%") == 0.125


def test_formatar_nao_mascara_nan_pandas():
    assert formatar(pd.NA) is None
    assert formatar(pd.NaT) is None
    serie = pd.Series([float("nan")])
    assert formatar(serie.iloc[0]) is None


def test_celula_planilha_none_vira_vazio_zero_permanece():
    assert celula_planilha(None) == ""
    assert celula_planilha(0.0) == 0.0
    assert celula_planilha(0) == 0
    assert celula_planilha(12.5) == 12.5
    assert celula_planilha("") == ""


def test_limpar_porcentagem_df_zero_e_ausencia():
    assert limpar_porcentagem_df("0%") == 0.0
    assert limpar_porcentagem_df(0) == 0.0
    assert limpar_porcentagem_df("8,0%") == 0.08
    assert limpar_porcentagem_df("") is None
    assert limpar_porcentagem_df(None) is None
    assert limpar_porcentagem_df(float("nan")) is None
    assert limpar_porcentagem_df("abc") is None


def test_montar_linha_acao_none_e_reservados_vazios():
    linha = montar_linha_acao(
        "Financeiro", 0.0, None, 0.0, None, 1.2, None, 0.0, None, None,
        None, None, None, 0.0, None, None, None, None, 0.0, None, None,
        None, None, None, None, None, None, "02/09 10:00",
    )
    assert linha[0] == "Financeiro"
    assert linha[1] == 0.0
    assert linha[2] == ""
    assert linha[3] == 0.0
    assert linha[4] == ""
    assert linha[5] == 1.2
    assert linha[7] == 0.0
    assert linha[18] == 0.0
    assert linha[21] == ""
    assert linha[22] == ""
    assert linha[23] == ""
    assert linha[25] == ""
    assert 0 not in (linha[21], linha[22], linha[23], linha[25])
    assert linha[-1] == "02/09 10:00"


def test_derivar_pl_pvp_nao_inventa_zero():
    assert derivar_pl(0, 10, 2) == 0.0
    assert derivar_pl(8.5, 10, 2) == 8.5
    assert derivar_pl(None, 10, 2) == 5.0
    assert derivar_pl(None, 10, 0) is None
    assert derivar_pl(None, 10, None) is None
    assert derivar_pl(None, None, 2) is None
    assert derivar_pvp(0, 10, 5) == 0.0
    assert derivar_pvp(None, 10, 5) == 2.0
    assert derivar_pvp(None, 10, 0) is None
    assert derivar_pvp(None, None, 5) is None


def test_telegram_acao_none_vira_nd():
    texto = _bloco_telegram_acao("PETR4", None, None, None, None, None)
    assert "N/D" in texto
    assert "0.00" not in texto
    texto_zero = _bloco_telegram_acao("VALE3", 0.0, 0.0, 0.0, 0.0, 0.0)
    assert "R$ 0.00" in texto_zero
    assert "P/L: 0.0" in texto_zero
    assert "ROE: 0.0%" in texto_zero


def test_montar_linha_fii_none_versus_zero():
    linha = montar_linha_fii(
        "MXRF11", "Papel", "CRI", 9.87, None, 0.95, 0.0, None,
        0, "Não informado / Não aplicável", None, None,
        None, None, 0.0, "02/09 10:00",
    )
    assert linha[0] == "MXRF11"
    assert linha[3] == 9.87
    assert linha[4] == ""
    assert linha[5] == 0.95
    assert linha[6] == 0.0
    assert linha[7] == ""
    assert linha[8] == 0
    assert linha[10] == "Pendente de IA"
    assert linha[11] == "Pendente de IA"
    assert linha[12] == ""
    assert linha[16] == 0.0


def _reg_cvm(**kwargs):
    base = {
        "divida_curto_prazo": None,
        "divida_longo_prazo": None,
        "caixa": None,
        "ebit": None,
        "depreciacao": None,
    }
    base.update(kwargs)
    return base


def test_cvm_zero_informado_preservado():
    reg = derivar_indicadores_cvm(_reg_cvm(
        divida_curto_prazo=0.0, divida_longo_prazo=0.0, caixa=0.0,
        ebit=0.0, depreciacao=0.0,
    ))
    assert reg["divida_bruta"] == 0.0
    assert reg["divida_liquida"] == 0.0
    assert reg["ebitda"] == 0.0
    assert "ebit" not in reg
    assert "depreciacao" not in reg


def test_cvm_conta_ausente_nao_vira_zero():
    so_cp = derivar_indicadores_cvm(_reg_cvm(divida_curto_prazo=100.0, caixa=10.0))
    assert so_cp["divida_bruta"] is None
    assert so_cp["divida_liquida"] is None

    sem_caixa = derivar_indicadores_cvm(_reg_cvm(
        divida_curto_prazo=100.0, divida_longo_prazo=50.0,
    ))
    assert sem_caixa["divida_bruta"] == 150.0
    assert sem_caixa["divida_liquida"] is None

    sem_dep = derivar_indicadores_cvm(_reg_cvm(ebit=80.0))
    assert sem_dep["ebitda"] is None

    sem_ebit = derivar_indicadores_cvm(_reg_cvm(depreciacao=10.0))
    assert sem_ebit["ebitda"] is None


def test_cvm_derivacao_completa():
    reg = derivar_indicadores_cvm(_reg_cvm(
        divida_curto_prazo=40.0, divida_longo_prazo=60.0, caixa=15.0,
        ebit=100.0, depreciacao=-20.0,
    ))
    assert reg["divida_bruta"] == 100.0
    assert reg["divida_liquida"] == 85.0
    assert reg["ebitda"] == 120.0
