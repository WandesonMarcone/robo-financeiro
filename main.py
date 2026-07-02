import gspread
import pandas as pd
import yfinance as yf
import requests
import io
import random
from datetime import datetime

# --- CONFIGURAÇÕES ---
FIXAS = ["PETR4", "VALE3", "ITUB4", "BBDC4"] 
JSON_KEY = 'credenciais.json' 
SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk' 

def formatar(val):
    try: return float(val) if val is not None and not pd.isna(val) else 0.0
    except: return 0.0

def atualizar_financeiro(request=None):
    gc = gspread.service_account(filename=JSON_KEY)
    planilha = gc.open_by_url(SPREADSHEET_URL)
    aba_base = planilha.worksheet("Base de Dados")
    aba_metodo = planilha.worksheet("Metodologia Projetiva")
    
    # 1. BUSCA DADOS FUNDAMENTUS E DEFINIÇÃO DE FILA
    try:
        url = "https://www.fundamentus.com.br/resultado.php"
        df = pd.read_html(io.StringIO(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).text), decimal=',', thousands='.')[0]
        df['Papel'] = df['Papel'].str.strip().str.upper()
        df = df.set_index('Papel')
    except: df = pd.DataFrame()

    # Identificar Oportunidades (P/L < 12 e P/VP < 1.5)
    opps = df[(df['P/L'].astype(float) < 12) & (df['P/VP'].astype(float) < 1.5)].index.tolist()[:5]
    
    # Identificar C3
    ticker_c3 = str(aba_metodo.acell('C3').value).strip().upper()
    
    # Identificar Aleatórias (3)
    todas = aba_base.col_values(1)[1:] # Coluna A
    aleatorias = random.sample(todas, min(len(todas), 3))
    
    # Fila final única (sem repetir)
    fila = list(set(FIXAS + [ticker_c3] + opps + aleatorias))
    fila = [t for t in fila if t in todas] # Garante que está na planilha

    # 2. PROCESSAMENTO
    batch_updates = []
    
    for ticker in fila:
        linha_idx = todas.index(ticker) + 2
        try:
            # Dados Yahoo
            yf_data = yf.Ticker(f"{ticker}.SA").info
            preco = formatar(yf_data.get('currentPrice') or yf_data.get('regularMarketPrice'))
            
            # Dados Fundamentus
            f = df.loc[ticker] if ticker in df.index else {}
            
            # Mapeamento Completo (B a AF)
            row = [
                preco, formatar(f.get('Div.Yield', 0)), 0, formatar(f.get('P/L', 0)), 
                formatar(f.get('P/VP', 0)), formatar(f.get('P/Ativo', 0)), formatar(f.get('Mrg Bruta', 0)),
                formatar(f.get('Mrg Ebit', 0)), formatar(f.get('Mrg. Líq.', 0)), formatar(f.get('P/EBIT', 0)),
                formatar(f.get('EV/EBIT', 0)), 0, formatar(f.get('Dív.Líq/ Patrim.', 0)), formatar(f.get('PSR', 0)),
                formatar(f.get('P/Cap.Giro', 0)), formatar(f.get('P/Ativ Circ.Liq', 0)), formatar(f.get('Liq. Corr.', 0)),
                formatar(f.get('ROE', 0)), 0, formatar(f.get('ROIC', 0)), 0, 0, 0, 
                formatar(f.get('Cresc. Rec.5a', 0)), 0, formatar(f.get('Liq.2meses', 0)),
                formatar(f.get('VPA', 0)), formatar(f.get('LPA', 0)), 0, formatar(f.get('Valor de Mercado', 0)),
                f"{datetime.now().strftime('%d/%m %H:%M')} OK"
            ]
            batch_updates.append({'range': f'B{linha_idx}:AF{linha_idx}', 'values': [row]})
        except Exception as e: print(f"Erro {ticker}: {e}")

    # 3. ESCRITA EM LOTE
    if batch_updates:
        aba_base.batch_update(batch_updates)
        print(f"Atualizado lote de {len(fila)} ativos.")

if __name__ == "__main__":
    atualizar_financeiro()
