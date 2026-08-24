from pipeline_dados.banco_dados import TipoAtivo
from pipeline_dados.mapeamento_sheets import (
    MAPEADO,
    MAPEAMENTO_BD_ACOES,
    MAPEAMENTO_BD_FIIS,
    MAPEAMENTO_BD_LOGS,
    NAO_MAPEADO,
    TEMPORARIO,
    campos_sem_destino,
    lacunas,
    parsear_valor_market,
    resolver_cnpj,
    tipo_ativo_da_aba,
    transformar_linha_acao,
    transformar_linha_fii,
)
from pipeline_dados.normalizacao import normalizar_data


def linha_fii(extra=None):
    linha = [
        "MXRF11", "Papel", "CRI / Cotas de FIIs", 9.87, 500000000.0, 0.95, 0.12,
        0.0, 0, "Não informado", "Pendente de IA", "Pendente de IA", 1500000.0,
        4800000000.0, 10.39, 576000000.0, 0.0987, "19/08 10:00",
    ]
    if extra:
        linha.extend(extra)
    return linha


def linha_acao(extra=None):
    linha = [
        "PETR4", "Petróleo, Gás & Biocombustíveis", 37.52, 0.14, 12300000000.0,
        4.5, 1.2, 0.8, 0.55, 0.30, 0.12, 8.0, 5.0, 0.5, 0.8, 0.9, 1.2, 1.1,
        1.5, 0.18, 0.12, 0.16, 0, 0, 0, 0.10, 0, 85000000.0, 31.0, 8.3, 1.1,
        400000000000.0, "19/08 10:00",
    ]
    if extra:
        linha.extend(extra)
    return linha


# ==========================================
# ESTRUTURA DO MAPEAMENTO
# ==========================================

def test_mapeamento_fiis_tem_18_colunas():
    assert len(MAPEAMENTO_BD_FIIS) == 18


def test_mapeamento_acoes_tem_33_colunas():
    assert len(MAPEAMENTO_BD_ACOES) == 33


def test_bd_logs_e_classificado_como_log():
    assert all(col.classificacao == "LOG" for col in MAPEAMENTO_BD_LOGS)


def test_ticker_mapeado_para_ativo():
    for mapa in (MAPEAMENTO_BD_FIIS, MAPEAMENTO_BD_ACOES):
        ticker = next(col for col in mapa if col.nome == "ticker")
        assert ticker.classificacao == MAPEADO
        assert ticker.destino == "ativos.ticker"


def test_indicadores_de_mercado_tem_destino_no_schema_5b():
    fiis = {c.nome: c.destino for c in MAPEAMENTO_BD_FIIS}
    acoes = {c.nome: c.destino for c in MAPEAMENTO_BD_ACOES}
    assert fiis["preco"] == "snapshots_fiis.preco"
    assert fiis["pvp"] == "snapshots_fiis.pvp"
    assert fiis["dy"] == "snapshots_fiis.dy"
    assert fiis["vpa"] == "snapshots_fiis.vpa"
    assert acoes["pl"] == "snapshots_acoes.pl"
    assert acoes["roe"] == "snapshots_acoes.roe"
    assert acoes["setor"] == "ativos_perfil.setor"
    assert fiis["inquilinos"] == "ativos_inquilinos.nome"


def test_carimbo_e_temporario_cache():
    for mapa in (MAPEAMENTO_BD_FIIS, MAPEAMENTO_BD_ACOES):
        carimbo = next(col for col in mapa if col.nome == "carimbo")
        assert carimbo.classificacao == TEMPORARIO


# ==========================================
# TIPO DE ATIVO E CNPJ
# ==========================================

def test_tipo_ativo_da_aba():
    assert tipo_ativo_da_aba("BD_FIIs") is TipoAtivo.FII
    assert tipo_ativo_da_aba("BD_Acoes") is TipoAtivo.ACAO
    assert tipo_ativo_da_aba("BD_Logs") is None


def test_resolver_cnpj_acao_pelo_catalogo():
    assert resolver_cnpj("PETR4", TipoAtivo.ACAO) == "33.000.167/0001-01"


def test_resolver_cnpj_acao_fora_do_catalogo_usa_placeholder():
    assert resolver_cnpj("ZZZZ3", TipoAtivo.ACAO) == "PENDENTE-ZZZZ3"


def test_resolver_cnpj_fii_usa_placeholder():
    assert resolver_cnpj("MXRF11", TipoAtivo.FII) == "PENDENTE-MXRF11"


# ==========================================
# TRANSFORMAÇÃO / NORMALIZAÇÃO
# ==========================================

def test_transformar_linha_fii_normaliza_campos():
    dados = transformar_linha_fii(linha_fii())
    assert dados["ticker"] == "MXRF11"
    assert dados["preco"] == 9.87
    assert dados["dy"] == 0.12
    assert dados["vpa"] == 10.39
    assert dados["qtd_imoveis"] == 0
    assert dados["carimbo"] == "19/08 10:00"


def test_transformar_linha_acao_normaliza_campos():
    dados = transformar_linha_acao(linha_acao())
    assert dados["ticker"] == "PETR4"
    assert dados["pl"] == 4.5
    assert dados["pvp"] == 1.2
    assert dados["roe"] == 0.18
    assert dados["valor_mercado"] == 400000000000.0


def test_transformar_linha_ticker_em_minusculas_fica_maiusculo():
    linha = linha_fii()
    linha[0] = "mxrf11"
    assert transformar_linha_fii(linha)["ticker"] == "MXRF11"


def test_transformar_linha_curta_preserva_none():
    dados = transformar_linha_fii(["GARE11"])
    assert dados["ticker"] == "GARE11"
    assert dados["preco"] is None
    assert dados["pvp"] is None
    assert dados["carimbo"] is None


def test_transformar_linha_vazia_retorna_ticker_none():
    dados = transformar_linha_fii(["", "", ""])
    assert dados["ticker"] is None


# ==========================================
# NÚMEROS BRASILEIROS E NONE
# ==========================================

def test_parsear_valor_market_formato_br():
    assert parsear_valor_market("R$ 1.234,56") == 1234.56
    assert parsear_valor_market("R$ 1,50") == 1.5
    assert parsear_valor_market("11,5%") == 11.5
    assert parsear_valor_market("0") == 0.0
    assert parsear_valor_market(0) == 0.0


def test_parsear_valor_market_nunca_vira_zero():
    assert parsear_valor_market(None) is None
    assert parsear_valor_market("") is None
    assert parsear_valor_market("   ") is None
    assert parsear_valor_market("-") is None
    assert parsear_valor_market("N/A") is None
    assert parsear_valor_market("R$ abc") is None
    assert parsear_valor_market("erro_de_coleta") is None


# ==========================================
# DATAS: O CARIMBO NÃO GERA DATA_REFERENCIA
# ==========================================

def test_carimbo_nao_vira_data_referencia():
    carimbo = transformar_linha_fii(linha_fii())["carimbo"]
    assert normalizar_data(carimbo) is None


def test_data_referencia_registrada_como_lacuna():
    for nome_aba in ("BD_FIIs", "BD_Acoes"):
        assert any(l.startswith("data_referencia") for l in lacunas(nome_aba))


# ==========================================
# LACUNAS
# ==========================================

def test_campos_ambiguos_permanecem_sem_destino():
    for nome in ("numero_cotas", "vacancia", "valor_mercado"):
        col = next(c for c in MAPEAMENTO_BD_FIIS if c.nome == nome)
        assert col.classificacao == NAO_MAPEADO
        assert col.destino is None
    col = next(c for c in MAPEAMENTO_BD_ACOES if c.nome == "qtd_acoes")
    assert col.classificacao == NAO_MAPEADO
    assert col.destino is None


def test_campos_sem_destino_restam_apenas_os_ambiguos():
    assert campos_sem_destino("BD_FIIs") == {"numero_cotas", "vacancia", "valor_mercado"}
    assert campos_sem_destino("BD_Acoes") == {"qtd_acoes"}
    assert "preco" not in campos_sem_destino("BD_FIIs")
    assert "roe" not in campos_sem_destino("BD_Acoes")


def test_lacunas_nao_incluem_ticker_nem_carimbo():
    for nome_aba in ("BD_FIIs", "BD_Acoes"):
        assert "ticker" not in lacunas(nome_aba)
        assert "carimbo" not in lacunas(nome_aba)


def test_lacunas_transversais_documentadas():
    for nome_aba in ("BD_FIIs", "BD_Acoes"):
        assert any(l.startswith("cnpj") for l in lacunas(nome_aba))
