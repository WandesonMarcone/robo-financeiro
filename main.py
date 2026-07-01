import gspread
from datetime import datetime

def testar_conexao(request):
    print("Iniciando Teste de Conexão...")
    JSON_KEY = 'credenciais.json' 
    SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk' 

    try:
        gc = gspread.service_account(filename=JSON_KEY)
        planilha = gc.open_by_url(SPREADSHEET_URL)
        aba = planilha.worksheet("Base de Dados")
        
        # Tenta escrever um teste na célula AF1
        aba.update_acell('AF1', "TESTE OK - " + datetime.now().strftime('%H:%M:%S'))
        print("Sucesso! Escrevi na célula AF1.")
        return "Sucesso"
    except Exception as e:
        print(f"ERRO CRÍTICO: {e}")
        return "Erro"

if __name__ == "__main__":
    testar_conexao(None)
