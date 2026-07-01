import gspread
import pandas as pd
import yfinance as yf
import requests
import json
from datetime import datetime
import pytz # Adicionado para corrigir o fuso horário

# --- CONFIGURAÇÃO DE FUSO HORÁRIO ---
def get_horario_brasilia():
    tz = pytz.timezone('America/Sao_Paulo')
    return datetime.now(tz)

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

def atualizar_financeiro(request):
    JSON_KEY = 'credenciais.json' 
    SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk' 

    gc = gspread.service_account(filename=JSON_KEY)
    planilha = gc.open_by_url(SPREADSHEET_URL)
    aba_base = planilha.worksheet("Base de Dados")
    aba_metodo = planilha.worksheet("Metodologia Projetiva")

    comando = str(aba_metodo.acell('C3').value).strip().upper()
    if not comando or comando == "CONCLUÍDO": return "Aguardando comando."

    # AÇÕES FIXAS (CORE)
    ativos_core = ["ITUB4", "BBAS3", "PSSA3", "CMIG4", "VALE3", "SANB11", "SBSP3", "BBSE3", "BBDC3", "PETR4"]
    
    # 1. RASPAGEM E SELEÇÃO INTELIGENTE
    ativos_finais = []
    fund_data_dict = {}

    if comando == "PESQUISAR":
        try:
            url_ops = "https://www.fundamentus.com.br/resultado.php"
            df = pd.read_html(requests.get(url_ops, headers={'User-Agent': 'Mozilla/5.0'}).text, decimal=',', thousands='.')[0]
            df.columns = df.columns.str.strip()
            df['Papel'] = df['Papel'].str.strip().str.upper()
            fund_data_dict = df.set_index('Papel').to_dict('index')

            # Oportunidades (excluindo o que já está no CORE)
            df['P/L'] = pd.to_numeric(df['P/L'].astype(str).str.replace('.', '').str.replace(',', '.'), errors='coerce')
            df['ROE'] = pd.to_numeric(df['ROE'].astype(str).str.replace('%', '').str.replace('.', '').str.replace(',', '.'), errors='coerce') / 100
            
            oportunidades = df[(df['P/L'] > 0) & (df['ROE'] > 0.10) & (~df['Papel'].isin(ativos_core))].sort_values(by='Liq.2meses', ascending=False).head(5)['Papel'].tolist()
            ativos_finais = list(set(ativos_core + oportunidades))
        except Exception as e: print(f"Erro: {e}")
    else:
        ativos_finais = [comando]

    # 2. MOTOR DE ATUALIZAÇÃO E AUDITORIA
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

            # TRAVA DE DATA (Anti-spam)
            valor_af = aba_base.cell(linha_busca, 32).value
            if valor_af and comando != "PESQUISAR":
                try:
                    if datetime.strptime(str(valor_af).split()[0], '%d/%m/%Y').date() == data_hoje: continue
                except: pass

            # BUSCA E AUDITORIA
            acao = yf.Ticker(f"{ticker}.SA")
            info = acao.info
            y_preco = info.get('currentPrice', info.get('regularMarketPrice', 0)) or 0
            f_pl, f_pvp, f_dy = 0.0, 0.0, 0.0
            if ticker in fund_data_dict:
                d = fund_data_dict[ticker]
                f_pl = converter_para_float(d.get('P/L', 0))
                f_pvp = converter_para_float(d.get('P/VP', 0))
                f_dy = converter_para_float(d.get('Div.Yield', 0))
            
            is_seguro = calcular_discrepancia(info.get('trailingPE', 0), f_pl) <= 0.05

            # ATUALIZAÇÃO FORÇADA (DATA E VALORES)
            lote_updates.append({'range': f'AF{linha_busca}', 'values': [[agora_str]]})
            lote_updates.append({'range': f'B{linha_busca}', 'values': [[converter_para_float(y_preco)]]})
            lote_updates.append({'range': f'C{linha_busca}', 'values': [[f_dy]]})
            lote_updates.append({'range': f'E{linha_busca}', 'values': [[f_pl]]})
            lote_updates.append({'range': f'F{linha_busca}', 'values': [[f_pvp]]})
            
            status_msg = "🟢 Sincronizado" if is_seguro else "🔴 Discrepância"
            lote_updates.append({'range': f'AH{linha_busca}', 'values': [[f"[{agora_str}] {status_msg}"]]})
            
            if not is_seguro:
                dados_json_global[ticker] = {"status": "DISCREPÂNCIA", "info": "Verifique fontes"}

        except Exception as e: print(f"Erro em {ticker}: {e}")

    if lote_updates: aba_base.batch_update(lote_updates)
    aba_base.update_acell('AG1', json.dumps({"DADOS": dados_json_global}))
    return "Sucesso."