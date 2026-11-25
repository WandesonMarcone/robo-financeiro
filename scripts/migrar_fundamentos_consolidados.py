"""Migra antes de iniciar a fila. Não exclui os backups de origem."""
import json
from services.fundamentos_consolidados import migrar
if __name__ == "__main__":
    resultado = migrar()
    from services.planilha_fundamentos_valuation import limpar_trimestres_antigos
    resultado["linhas_antigas_planilha_removidas"] = limpar_trimestres_antigos()
    print(json.dumps(resultado,ensure_ascii=False,default=str))
