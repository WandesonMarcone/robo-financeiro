"""Executado antes das oportunidades e da atualização noturna."""
import json
from services.cadastro_cnpj_oficial import sincronizar

if __name__ == "__main__":
    resultado = sincronizar()
    print(json.dumps(resultado, ensure_ascii=False, default=str))
    if resultado["nao_localizados"]:
        print("::warning::CNPJs ainda não confirmados: " + ", ".join(resultado["nao_localizados"]))
