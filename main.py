import gspread
import pandas as pd
import yfinance as yf
import requests
import json
import pytz
import urllib.parse
from datetime import datetime
import io

# --- CONFIGURAÇÕES ---
TELEFONE_WHATSAPP = "553491503895" 
API_KEY_WHATSAPP = "5116767"

def get_horario_brasilia():
    tz = pytz.timezone('America/Sao_Paulo')
    return datetime.now(tz)

def formatar_valor(val):
    # Garante que o valor seja um número válido para o Google Sheets
    try:
        if val is None or pd.isna(val): return 0
        return float(val)
    except: return 0

def atualizar_financeiro(request):
    print("Iniciando Mestre Otimizado...")
    JSON_KEY = 'credenciais.json' 
    gc = gspread.service_account(filename=JSON_KEY)
    planilha = gc.open_by_url('https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk')
    aba_base = planilha.worksheet("Base de Dados")
    
    # 1. CARREGAR ATIVOS
    ativos_core = ["ITUB4", "BBAS3", "PSSA3", "CMIG4", "VALE3", "SANB11", "SBSP3", "BBSE3", "BBDC3", "PETR4", "BBDC4", "B3SA3"]
    
    # 2. BUSCA DE OPORTUNIDADES
    try:
        url = "https://www.fundamentus.com.br/resultado.php"
        df = pd.read_html(io.StringIO(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).text), decimal=',', thousands='.')[0]
        df.columns = df.columns.str.strip()
        df['Papel'] = df['Papel'].str.strip().str.upper()
        df['Div.Yield'] = pd.to_numeric(df['Div.Yield'].astype(str).str.replace('%','').str.replace('.','').str.replace(',','.'), errors='coerce') / 100
        df['P/L'] = pd.to_numeric(df['P/L'], errors='coerce')
        df['P/VP'] = pd.to_numeric(df['P/VP'], errors='coerce')
        opps = df[(df['Div.Yield'] > 0.06) & (df['P/L'] < 15) & (df['P/VP'] < 2)]['Papel'].tolist()
        ativos_finais = list(set(ativos_core + opps))[:20] # Máximo 20 ativos para não estourar cota
        fund_data = df.set_index('Papel').to_dict('index')
    except: 
        ativos_finais = ativos_core
        fund_data = {}

    # 3. PREPARAÇÃO DE ESCRITA
    todas_linhas = aba_base.get_all_values()
    coluna_a = [linha[0].strip().upper() if len(linha) > 0 else "" for linha in todas_linhas]
    
    batch_updates = []
    dados_ag1 = {}
    agora = get_horario_brasilia().strftime('%H:%M')

    # 4. LOOP
    for ticker in ativos_finais:
        if ticker not in coluna_a: continue
        linha = coluna_a.index(ticker) + 1
        
        try:
            acao = yf.Ticker(f"{ticker}.SA").info
            y_p = formatar_valor(acao.get('currentPrice') or acao.get('regularMarketPrice'))
            y_pl = formatar_valor(acao.get('trailingPE'))
            y_pvp = formatar_valor(acao.get('priceToBook'))
            y_dy = formatar_valor(acao.get('dividendYield'))
            
            f = fund_data.get(ticker, {})
            f_pl = formatar_valor(f.get('P/L'))
            f_pvp = formatar_valor(f.get('P/VP'))
            f_dy = formatar_valor(f.get('Div.Yield'))

            # Consenso Simples (Diferença < 20%)
            if abs(y_pl - f_pl) < (f_pl * 0.2) or f_pl == 0:
                batch_updates.append({'range': f'B{linha}', 'values': [[y_p]]})
                batch_updates.append({'range': f'C{linha}', 'values': [[(y_dy + f_dy)/2]]})
                batch_updates.append({'range': f'E{linha}', 'values': [[(y_pl + f_pl)/2]]})
                batch_updates.append({'range': f'F{linha}', 'values': [[(y_pvp + f_pvp)/2]]})
                batch_updates.append({'range': f'AH{linha}', 'values': [[f"{agora} OK"]]})
            else:
                dados_ag1[ticker] = {"linha": linha, "status": "Divergência"}
        except: continue

    # 5. ESCRITA ÚNICA (BATEU O BATCH UPDATE)
    if batch_updates: aba_base.batch_update(batch_updates)
    aba_base.update_acell('AG1', json.dumps({"DADOS": dados_ag1}))
    return "Sucesso."

if __name__ == "__main__":
    atualizar_financeiro(None)