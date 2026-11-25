"""Resolve ticker de ação pelo FCA oficial, sem alterar cadastros legados."""
from datetime import date
from pipeline_dados.coletor_catalogo_cvm import (
    ColetorCatalogoCVM, _selecionar_mais_recente, _texto, _sem_acento, _mercado_valido,
)
from pipeline_dados.coletor_fiis import normalizar_cnpj

def mapa_fca(geral, valores):
    setores = {}
    for _, linha in _selecionar_mais_recente(geral, ["CNPJ_Companhia"]).iterrows():
        cnpj = normalizar_cnpj(_texto(linha.get("CNPJ_Companhia")))
        if cnpj:
            setores[cnpj] = _texto(linha.get("Setor_Atividade"))
    candidatos = {}
    for _, linha in _selecionar_mais_recente(valores, ["CNPJ_Companhia", "Codigo_Negociacao"]).iterrows():
        ticker = _texto(linha.get("Codigo_Negociacao")).upper()
        cnpj = normalizar_cnpj(_texto(linha.get("CNPJ_Companhia")))
        tipo = _sem_acento(linha.get("Tipo"))
        if not ticker or cnpj not in setores or not _mercado_valido(linha.get("Mercado")):
            continue
        if not any(t in tipo for t in ("acao", "acoes", "unit")) or _texto(linha.get("Data_Fim_Negociacao")):
            continue
        candidatos.setdefault(ticker, {})[cnpj] = setores[cnpj]
    return {ticker: {"ticker": ticker, "cnpj": next(iter(v)), "classe": "ACAO",
                     "setor": next(iter(v.values())), "fonte_cadastro": "FCA_CVM"}
            for ticker, v in candidatos.items() if len(v) == 1}

class IdentidadeFCA:
    def __init__(self, http_get=None, ano=None):
        self.coletor = ColetorCatalogoCVM(http_get=http_get)
        self.ano = ano or date.today().year
        self.mapa = None
        self.falha = None

    def __call__(self, ticker):
        if self.mapa is None:
            self.mapa = {}
            try:
                geral, valores, _ = self.coletor.baixar_dataframes(self.ano)
                self.mapa = mapa_fca(geral, valores)
            except Exception as exc:
                self.falha = type(exc).__name__
        return self.mapa.get(ticker)
