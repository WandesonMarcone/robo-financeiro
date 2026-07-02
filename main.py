import gspread

# --- CONFIGURAÇÕES ---
JSON_KEY = 'credenciais.json' 
SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk' 

def faxina_planilha():
    gc = gspread.service_account(filename=JSON_KEY)
    planilha = gc.open_by_url(SPREADSHEET_URL)
    aba = planilha.worksheet("Base de Dados")
    
    # Pega todos os dados
    linhas = aba.get_all_values()
    # cabeçalho = linhas[0] # Linha 1
    
    zumbis = []
    
    # Itera a partir da linha 2
    for i, linha in enumerate(linhas[1:], start=2):
        ticker = linha[0].strip().upper()
        preco = linha[1].strip()     # Coluna B
        liq = linha[26].strip()      # Coluna AA (Indice 26)
        
        # Critério de Zumbi: Preço vazio/zero OU Liquidez zero
        if preco == "" or preco == "0" or liq == "" or liq == "0":
            zumbis.append((i, ticker))
            
    print(f"--- RELATÓRIO DE FAXINA ---")
    print(f"Total de ações analisadas: {len(linhas)-1}")
    print(f"Total de ações 'Zumbis' encontradas: {len(zumbis)}")
    print("Primeiros 10 zumbis encontrados (Linha, Ticker):")
    for z in zumbis[:10]:
        print(f"Linha {z[0]}: {z[1]}")
        
    return zumbis

# Rode isso para ver quem está poluindo seu sistema
if __name__ == "__main__":
    lista_zumbis = faxina_planilha()
