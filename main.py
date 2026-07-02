import gspread
import pandas as pd
import yfinance as yf
import requests
import io
import urllib.parse

# --- CONFIGURAÇÕES ---
TELEFONE_WHATSAPP = "553491503895" 
API_KEY_WHATSAPP = "5116767"

def enviar_whatsapp(mensagem):
    url = f"https://api.callmebot.com/whatsapp.php?phone={TELEFONE_WHATSAPP}&text={urllib.parse.quote(mensagem)}&apikey={API_KEY_WHATSAPP}"
    try: requests.get(url, timeout=5)
    except: pass

def atualizar_financeiro(request):
    print("Iniciando Mestre Simplificado...")
    # Conexão
    gc = gspread.service_account(filename='credenciais.json')
    planilha = gc.open_by_url('https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk')
    aba = planilha.worksheet("Base de Dados")

    # 1. PEGAR LISTA DA PLANILHA
    ativos_da_planilha = [linha[0] for linha in aba.get_all_values() if linha and linha[0]]
    
    # 2. BUSCAR DADOS DO FUNDAMENTUS
    try:
        url = "https://www.fundamentus.com.br/resultado.php"
        df = pd.read_html(io.StringIO(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).text), decimal=',', thousands='.')[0]
        df['Papel'] = df['Papel'].str.strip().str.upper()
        fund_map = df.set_index('Papel').to_dict('index')
    except: fund_map = {}

    sincronizados = []

    # 3. PROCESSAR CADA ATIVO
    for i, ticker in enumerate(ativos_da_planilha):
        if i == 0: continue # Pula cabeçalho
        if len(ticker) < 4: continue
        
        try:
            # Busca Yahoo
            ticker_yf = yf.Ticker(f"{ticker}.SA").info
            preco = ticker_yf.get('currentPrice') or ticker_yf.get('regularMarketPrice') or 0
            
            # Dados Fundamentus
            f = fund_map.get(ticker, {})
            pl = f.get('P/L', 0)
            pvp = f.get('P/VP', 0)
            dy = f.get('Div.Yield', 0)
            if isinstance(dy, str): dy = float(dy.replace('%', '').replace(',', '.')) / 100

            # ESCREVER DIRETO (Sem auditoria, sem complicações)
            linha_idx = i + 1
            aba.update_cell(linha_idx, 2, float(preco))
            aba.update_cell(linha_idx, 3, float(dy))
            aba.update_cell(linha_idx, 5, float(pl))
            aba.update_cell(linha_idx, 6, float(pvp))
            
            sincronizados.append(ticker)
        except Exception as e:
            print(f"Erro em {ticker}: {e}")

    # 4. NOTIFICAR
    enviar_whatsapp(f"✅ Atualização concluída com sucesso! Total: {len(sincronizados)} ativos.")
    return "Sucesso."

if __name__ == "__main__":
    atualizar_financeiro(None)