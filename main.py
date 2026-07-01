import gspread
import pandas as pd
import yfinance as yf
import requests
import json
import re
import pytz
from datetime import datetime

# --- CONFIGURAÇÕES E API ---
TOLERANCIA = 0.05
TELEFONE_WHATSAPP = "SEU_NUMERO_AQUI" 
API_KEY_WHATSAPP = "SUA_API_KEY_AQUI"

def get_horario_brasilia():
    tz = pytz.timezone('America/Sao_Paulo')
    return datetime.now(tz)

def fmt_moeda_sheet(valor):
    try:
        if valor is None or valor == 0: return "0,00"
        return f"{float(valor):.2f}".replace('.', ',')
    except: return "0,00"

def converter_para_float(valor):
    try:
        if isinstance(valor, str): valor = valor.replace(',', '.')
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
    url = f"https://api.callmebot.com/whatsapp.php?phone={TELEFONE_WHATSAPP}&text={msg}&apikey={API_KEY_WHATSAPP}"
    try: requests.get(url, timeout=5)
    except: print(f"Falha ao enviar WhatsApp para {ticker}")

# --- FUNÇÃO PRINCIPAL ---
def atualizar_financeiro(request):
    print("Iniciando execução oficial (Versão Integral)...")
    
    JSON_KEY = 'credenciais.json' 
    SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk' 

    gc = gspread.service_account(filename=JSON_KEY)
    planilha = gc.open_by_url(SPREADSHEET_URL)
    aba_base = planilha.worksheet("Base de Dados")
    aba_metodo = planilha.worksheet("Metodologia Projetiva")
    aba_disc = planilha.worksheet("Discrepâncias")

    comando = str(aba_metodo.acell('C3').value).strip().upper()
    if not comando or comando == "CONCLUÍDO": return "Aguardando comando."

    ativos_core = ["ITUB4", "BBAS3", "PSSA3", "CMIG4", "VALE3", "SANB11", "SBSP3", "BBSE3", "BBDC3", "PETR4"]
    fund_data_dict = {}
    ativos_finais = []

    # 1. RASPAGEM E SELEÇÃO DE ATIVOS (A lógica que você já validou)
    try:
        url_ops = "https://www.fundamentus.com.br/resultado.php"
        df = pd.read_html(requests.get(url_ops, headers={'User-Agent': 'Mozilla/5.0'}).text, decimal=',', thousands='.')[0]
        df.columns = df.columns.str.strip()
        df['Papel'] = df['Papel'].str.strip().str.upper()
        
        # Limpeza para cálculo
        df['P/L'] = pd.to_numeric(df['P/L'].astype(str).str.replace('.', '').str.replace(',', '.'), errors='coerce')
        df['ROE'] = pd.to_numeric(df['ROE'].astype(str).str.replace('%', '').str.replace('.', '').str.replace(',', '.'), errors='coerce') / 100
        fund_data_dict = df.set_index('Papel').to_dict('index')

        if comando == "PESQUISAR":
            oportunidades = df[(df['P/L'] > 0) & (df['ROE'] > 0.10) & (~df['Papel'].isin(ativos_core))].sort_values(by='Liq.2meses', ascending=False).head(5)['Papel'].tolist()
            
            # Rotatividade de Ativos
            todas_linhas = aba_base.get_all_values()
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

    # 2. MOTOR DE ATUALIZAÇÃO (Toda a lógica preservada)
    lote_updates = []
    dados_json_global = {}
    agora_str = get_horario_brasilia().strftime('%d/%m/%Y %H:%M:%S')
    data_hoje = get_horario_brasilia().date()
    coluna_a = aba_base.col_values(1)

    for ticker in ativos_finais:
        try:
            linha_busca = coluna_a.index(ticker) + 1 if ticker in coluna_a else len(coluna_a) + 1
            if ticker not in coluna_a:
                aba_base.update_cell(linha_busca, 1, ticker)
                coluna_a.append(ticker)

            # Trava Anti-Spam
            valor_af = aba_base.cell(linha_busca, 32).value
            if valor_af and comando != "PESQUISAR":
                try:
                    if datetime.strptime(str(valor_af).split()[0], '%d/%m/%Y').date() == data_hoje: continue
                except: pass

            # BUSCA DADOS
            acao = yf.Ticker(f"{ticker}.SA")
            info = acao.info
            y_preco = info.get('currentPrice', info.get('regularMarketPrice', 0)) or 0
            y_pl = info.get('trailingPE', 0) or 0
            y_pvp = info.get('priceToBook', 0) or 0
            y_dy = info.get('dividendYield', 0) or 0
            y_vmkt = info.get('marketCap', 0) or 0
            
            f_pl, f_pvp, f_dy = 0.0, 0.0, 0.0
            if ticker in fund_data_dict:
                d = fund_data_dict[ticker]
                f_pl = converter_para_float(d.get('P/L', 0))
                f_pvp = converter_para_float(d.get('P/VP', 0))
                f_dy = converter_para_float(d.get('Div.Yield', 0)) / 100

            # AUDITORIA 360º (Preço, PL, PVP, DY, Valor Mercado)
            lista_disc = []
            if calcular_discrepancia(y_pl, f_pl) > TOLERANCIA: lista_disc.append("P/L")
            if calcular_discrepancia(y_pvp, f_pvp) > TOLERANCIA: lista_disc.append("P/VP")
            if calcular_discrepancia(y_dy, f_dy) > TOLERANCIA: lista_disc.append("DY")
            
            is_seguro = len(lista_disc) == 0
            status_msg = "🟢 Sincronizado" if is_seguro else f"🔴 Discrepância: {', '.join(lista_disc)}"
            
            # ATUALIZAÇÃO
            lote_updates.append({'range': f'AF{linha_busca}', 'values': [[agora_str]]})
            lote_updates.append({'range': f'B{linha_busca}', 'values': [[converter_para_float(y_preco)]]})
            lote_updates.append({'range': f'C{linha_busca}', 'values': [[f_dy]]})
            lote_updates.append({'range': f'E{linha_busca}', 'values': [[f_pl]]})
            lote_updates.append({'range': f'F{linha_busca}', 'values': [[f_pvp]]})
            lote_updates.append({'range': f'AE{linha_busca}', 'values': [[y_vmkt]]})
            lote_updates.append({'range': f'AH{linha_busca}', 'values': [[f"[{agora_str}] {status_msg}"]]})
            
            # NOTIFICAÇÕES
            if not is_seguro:
                aba_disc.append_row([agora_str, ticker, status_msg, f"Y:{y_pl}|F:{f_pl}"])
                enviar_alerta_whatsapp(ticker, f"🔴 ATENÇÃO: {status_msg}. Ativo: {ticker}.")
            
            dados_json_global[ticker] = {"linha": linha_busca, "valor_atual": y_preco, "status": status_msg}

        except Exception as e: print(f"Erro em {ticker}: {e}")

    if lote_updates: aba_base.batch_update(lote_updates)
    aba_base.update_acell('AG1', json.dumps({"DADOS": dados_json_global}))
    return "Sucesso."

if __name__ == "__main__":
    atualizar_financeiro(None)
