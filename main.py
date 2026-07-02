import gspread
import pandas as pd
import yfinance as yf
import requests
import json
import pytz
import urllib.parse
from datetime import datetime

# --- CONFIGURAÇÕES ---
TOLERANCIA = 0.05
TELEFONE_WHATSAPP = "553491503895" 
API_KEY_WHATSAPP = "5116767"

def get_horario_brasilia():
    tz = pytz.timezone('America/Sao_Paulo')
    return datetime.now(tz)

def calcular_discrepancia(v1, v2):
    v1, v2 = abs(float(v1 or 0)), abs(float(v2 or 0))
    if v1 == 0 and v2 == 0: return 0.0
    if v1 == 0 or v2 == 0: return 1.0 
    return abs(v1 - v2) / max(v1, v2)

def enviar_relatorio_whatsapp(sincronizados, alertas):
    msg = "📊 *Relatório Diário B3* 📊\n\n"
    if sincronizados: msg += "✅ *Automático (Consenso):*\n" + ", ".join(sincronizados) + "\n\n"
    if alertas:
        msg += "🔴 *Revisão no Painel (AG1):*\n"
        for alerta in alertas: msg += f"• {alerta}\n"
    url = f"https://api.callmebot.com/whatsapp.php?phone={TELEFONE_WHATSAPP}&text={urllib.parse.quote(msg)}&apikey={API_KEY_WHATSAPP}"
    try: requests.get(url, timeout=5)
    except Exception as e: print(f"Erro WhatsApp: {e}")

# --- FUNÇÃO PRINCIPAL ---
def atualizar_financeiro(request):
    print("--- INÍCIO DO DIAGNÓSTICO ---")
    JSON_KEY = 'credenciais.json' 
    SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk' 
    
    try:
        gc = gspread.service_account(filename=JSON_KEY)
        planilha = gc.open_by_url(SPREADSHEET_URL)
        aba_base = planilha.worksheet("Base de Dados")
        aba_disc = planilha.worksheet("Discrepâncias")
        print("Sucesso: Planilha conectada.")
    except Exception as e:
        print(f"ERRO: Não conectou na planilha: {e}")
        return

    # 1. CARREGAR ATIVOS
    ativos_core = ["ITUB4", "BBAS3", "PSSA3", "CMIG4", "VALE3", "SANB11", "SBSP3", "BBSE3", "BBDC3", "PETR4", "BBDC4", "B3SA3"]
    ativos_finais = ativos_core[:]
    
    try:
        df = pd.read_html("https://www.fundamentus.com.br/resultado.php", headers={'User-Agent': 'Mozilla/5.0'}, decimal=',', thousands='.')[0]
        df.columns = df.columns.str.strip()
        df['Papel'] = df['Papel'].str.strip().str.upper()
        df['Div.Yield'] = pd.to_numeric(df['Div.Yield'].astype(str).str.replace('%','').str.replace('.','').str.replace(',','.'), errors='coerce') / 100
        df['P/L'] = pd.to_numeric(df['P/L'], errors='coerce')
        df['P/VP'] = pd.to_numeric(df['P/VP'], errors='coerce')
        oportunidades = df[(df['Div.Yield'] > 0.06) & (df['P/L'] < 15) & (df['P/VP'] < 2)]['Papel'].tolist()
        for op in oportunidades:
            if op not in ativos_finais and len(ativos_finais) < 15: ativos_finais.append(op)
        fund_data_dict = df.set_index('Papel').to_dict('index')
        print(f"Sucesso: Busca de oportunidades feita. Total ativos: {len(ativos_finais)}")
    except Exception as e: print(f"Erro na busca: {e}")

    # 2. PROCESSAMENTO
    todas_linhas = aba_base.get_all_values()
    coluna_a = [linha[0].strip().upper() if len(linha) > 0 else "" for linha in todas_linhas]
    
    try: dados_json_global = json.loads(aba_base.acell('AG1').value or '{"DADOS":{}}').get("DADOS", {})
    except: dados_json_global = {}

    agora_str = get_horario_brasilia().strftime('%d/%m/%Y %H:%M:%S')
    relatorio_sinc, relatorio_alertas = [], []

    for ticker in ativos_finais:
        print(f"DEBUG: Processando {ticker}...")
        try:
            if ticker not in coluna_a:
                print(f"DEBUG: {ticker} NÃO está na coluna A. Pulando.")
                continue
            
            linha_busca = coluna_a.index(ticker) + 1
            print(f"DEBUG: {ticker} encontrado na linha {linha_busca}.")
            
            # Buscas
            acao = yf.Ticker(f"{ticker}.SA")
            info = acao.info
            y_preco = info.get('currentPrice', info.get('regularMarketPrice', 0)) or 0
            y_pl = info.get('trailingPE', 0) or 0
            y_pvp = info.get('priceToBook', 0) or 0
            y_dy = info.get('dividendYield', 0) or 0
            if y_dy > 1: y_dy /= 100 

            f_pl, f_pvp, f_dy = 0.0, 0.0, 0.0
            if ticker in fund_data_dict:
                d = fund_data_dict[ticker]
                f_pl, f_pvp, f_dy = d.get('P/L', 0), d.get('P/VP', 0), d.get('Div.Yield', 0)
            
            if y_pvp < 0.5: y_pvp = f_pvp 

            print(f"DEBUG: Valores obtidos para {ticker} -> Y: {y_preco} / F: {f_pl}")

            disc_pl = calcular_discrepancia(y_pl, f_pl) > TOLERANCIA
            disc_pvp = calcular_discrepancia(y_pvp, f_pvp) > TOLERANCIA
            disc_dy = calcular_discrepancia(y_dy, f_dy) > TOLERANCIA

            if not disc_pl and not disc_pvp and not disc_dy:
                media_preco = float(y_preco)
                media_pl = float(round((y_pl + f_pl)/2, 2) if f_pl > 0 else y_pl)
                media_pvp = float(round((y_pvp + f_pvp)/2, 2) if f_pvp > 0 else y_pvp)
                media_dy = float(round((y_dy + f_dy)/2, 4) if f_dy > 0 else y_dy)
                
                print(f"DEBUG: Consenso atingido para {ticker}. Escrevendo na linha {linha_busca}...")
                aba_base.update_cell(linha_busca, 2, media_preco)
                aba_base.update_cell(linha_busca, 3, media_dy)
                aba_base.update_cell(linha_busca, 5, media_pl)
                aba_base.update_cell(linha_busca, 6, media_pvp)
                aba_base.update_cell(linha_busca, 34, f"[{agora_str}] 🟢 Média")
                print(f"DEBUG: Escrita finalizada para {ticker}.")
                
                relatorio_sinc.append(ticker)
                if ticker in dados_json_global: del dados_json_global[ticker]
            else:
                print(f"DEBUG: Discrepância detectada para {ticker}.")
                relatorio_alertas.append(f"{ticker} (Disc: {'PL ' if disc_pl else ''}{'PVP ' if disc_pvp else ''}{'DY ' if disc_dy else ''})")
                aba_disc.append_row([agora_str, ticker, "Divergência", f"Y:{y_pl}|F:{f_pl}"])
                dados_json_global[ticker] = {"linha": linha_busca, "status": "🔴 Revisão"}
        except Exception as e: print(f"ERRO CRÍTICO em {ticker}: {e}")

    aba_base.update_acell('AG1', json.dumps({"DADOS": dados_json_global}))
    enviar_relatorio_whatsapp(relatorio_sinc, relatorio_alertas)
    print("--- FIM DO DIAGNÓSTICO ---")
    return "Sucesso."

if __name__ == "__main__":
    atualizar_financeiro(None)