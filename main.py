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
TOLERANCIA = 0.15 # Tolerância de 15%
TELEFONE_WHATSAPP = "553491503895" 
API_KEY_WHATSAPP = "5116767"

def get_horario_brasilia():
    tz = pytz.timezone('America/Sao_Paulo')
    return datetime.now(tz)

def formatar_valor(val):
    try: return float(val) if val is not None and not pd.isna(val) else 0.0
    except: return 0.0

def enviar_relatorio_whatsapp(sincronizados, alertas):
    # Forçamos o envio mesmo que uma lista esteja vazia
    msg = "📊 *Relatório B3* 📊\n"
    msg += f"✅ Sincronizados: {len(sincronizados)}\n"
    msg += f"🔴 Revisão: {len(alertas)}\n"
    if alertas: msg += "\nAlertas: " + ", ".join(alertas[:5])
    
    url = f"https://api.callmebot.com/whatsapp.php?phone={TELEFONE_WHATSAPP}&text={urllib.parse.quote(msg)}&apikey={API_KEY_WHATSAPP}"
    try: requests.get(url, timeout=10)
    except: pass

def atualizar_financeiro(request):
    print("Iniciando Mestre Ajustado...")
    gc = gspread.service_account(filename='credenciais.json')
    aba = gc.open_by_url('https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk').worksheet("Base de Dados")
    
    ativos_core = ["ITUB4", "BBAS3", "PSSA3", "CMIG4", "VALE3", "SANB11", "SBSP3", "BBSE3", "BBDC3", "PETR4", "BBDC4", "B3SA3"]
    
    # 1. BUSCA OPORTUNIDADES
    try:
        df = pd.read_html(io.StringIO(requests.get("https://www.fundamentus.com.br/resultado.php", headers={'User-Agent': 'Mozilla/5.0'}).text), decimal=',', thousands='.')[0]
        df.columns = df.columns.str.strip()
        df['Papel'] = df['Papel'].str.strip().str.upper()
        # Filtros
        opps = df[(df['Div.Yield'].str.replace('%','').str.replace(',','.').astype(float) > 6) & (df['P/L'].astype(float) < 15)]['Papel'].tolist()
        ativos_finais = list(set(ativos_core + opps))[:15]
    except: ativos_finais = ativos_core

    todas_linhas = aba.get_all_values()
    coluna_a = [linha[0].strip().upper() if len(linha) > 0 else "" for linha in todas_linhas]
    
    agora = get_horario_brasilia().strftime('%H:%M')
    dados_ag1 = json.loads(aba.acell('AG1').value or '{"DADOS":{}}').get("DADOS", {})
    sinc, alts = [], []

    for ticker in ativos_finais:
        if ticker not in coluna_a: continue
        linha = coluna_a.index(ticker) + 1
        
        try:
            acao = yf.Ticker(f"{ticker}.SA").info
            y_p = formatar_valor(acao.get('currentPrice') or acao.get('regularMarketPrice'))
            # Se Y_P for zero, o ativo não existe ou está fora do mercado
            if y_p == 0: continue
            
            # Escreve sempre o preço atual (o mais importante)
            aba.update_cell(linha, 2, y_p)
            # Escreve o horário na coluna AF (32)
            aba.update_cell(linha, 32, f"{agora} OK")
            sinc.append(ticker)
        except Exception as e:
            alts.append(f"{ticker} (Erro)")
            dados_ag1[ticker] = {"linha": linha, "status": "Erro YFinance"}

    # Atualiza AG1 e WhatsApp
    aba.update_acell('AG1', json.dumps({"DADOS": dados_ag1}))
    enviar_relatorio_whatsapp(sinc, alts)
    return "Sucesso."

if __name__ == "__main__":
    atualizar_financeiro(None)