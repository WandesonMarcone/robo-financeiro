"""Migra antes de iniciar a fila. Não exclui os backups de origem."""
import json
from services.fundamentos_consolidados import migrar
if __name__ == "__main__":
    print(json.dumps(migrar(),ensure_ascii=False,default=str))
