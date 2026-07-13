import os
import sys
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import func
from datetime import datetime, timedelta

# Adiciona o diretório atual ao path para evitar erros de importação
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from banco_dados import Base, DocumentosQualitativos
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
        
        # Lógica Incremental: Busca a data mais recente no banco
        ultima_data = session.query(func.max(DocumentosQualitativos.data_publicacao)).scalar()
        if ultima_data:
            data_inicio = (ultima_data + timedelta(days=1)).strftime("%d/%m/%Y")
            print(f"🔄 Modo Incremental: Buscando dados a partir de {data_inicio}")
        else:
            data_inicio = "01/01/2026"
            print(f"💥 Modo Inicial: Buscando dados desde {data_inicio}")
            
        motor_fiis.atualizar_fiis(data_inicio)

        # 3. Roda o Coletor de Ações (CVM)
        print("\n--- MOTOR AÇÕES (CVM) ---")
        motor_acoes = AcoesCVMReader(session)
        ano_atual = data_hoje.year
        motor_acoes.atualizar_acoes(ano_atual)

        print("\n✅ Todos os motores rodaram com sucesso e os dados foram salvos!")
    except Exception as e:
        import traceback
        print(f"❌ ERRO CRÍTICO NO PIPELINE:")
        traceback.print_exc() # Isso vai mostrar a linha exata do erro no log do GitHub
        session.rollback()

    finally:
        session.close()