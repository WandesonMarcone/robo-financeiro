"""Cadastra a seleção inicial de ETFs e BDRs sem executar coleta."""
from services.coletor_etfs_bdrs import cadastrar_base_inicial


if __name__ == "__main__":
    print(cadastrar_base_inicial())
