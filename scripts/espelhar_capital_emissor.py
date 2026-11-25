"""Atualiza apenas AK:AL da BD_Acoes, usando o capital conciliado no Neon."""
from services.capital_emissor import espelhar_planilha

if __name__ == "__main__":
    print(f"Capital conciliado espelhado: {espelhar_planilha()} tickers")
