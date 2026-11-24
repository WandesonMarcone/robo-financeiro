"""Executa a recuperação conservadora de setores/segmentos de FIIs."""
import argparse

from services.taxonomia_fiis_automatica import corrigir_taxonomia_fiis


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--usar-contingencia", action="store_true")
    args = parser.parse_args()
    print(corrigir_taxonomia_fiis(usar_contingencia=args.usar_contingencia))
