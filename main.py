import gspread
import pandas as pd
import yfinance as yf
import requests
import json
import pytz
from datetime import datetime

# --- CONFIGURAÇÕES E API ---
TOLERANCIA = 0.05
TELEFONE_WHATSAPP = "553491503895" 
API_KEY_WHATSAPP = "5116767"

def get_horario_brasilia():
    tz = pytz.timezone('America/Sao_Paulo')
    return datetime.now(tz)

# Função robusta de conversão: limpa R$, %, pontos e converte para float real
def get_celula_float(valor):
    try:
        if isinstance(valor, (int, float)): return float(valor)
        if not valor: return 0.0
        # Remove símbolos de formatação brasileiros e força ponto decimal
        valor = str(valor).replace('R$', '').replace('%', '').strip()
        if '.' in valor and ',' in valor: valor = valor.replace('.', '').replace(',', '.')
        elif ',' in valor: valor = valor.replace(',', '.')
        return float(valor)
    except: return 0.0

def calcular_discrepancia(v1, v2):
    v1, v2 = abs(float(v1 or 0)), abs(float(v2 or 0))
    if v1 == 0 and v2 == 0: return 0.0
    if v1 == 0 or v2 == 0: return 1.0 
    return abs(v1 - v2) / max(v1, v2)

def obter_data_ordenacao(txt):
    try: return datetime.strptime(str(txt).strip(), '%d/%m/%Y %H:%M:%S')
    except: return datetime.min

def enviar_alerta_whatsapp(ticker, msg):
    url = "https://api.callmebot.com/whatsapp.php"
    params = {"phone": TELEFONE_WHATSAPP, "text": msg, "apikey": API_KEY_WHATSAPP}
    try: requests.get(url, params=params, timeout=5)
    except Exception as e: print(f"Falha ao enviar WhatsApp: {e}")

# --- FUNÇÃO PRINCIPAL ---
def atualizar_financeiro(request):
    print("Executando: Consenso Automático e Auditoria 360...")

    JSON_KEY = 'credenciais.json' 
    SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk' 

    gc = gspread.service_account(filename=JSON_KEY)
    planilha = gc.open_by_url(SPREADSHEET_URL)
    aba_base = planilha.worksheet("Base de Dados")
    aba_metodo = planilha.worksheet("Metodologia Projetiva")

    comando = str(aba_metodo.acell('C3').value).strip().upper()
    if not comando or comando == "CONCLUÍDO": return "Aguardando comando."

    ativos_core = ["ITUB4", "BBAS3", "PSSA3", "CMIG4", "VALE3", "SANB11", "SBSP3", "BBSE3", "BBDC3", "PETR4"]
    fund_data_dict = {}
    ativos_finais = []

    todas_linhas = aba_base.get_all_values()
    coluna_a = [linha[0].strip().upper() if len(linha) > 0 else "" for linha in todas_linhas]

    # 1. RASPAGEM E SELEÇÃO DE ATIVOS
    try:
        url_ops = "https://www.fundamentus.com.br/resultado.php"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'}
        response = requests.get(url_ops, headers=headers, timeout=10)
        df = pd.read_html(response.text, decimal=',', thousands='.')[0]
        df.columns = df.columns.str.strip()
        df['Papel'] = df['Papel'].str.strip().str.upper()

        if 'Div.Yield' in df.columns:
            df['Div.Yield'] = pd.to_numeric(df['Div.Yield'].astype(str).str.replace('%', '', regex=False).str.replace('.', '', regex=False).str.replace(',', '.', regex=False), errors='coerce') / 100
        if 'ROE' in df.columns:
            df['ROE'] = pd.to_numeric(df['ROE'].astype(str).str.replace('%', '', regex=False).str.replace('.', '', regex=False).str.replace(',', '.', regex=False), errors='coerce') / 100
        if 'P/L' in df.columns: df['P/L'] = pd.to_numeric(df['P/L'], errors='coerce')
        if 'P/VP' in df.columns: df['P/VP'] = pd.to_numeric(df['P/VP'], errors='coerce')
            
        fund_data_dict = df.set_index('Papel').to_dict('index')

        if comando == "PESQUISAR":
            oportunidades = df[(df['P/L'] > 0) & (df['ROE'] > 0.10) & (~df['Papel'].isin(ativos_core))].sort_values(by='Liq.2meses', ascending=False).head(5)['Papel'].tolist()
            outros_ativos_Fila = []
            for idx, linha in enumerate(todas_linhas[1:], start=2):
                if len(linha) > 0 and linha[0]:
                    ticker_p = linha[0].strip().upper()
                    if ticker_p != "TICKER" and ticker_p not in ativos_core and ticker_p not in oportunidades:
                        data_af = linha[31].strip() if len(linha) > 31 else ""
                        outros_ativos_Fila.append({"ticker": ticker_p, "data": data_af})
            outros_ativos_Fila.sort(key=lambda x: obter_data_ordenacao(x["data"]))
            ativos_rotativos = [item["ticker"] for item in outros_ativos_Fila[:5]]
            ativos_finais = list(set(ativos_core + oportunidades + ativos_rotativos))
        else:
            ativos_finais = [comando]
    except Exception as e: print(f"Erro na raspagem: {e}")

    # 2. MOTOR DE ATUALIZAÇÃO
    lote_updates = []
    dados_json_global = {}
    agora_str = get_horario_brasilia().strftime('%d/%m/%Y %H:%M:%S')

    for ticker in ativos_finais:
        try:
            linha_busca = coluna_a.index(ticker) + 1 if ticker in coluna_a else len(coluna_a) + 1
            if linha_busca <= len(todas_linhas):
                linha_atual = todas_linhas[linha_busca - 1]
                atual_preco = get_celula_float(linha_atual[1]) if len(linha_atual) > 1 else 0.0
                atual_dy = get_celula_float(linha_atual[2]) / 100 if len(linha_atual) > 2 else 0.0
                atual_pl = get_celula_float(linha_atual[4]) if len(linha_atual) > 4 else 0.0
                atual_pvp = get_celula_float(linha_atual[5]) if len(linha_atual) > 5 else 0.0
            else:
                atual_preco, atual_dy, atual_pl, atual_pvp = 0.0, 0.0, 0.0, 0.0

            # DADOS YAHOO E FUNDAMENTUS
            acao = yf.Ticker(f"{ticker}.SA")
            info = acao.info
            y_preco = info.get('currentPrice', info.get('regularMarketPrice', 0)) or 0
            y_pl = info.get('trailingPE', 0) or 0
            y_pvp = info.get('priceToBook', 0) or 0
            y_dy = info.get('dividendYield', 0) or 0
            
            f_pl, f_pvp, f_dy, f_preco = 0.0, 0.0, 0.0, 0.0
            if ticker in fund_data_dict:
                d = fund_data_dict[ticker]
                f_pl, f_pvp = d.get('P/L', 0), d.get('P/VP', 0)
                f_dy, f_preco = d.get('Div.Yield', 0), d.get('Cotação', 0)
            if y_pvp < 0.5: y_pvp = f_pvp 

            # AUDITORIA
            lista_disc = []
            if calcular_discrepancia(y_pl, f_pl) > TOLERANCIA: lista_disc.append("P/L")
            if calcular_discrepancia(y_pvp, f_pvp) > TOLERANCIA: lista_disc.append("P/VP")
            if calcular_discrepancia(y_dy, f_dy) > TOLERANCIA: lista_disc.append("DY")

            if len(lista_disc) == 0 and atual_preco > 0:
                lote_updates.append({'range': f'B{linha_busca}', 'values': [[y_preco], [f_dy], [f_pl], [f_pvp]]}) # Simplify
                enviar_alerta_whatsapp(ticker, f"✅ SUCESSO: {ticker} atualizado.")
            else:
                dados_json_global[ticker] = {
                    "linha": linha_busca,
                    "status": f"🔴 Discrepância: {', '.join(lista_disc)}" if lista_disc else "Revisão Necessária",
                    "atual": {"preco": atual_preco, "pl": atual_pl, "pvp": atual_pvp, "dy": atual_dy},
                    "y": {"preco": y_preco, "pl": y_pl, "pvp": y_pvp, "dy": y_dy},
                    "f": {"preco": f_preco, "pl": f_pl, "pvp": f_pvp, "dy": f_dy}
                }
                enviar_alerta_whatsapp(ticker, f"🔴 ATENÇÃO: {ticker} requer revisão.")

        except Exception as e: print(f"Erro em {ticker}: {e}")

    if dados_json_global: aba_base.update_acell('AG1', json.dumps({"DADOS": dados_json_global}))
    else: aba_base.update_acell('AG1', '')
    return "Sucesso."