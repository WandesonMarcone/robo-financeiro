import gspread
import pandas as pd
import yfinance as yf
import requests
import io
from datetime import datetime

def formatar(val):
    try: return float(val) if val is not None and not pd.isna(val) else 0.0
    except: return 0.0

def atualizar_financeiro():
    # 1. Configuração
    gc = gspread.service_account(filename='credenciais.json')
    aba = gc.open_by_url('https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk').worksheet("Base de Dados")
    
    # 2. BUSCA
    url = "https://www.fundamentus.com.br/resultado.php"
    df = pd.read_html(io.StringIO(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).text), decimal=',', thousands='.')[0]
    df['Papel'] = df['Papel'].str.strip().str.upper()
    df = df.set_index('Papel')

    # 3. FILA DE 14 (Fixas + Oportunidades + Antigas)
    # [Lógica simplificada para focar na escrita]
    
    batch_updates = []
    
    # Exemplo para a lista que você decidir (coloque seus 17 aqui)
    ATIVOS = ["PETR4", "VALE3", "ITUB4", "BBDC4", "BBAS3", "B3SA3", "WEGE3", "ABEV3", "SUZB3", "GGBR4", "BBSE3", "CSAN3", "RADL3", "CMIG4", "VIVT3", "MGLU3", "PRIO3"]
    
    for i, ticker in enumerate(ATIVOS):
        linha = i + 2 # Ajuste conforme sua planilha
        f = df.loc[ticker] if ticker in df.index else {}
        
        # Mapeamento exato conforme colunas B até AF
        row = [
            formatar(yf.Ticker(f"{ticker}.SA").info.get('currentPrice', 0)), # B: Preço
            formatar(f.get('Div.Yield', 0)), # C: DY
            0,                               # D: Nº Ações (Indisponível)
            formatar(f.get('P/L', 0)),       # E: P/L
            formatar(f.get('P/VP', 0)),      # F: P/VP
            formatar(f.get('P/Ativo', 0)),   # G: P/Ativos
            formatar(f.get('Mrg Bruta', 0)), # H: Margem Bruta
            formatar(f.get('Mrg Ebit', 0)),  # I: Margem EBIT
            formatar(f.get('Mrg. Líq.', 0)), # J: Marg. Liquida
            formatar(f.get('P/EBIT', 0)),    # K: P/EBIT
            formatar(f.get('EV/EBIT', 0)),   # L: EV/EBIT
            0,                               # M: Div.Liq/Ebit (Indisponível)
            formatar(f.get('Dív.Líq/ Patrim.', 0)), # N: Div.Liq/Patri
            formatar(f.get('PSR', 0)),       # O: PSR
            formatar(f.get('P/Cap.Giro', 0)),# P: P/Cap.Giro
            formatar(f.get('P/Ativ Circ.Liq', 0)), # Q: P.At.Cir.Liq
            formatar(f.get('Liq. Corr.', 0)),# R: Liq. Corr
            formatar(f.get('ROE', 0)),       # S: ROE
            0,                               # T: ROA (Indisponível)
            formatar(f.get('ROIC', 0)),      # U: ROIC
            0, 0, 0,                         # V, W, X
            formatar(f.get('Cresc. Rec.5a', 0)), # Y: CAGR Receitas
            0,                               # Z: CAGR Lucros
            formatar(f.get('Liq.2meses', 0)),# AA: Liq. Media
            0, 0, 0,                         # AB, AC, AD
            0,                               # AE: Valor Mercado (Requer cálculo)
            f"{datetime.now().strftime('%d/%m %H:%M')} OK" # AF: Data
        ]
        batch_updates.append({'range': f'B{linha}:AF{linha}', 'values': [row]})

    aba.batch_update(batch_updates)
    print("Sucesso: Dados mapeados e inseridos.")

if __name__ == "__main__":
    atualizar_financeiro()