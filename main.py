import gspread
import pandas as pd
import yfinance as yf
import requests
import io
from datetime import datetime

# --- CONFIGURAÇÕES ---
FIXAS = ["PETR4", "VALE3", "ITUB4", "BBAS3"] # Suas 4 fixas

def atualizar_carteira_inteligente():
    gc = gspread.service_account(filename='credenciais.json')
    aba = gc.open_by_url('https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk').worksheet("Base de Dados")
    
    # 1. BUSCA DADOS DE TODA A BOLSA
    try:
        url = "https://www.fundamentus.com.br/resultado.php"
        df = pd.read_html(io.StringIO(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).text), decimal=',', thousands='.')[0]
        df['Papel'] = df['Papel'].str.strip().str.upper()
        df = df.set_index('Papel')
    except: return

    # 2. SELEÇÃO DE OPORTUNIDADES
    # Filtro: P/L entre 0.1 e 12, P/VP < 1.5 e Liquidez > 1 Milhão
    opps = df[(df['P/L'] > 0.1) & (df['P/L'] < 12) & (df['P/VP'] < 1.5) & (df['Liq.2meses'] > 1000000)].index.tolist()
    opps = [o for o in opps if o not in FIXAS][:5] # 5 Oportunidades

    # 3. FILA DE MANUTENÇÃO (5 mais antigas)
    linhas = aba.get_all_values()
    candidatas = []
    for i, linha in enumerate(linhas[1:], start=2):
        if linha[0] not in FIXAS and linha[0] not in opps:
            candidatas.append({'ticker': linha[0], 'linha': i, 'data': linha[31]})
    # Ordena pelas que têm data mais antiga na coluna AF
    candidatas.sort(key=lambda x: x['data'] if x['data'] else "00/00")
    manutencao = [c['ticker'] for c in candidatas[:5]]

    # Fila final de 14 ações
    fila = list(set(FIXAS + opps + manutencao))
    
    # 4. ESCRITA EM LOTE
    batch_updates = []
    print(f"Processando fila: {fila}")
    
    for ticker in fila:
        # Encontra a linha na planilha
        row_idx = next((i for i, l in enumerate(linhas) if l[0] == ticker), None)
        if not row_idx: continue
        
        try:
            f = df.loc[ticker]
            # row = [Preço, DY, Nº Ações, P/L, P/VP, P/Ativo, Bruta, EBIT, Liq, P/EBIT, EV/EBIT, Div/EBIT, Div/Patri, PSR, P/CapGiro, P/At.Cir, LiqCorr, ROE, ROA, ROIC, Pat/At, Pas/At, GiroAt, CAGR Rec, CAGR Luc, LiqMed, VPA, LPA, PEG, ValMerc, Atualizacao]
            row = [
                0, f.get('Div.Yield', 0), 0, f.get('P/L', 0), f.get('P/VP', 0), f.get('P/Ativo', 0), 
                f.get('Mrg Bruta', 0), f.get('Mrg Ebit', 0), f.get('Mrg. Líq.', 0), f.get('P/EBIT', 0), 
                f.get('EV/EBIT', 0), 0, 0, f.get('PSR', 0), 0, 0, 0, f.get('ROE', 0), 0, 
                f.get('ROIC', 0), 0, 0, 0, 0, 0, f.get('Liq.2meses', 0), f.get('VPA', 0), 
                f.get('LPA', 0), 0, f.get('Valor de Mercado', 0), 
                f"{datetime.now().strftime('%d/%m %H:%M')} OK"
            ]
            batch_updates.append({'range': f'B{row_idx+1}:AF{row_idx+1}', 'values': [row]})
        except: continue

    if batch_updates:
        aba.batch_update(batch_updates)
        print(f"Atualizadas {len(batch_updates)} ações.")

if __name__ == "__main__":
    atualizar_financeiro_inteligente()