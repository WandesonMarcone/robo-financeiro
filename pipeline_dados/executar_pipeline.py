import os
import sys
import time
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import func

# Adiciona o diretório atual ao path para evitar erros de importação
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from banco_dados import Base, DocumentosQualitativos
from coletor_cvm import AcoesCVMReader
from coletor_fnet import FiisFnetScraper

# Define onde o banco SQLite vai ser salvo na pasta
DB_PATH = "sqlite:///pipeline_dados/banco_institucional.db"

def executar_com_resiliencia(nome_motor, funcao_motor, max_tentativas=3, tempo_espera_segundos=300):
    """Tenta rodar um motor. Se falhar, espera e tenta de novo."""
    for tentativa in range(1, max_tentativas + 1):
        try:
            print(f"🚀 Iniciando {nome_motor} (Tentativa {tentativa}/{max_tentativas})...")
            
            # Tenta executar a função do motor
            funcao_motor()
            
            print(f"✅ {nome_motor} executado com sucesso na tentativa {tentativa}!")
            return True # Sai do loop se deu certo
            
        except Exception as e:
            import traceback
            print(f"💥 Falha no {nome_motor} na tentativa {tentativa}: {e}")
            traceback.print_exc()
            
            if tentativa < max_tentativas:
                minutos = tempo_espera_segundos // 60
                print(f"⏳ O servidor pode estar instável. Aguardando {minutos} minutos para tentar novamente...")
                time.sleep(tempo_espera_segundos) # O robô pausa aqui e espera
            else:
                print(f"❌ {nome_motor} falhou definitivamente após {max_tentativas} tentativas.")
                return False

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

        # Executa FNET com Resiliência (3 tentativas, 5 min de pausa)
        executar_com_resiliencia(
            nome_motor="Motor FIIs (FNET)", 
            funcao_motor=lambda: motor_fiis.atualizar_fiis(data_inicio),
            max_tentativas=3,
            tempo_espera_segundos=300
        )

        # 3. Roda o Coletor de Ações (CVM)
        print("\n--- MOTOR AÇÕES (CVM) ---")
        motor_acoes = AcoesCVMReader(session)
        ano_atual = data_hoje.year
        
        # Executa CVM com Resiliência (3 tentativas, 5 min de pausa)
        executar_com_resiliencia(
            nome_motor="Motor Ações (CVM)", 
            funcao_motor=lambda: motor_acoes.atualizar_acoes(ano_atual),
            max_tentativas=3,
            tempo_espera_segundos=300
        )

        print("\n✅ Todos os motores rodaram (ou tentaram rodar) com proteção de resiliência!")
        
    except Exception as e:
        import traceback
        print(f"❌ ERRO CRÍTICO NO PIPELINE:")
        traceback.print_exc() # Isso vai mostrar a linha exata do erro no log do GitHub
        session.rollback()

    finally:
        session.close()

# ==========================================
# GATILHO DE EXECUÇÃO
# ==========================================
if __name__ == "__main__":
    iniciar_motor()