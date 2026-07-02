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

def fmt_moeda_sheet(valor):
    try:
        if valor is None or valor == 0: return "0,00"
        return f"{float(valor):.2f}".replace('.', ',')
    except: return "0,00"

def get_celula_float(valor):
    try:
        if isinstance(valor, (int, float)): return float(valor)
        if not valor: return 0.0
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
    print("Iniciando execução oficial (Versão Restaurada Integral)...")

    JSON_KEY = 'credenciais.json' 
    SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk' 

    gc = gspread.service_account(filename=JSON_KEY)
    planilha = gc.open_by_url(SPREADSHEET_URL)
    aba_base = planilha.worksheet("Base de Dados")
    aba_metodo = planilha.worksheet("Metodologia Projetiva")
    aba_disc = planilha.worksheet("Discrepâncias")

    comando = str(aba_metodo.acell('C3').value).strip().upper()
    if not comando or comando == "CONCLUÍDO": return "Aguardando comando."

    ativos_core = ["ITUB4", "BBAS3", "PSSA3", "CMIG4", "VALE3", "SANB11", "SBSP3", "BBSE3", "BBDC3", "PETR4", "BBDC3", "BBDC4", "B3SA3"]
    fund_data_dict = {}
    ativos_finais = []

    # Leitura da planilha para processamento
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

        # Limpeza robusta
        for col in ['Div.Yield', 'ROE']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col].astype(str).str.replace('%', '', regex=False).str.replace('.', '', regex=False).str.replace(',', '.', regex=False), errors='coerce') / 100
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

    # 2. MOTOR DE ATUALIZAÇÃO E AUDITORIA
    lote_updates = []
    
    # Carregar erros pendentes no AG1 para não apagar o que já existe
    try:
        dados_json_global = json.loads(aba_base.acell('AG1').value).get("DADOS", {})
    except:
        dados_json_global = {}

    agora_str = get_horario_brasilia().strftime('%d/%m/%Y %H:%M:%S')
    data_hoje = get_horario_brasilia().date()

    for ticker in ativos_finais:
        try:
            linha_busca = coluna_a.index(ticker) + 1 if ticker in coluna_a else len(coluna_a) + 1
            if linha_busca <= len(todas_linhas):
                linha_atual = todas_linhas[linha_busca - 1]
                while len(linha_atual) < 32: linha_atual.append("")
                atual_preco = get_celula_float(linha_atual[1])
                atual_dy = get_celula_float(linha_atual[2])
                atual_pl = get_celula_float(linha_atual[4])
                atual_pvp = get_celula_float(linha_atual[5])
            else:
                atual_preco, atual_dy, atual_pl, atual_pvp = 0.0, 0.0, 0.0, 0.0

            # Trava Anti-Spam
            valor_af = linha_atual[31] if linha_busca <= len(todas_linhas) else ""
            if valor_af and comando == "PESQUISAR":
                if datetime.strptime(str(valor_af).split()[0], '%d/%m/%Y').date() == data_hoje: continue

            # DADOS YAHOO E FUNDAMENTUS
            acao = yf.Ticker(f"{ticker}.SA")
            info = acao.info
            y_preco = info.get('currentPrice', info.get('regularMarketPrice', 0)) or 0
            y_pl = info.get('trailingPE', 0) or 0
            y_pvp = info.get('priceToBook', 0) or 0
            y_dy = info.get('dividendYield', 0) or 0
            y_vmkt = info.get('marketCap', 0) or 0

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
                lote_updates.append({'range': f'AF{linha_busca}', 'values': [[agora_str]]})
                lote_updates.append({'range': f'B{linha_busca}', 'values': [[y_preco]]})
                lote_updates.append({'range': f'C{linha_busca}', 'values': [[f_dy]]})
                lote_updates.append({'range': f'E{linha_busca}', 'values': [[f_pl]]})
                lote_updates.append({'range': f'F{linha_busca}', 'values': [[f_pvp]]})
                lote_updates.append({'range': f'AH{linha_busca}', 'values': [[f"[{agora_str}] 🟢 Sincronizado"]]})
                enviar_alerta_whatsapp(ticker, f"✅ {ticker} Sincronizado automaticamente.")
            else:
                aba_disc.append_row([agora_str, ticker, f"Disc: {', '.join(lista_disc)}", f"Y:{y_pl}|F:{f_pl}"])
                enviar_alerta_whatsapp(ticker, f"🔴 {ticker} Requer revisão no Painel.")
                dados_json_global[ticker] = {
                    "linha": linha_busca,
                    "status": f"🔴 Discrepância: {', '.join(lista_disc)}",
                    "atual": {"preco": atual_preco, "pl": atual_pl, "pvp": atual_pvp, "dy": atual_dy},
                    "y": {"preco": y_preco, "pl": y_pl, "pvp": y_pvp, "dy": y_dy},
                    "f": {"preco": f_preco, "pl": f_pl, "pvp": f_pvp, "dy": f_dy}
                }

        except Exception as e: print(f"Erro em {ticker}: {e}")

    if lote_updates: aba_base.batch_update(lote_updates)
    aba_base.update_acell('AG1', json.dumps({"DADOS": dados_json_global}))
    return "Sucesso."

if __name__ == "__main__":
    atualizar_financeiro(None)