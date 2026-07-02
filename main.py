import gspread
import pandas as pd
import yfinance as yf
import requests
import io
from datetime import datetime

def formatar_valor(val):
    # Garante que qualquer valor estranho vire zero para evitar erro de API
    try: return float(val) if val is not None and not pd.isna(val) else 0.0
    except: return 0.0

def atualizar_carteira_completa():
    gc = gspread.service_account(filename='credenciais.json')
    # Acessa a planilha
    aba = gc.open_by_url('https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk').worksheet("Base de Dados")
    
    # Lista de 17 ações
    ATIVOS = ["PETR4", "VALE3", "ITUB4", "BBDC4", "BBAS3", "B3SA3", "WEGE3", "ABEV3", 
              "SUZB3", "GGBR4", "BBSE3", "CSAN3", "RADL3", "CMIG4", "VIVT3", "MGLU3", "PRIO3"]
    
    # Busca Fundamentus uma única vez
    try:
        url = "https://www.fundamentus.com.br/resultado.php"
        df = pd.read_html(io.StringIO(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).text), decimal=',', thousands='.')[0]
        df['Papel'] = df['Papel'].str.strip().str.upper()
        df = df.set_index('Papel')
    except Exception as e:
        print(f"Erro Fundamentus: {e}")
        return

    batch_updates = []
    
    for i, ticker in enumerate(ATIVOS):
        linha_atual = i + 2 # Assume que a linha 1 é cabeçalho
        try:
            # 1. Dados Yahoo
            ticker_data = yf.Ticker(f"{ticker}.SA").info
            preco = formatar_valor(ticker_data.get('currentPrice') or ticker_data.get('regularMarketPrice'))
            
            # 2. Dados Fundamentus
            f = df.loc[ticker] if ticker in df.index else {}
            
            # 3. CONSTRUÇÃO DA LINHA (Tem que ter exatamente 31 campos de B a AF)
            # Ordem: B, C, D, E, F, G, H, I, J, K, L, M, N, O, P, Q, R, S, T, U, V, W, X, Y, Z, AA, AB, AC, AD, AE, AF
            row_data = [
                preco,                                      # B: Preço
                formatar_valor(f.get('Div.Yield', 0)),      # C: DY
                0,                                          # D: Nº Ações (Placeholder)
                formatar_valor(f.get('P/L', 0)),            # E: P/L
                formatar_valor(f.get('P/VP', 0)),           # F: P/VP
                0,                                          # G: P/Ativos
                formatar_valor(f.get('Marg. Bruta', 0)),    # H: Margem Bruta
                0,                                          # I: Margem EBIT
                formatar_valor(f.get('Marg. Líq.', 0)),     # J: Marg. Liquida
                formatar_valor(f.get('P/EBIT', 0)),         # K: P/EBIT
                formatar_valor(f.get('EV/EBIT', 0)),        # L: EV/EBIT
                0, 0,                                       # M, N: Dividas
                formatar_valor(f.get('PSR', 0)),            # O: PSR
                0, 0, 0, 0,                                 # P, Q, R, S
                formatar_valor(f.get('ROE', 0)),            # T: ROA
                formatar_valor(f.get('ROIC', 0)),           # U: ROIC
                0, 0, 0, 0, 0, 0,                           # V a AA
                formatar_valor(f.get('VPA', 0)),            # AB: VPA
                formatar_valor(f.get('LPA', 0)),            # AC: LPA
                0,                                          # AD: PEG Ratio
                formatar_valor(f.get('Valor de Mercado', 0)),# AE: Valor Mercado
                f"{datetime.now().strftime('%d/%m %H:%M')} OK" # AF: Atualização
            ]
            
            # Formato correto: lista contendo a linha (lista)
            batch_updates.append({'range': f'B{linha_atual}:AF{linha_atual}', 'values': [row_data]})
            
        except Exception as e:
            print(f"Erro ao processar {ticker}: {e}")
            
    # Execução única
    if batch_updates:
        aba.batch_update(batch_updates)
        print("Sucesso: Batch Update executado com sucesso!")

if __name__ == "__main__":
    atualizar_carteira_completa()