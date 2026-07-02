import gspread
import yfinance as yf
from datetime import datetime

# --- CONFIGURAÇÕES ---
# Lista limpa e performática
ATIVOS = ["PETR4", "VALE3", "ITUB4", "BBDC4", "BBAS3", "B3SA3", "WEGE3", "ABEV3", 
          "SUZB3", "JBSS3", "GGBR4", "BBSE3", "CSAN3", "RADL3", "ELET3", "PRIO3", 
          "CMIG4", "VIVT3", "CPLE6", "MGLU3"]

def atualizar_carteira_elite():
    gc = gspread.service_account(filename='credenciais.json')
    aba = gc.open_by_url('https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk').worksheet("Base de Dados")
    
    # Prepara o lote de escrita
    batch_updates = []
    linha_atual = 2 # Começa na linha 2 (após cabeçalho)
    
    for ticker in ATIVOS:
        try:
            dados = yf.Ticker(f"{ticker}.SA").info
            preco = dados.get('currentPrice') or dados.get('regularMarketPrice') or 0
            pl = dados.get('trailingPE') or 0
            pvp = dados.get('priceToBook') or 0
            
            # Adiciona ao batch (Colunas B, E, F e AF)
            batch_updates.append({'range': f'B{linha_atual}', 'values': [[preco]]})
            batch_updates.append({'range': f'E{linha_atual}', 'values': [[pl]]})
            batch_updates.append({'range': f'F{linha_atual}', 'values': [[pvp]]})
            batch_updates.append({'range': f'AF{linha_atual}', 'values': [[f"{datetime.now().strftime('%H:%M')} OK"]]})
            
            linha_atual += 1
        except Exception as e:
            print(f"Erro em {ticker}: {e}")
            
    # Executa tudo de uma vez só
    if batch_updates:
        aba.batch_update(batch_updates)
        print(f"Sucesso! {len(ATIVOS)} ações atualizadas com alta performance.")

if __name__ == "__main__":
    atualizar_carteira_elite()
