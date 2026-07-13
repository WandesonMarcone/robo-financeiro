import os
import sys
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Adiciona o diretório atual ao path para evitar erros de importação
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from banco_dados import Base
from coletor_cvm import AcoesCVMReader
from coletor_fnet import FiisFnetScraper

# Define onde o banco SQLite vai ser salvo na pasta
DB_PATH = "sqlite:///pipeline_dados/banco_institucional.db"

def iniciar_motor():
    print("🚀 Iniciando o Motor de Dados CVM/B3...")
    
    # 1. Cria a conexão e as tabelas (se não existirem)
    engine = create_engine(DB_PATH)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        data_hoje = datetime.now()
        
        # 2. Roda o Coletor de FIIs (FNET)
        print("\n--- MOTOR FIIs (FNET) ---")
        motor_fiis = FiisFnetScraper(session)
        # Puxa documentos a partir do dia 1º do mês atual
        # Puxa documentos desde o início do ano
        data_inicio = "01/01/2026"
        motor_fiis.atualizar_fiis(data_inicio)

        # 3. Roda o Coletor de Ações (CVM)
        print("\n--- MOTOR AÇÕES (CVM) ---")
        motor_acoes = AcoesCVMReader(session)
        ano_atual = data_hoje.year
        motor_acoes.atualizar_acoes(ano_atual)
        
        print("\n✅ Todos os motores rodaram com sucesso e os dados foram salvos!")
    except Exception as e:
        print(f"❌ Erro na execução do pipeline: {e}")
        session.rollback()
    finally:
        session.close()

if __name__ == "__main__":
    iniciar_motor()