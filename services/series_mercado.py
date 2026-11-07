"""Catálogo auditável de dados macro; coletores serão adicionados por fonte."""
SERIES_INICIAIS = (
    ("SELIC_EFETIVA", "Selic efetiva", "TAXA", "BCB/SGS 11", "DIARIA", "OFICIAL", "após divulgação BCB"),
    ("SELIC_META", "Meta Selic", "TAXA", "BCB/SGS 432", "DIARIA", "OFICIAL", "decisão Copom"),
    ("CDI", "CDI", "TAXA", "Fonte oficial a confirmar", "DIARIA", "OFICIAL", "fechamento"),
    ("IPCA", "IPCA", "INFLACAO", "IBGE/SIDRA 1737", "MENSAL", "OFICIAL", "divulgação IBGE"),
    ("USD_BRL_PTAX", "Dólar PTAX", "MOEDA", "BCB/PTAX", "DIARIA", "OFICIAL", "fechamento PTAX"),
    ("IBOV_FECHAMENTO", "Ibovespa", "INDICE", "B3", "DIARIA", "FECHAMENTO", "após pregão"),
    ("IFIX_FECHAMENTO", "IFIX", "INDICE", "B3", "DIARIA", "FECHAMENTO", "após pregão"),
)
