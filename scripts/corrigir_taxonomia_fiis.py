"""Executa a recuperação conservadora de setores/segmentos de FIIs."""
from services.taxonomia_fiis_automatica import corrigir_taxonomia_fiis


if __name__ == "__main__":
    print(corrigir_taxonomia_fiis())
