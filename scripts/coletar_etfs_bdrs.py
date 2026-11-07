"""Executável do GitHub Actions para ETFs e BDRs cadastrados no Neon."""
from services.coletor_etfs_bdrs import coletar_instrumentos_ativos

if __name__ == "__main__":
    print(coletar_instrumentos_ativos())
