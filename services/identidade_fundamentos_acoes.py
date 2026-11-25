"""Resolve identidade oficial utilizando o mesmo parser do cadastro central."""
from datetime import date
from pipeline_dados.coletor_catalogo_cvm import ColetorCatalogoCVM
from services.cadastro_cnpj_oficial import extrair_cadastro

def mapa_fca(geral, valores):
    # Compatibilidade com fixtures antigas; o arquivo oficial tem ambas as colunas.
    geral = geral.copy()
    valores = valores.copy()
    if "Nome_Empresarial" not in geral:
        geral["Nome_Empresarial"] = geral["CNPJ_Companhia"]
    if "Data_Fim_Negociacao" not in valores:
        valores["Data_Fim_Negociacao"] = ""
    mapa, _ = extrair_cadastro(geral,valores)
    return {ticker: dict(item, classe="ACAO", fonte_cadastro="FCA_CVM") for ticker,item in mapa.items()}

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
                print(f"FCA {self.ano}: {len(self.mapa)} vínculos para coleta de fundamentos")
                if not self.mapa:
                    self.falha = "SEM_VINCULOS"
            except Exception as exc:
                self.falha = type(exc).__name__
                print(f"FCA {self.ano}: {self.falha}: {str(exc)[:200]}")
        return self.mapa.get(ticker)
