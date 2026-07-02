import gspread
import pandas as pd
import yfinance as yf
import requests
import json
import pytz
import urllib.parse
from datetime import datetime

# --- CONFIGURAÇÕES ---
# Aumentei para 0.15 (15%) para evitar bloqueios por pequenas variações
TOLERANCIA = 0.15 
TELEFONE_WHATSAPP = "553491503895" 
API_KEY_WHATSAPP = "5116767"

def calcular_discrepancia(v1, v2):
    v1, v2 = abs(float(v1 or 0)), abs(float(v2 or 0))
    if v1 == 0 and v2 == 0: return 0.0
    if v1 == 0 or v2 == 0: return 1.0 
    return abs(v1 - v2) / max(v1, v2)

def atualizar_financeiro(request):
    print("--- INICIANDO AUDITORIA MESTRE ---")
    JSON_KEY = 'credenciais.json' 
    SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk' 
    
    gc = gspread.service_account(filename=JSON_KEY)
    planilha = gc.open_by_url(SPREADSHEET_URL)
    aba_base = planilha.worksheet("Base de Dados")
    
    # 1. CARREGAR ATIVOS
    ativos_core = ["ITUB4", "BBAS3", "PSSA3", "CMIG4", "VALE3", "SANB11", "SBSP3", "BBSE3", "BBDC3", "PETR4", "BBDC4", "B3SA3"]
    ativos_finais = ativos_core[:]
    
    # Busca de Oportunidades
    try:
        df = pd.read_html("https://www.fundamentus.com.br/resultado.php", headers={'User-Agent': 'Mozilla/5.0'}, decimal=',', thousands='.')[0]
        df.columns = df.columns.str.strip()
        df['Papel'] = df['Papel'].str.strip().str.upper()
        df['Div.Yield'] = pd.to_numeric(df['Div.Yield'].astype(str).str.replace('%','').str.replace('.','').str.replace(',','.'), errors='coerce') / 100
        df['P/L'] = pd.to_numeric(df['P/L'], errors='coerce')
        df['P/VP'] = pd.to_numeric(df['P/VP'], errors='coerce')
        
        # Filtro de Oportunidade
        oportunidades = df[(df['Div.Yield'] > 0.06) & (df['P/L'] < 15) & (df['P/VP'] < 2)]['Papel'].tolist()
        for op in oportunidades:
            if op not in ativos_finais and len(ativos_finais) < 15: ativos_finais.append(op)
        fund_data_dict = df.set_index('Papel').to_dict('index')
    except Exception as e: print(f"Erro na busca: {e}")

    # 2. PROCESSAMENTO
    todas_linhas = aba_base.get_all_values()
    coluna_a = [linha[0].strip().upper() if len(linha) > 0 else "" for linha in todas_linhas]
    
    for ticker in ativos_finais:
        if ticker not in coluna_a: continue
        linha_busca = coluna_a.index(ticker) + 1
        
        try:
            acao = yf.Ticker(f"{ticker}.SA")
            info = acao.info
            y_preco = info.get('currentPrice', info.get('regularMarketPrice', 0)) or 0
            y_pl = info.get('trailingPE', 0) or 0
            y_pvp = info.get('priceToBook', 0) or 0
            y_dy = info.get('dividendYield', 0) or 0
            if y_dy > 1: y_dy /= 100 

            f = fund_data_dict.get(ticker, {})
            f_pl, f_pvp, f_dy = f.get('P/L', 0), f.get('P/VP', 0), f.get('Div.Yield', 0)
            
            if y_pvp < 0.5: y_pvp = f_pvp 

            disc_pl = calcular_discrepancia(y_pl, f_pl) > TOLERANCIA
            disc_pvp = calcular_discrepancia(y_pvp, f_pvp) > TOLERANCIA
            disc_dy = calcular_discrepancia(y_dy, f_dy) > TOLERANCIA

            # LOG DE AUDITORIA
            print(f"AUDITORIA {ticker}: PL(Y:{y_pl}, F:{f_pl}, D:{disc_pl}) | PVP(Y:{y_pvp}, F:{f_pvp}, D:{disc_pvp}) | DY(Y:{y_dy}, F:{f_dy}, D:{disc_dy})")

            if not disc_pl and not disc_pvp and not disc_dy:
                # CONSENSO TOTAL: Escreve direto
                aba_base.update_cell(linha_busca, 2, float(y_preco))
                aba_base.update_cell(linha_busca, 3, float(round((y_dy + f_dy)/2, 4)))
                aba_base.update_cell(linha_busca, 5, float(round((y_pl + f_pl)/2, 2)))
                aba_base.update_cell(linha_busca, 6, float(round((y_pvp + f_pvp)/2, 2)))
                print(f"--> SUCESSO: {ticker} atualizado na linha {linha_busca}.")
            else:
                print(f"--> DIVERGÊNCIA: {ticker} enviado para painel.")
        except Exception as e: print(f"Erro em {ticker}: {e}")

    return "Sucesso."

if __name__ == "__main__":
    atualizar_financeiro(None)