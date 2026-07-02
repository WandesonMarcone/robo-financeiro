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
    print("Iniciando execução oficial (Versão Cirúrgica)...")

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

    # Lê todas as linhas de uma vez para não gastar API do Google
    todas_linhas = aba_base.get_all_values()
    coluna_a = [linha[0].strip().upper() if len(linha) > 0 else "" for linha in todas_linhas]

    # 1. RASPAGEM E SELEÇÃO DE ATIVOS
    try:
        url_ops = "https://www.fundamentus.com.br/resultado.php"
        df = pd.read_html(requests.get(url_ops, headers={'User-Agent': 'Mozilla/5.0'}).text, decimal=',', thousands='.')[0]
        df.columns = df.columns.str.strip()
        df['Papel'] = df['Papel'].str.strip().str.upper()

        # Limpeza cirúrgica: Só arranca % de quem é string
        if 'Div.Yield' in df.columns:
            df['Div.Yield'] = df['Div.Yield'].astype(str).str.replace('%', '', regex=False).str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
            df['Div.Yield'] = pd.to_numeric(df['Div.Yield'], errors='coerce') / 100
        if 'ROE' in df.columns:
            df['ROE'] = df['ROE'].astype(str).str.replace('%', '', regex=False).str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
            df['ROE'] = pd.to_numeric(df['ROE'], errors='coerce') / 100
        
        # P/L e P/VP já são floats nativos, não fazemos manipulação de string neles
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
    dados_json_global = {}
    agora_str = get_horario_brasilia().strftime('%d/%m/%Y %H:%M:%S')
    data_hoje = get_horario_brasilia().date()

    for ticker in ativos_finais:
        try:
            linha_busca = coluna_a.index(ticker) + 1 if ticker in coluna_a else len(coluna_a) + 1
            if ticker not in coluna_a:
                aba_base.update_cell(linha_busca, 1, ticker)
                coluna_a.append(ticker)

            # Capta os dados que JÁ ESTÃO na planilha para mostrar no painel
            if linha_busca <= len(todas_linhas):
                linha_atual = todas_linhas[linha_busca - 1]
                while len(linha_atual) < 6: linha_atual.append("")
                atual_preco = converter_para_float(linha_atual[1])
                atual_dy = converter_para_float(str(linha_atual[2]).replace('%','')) / 100 if '%' in str(linha_atual[2]) else converter_para_float(linha_atual[2])
                atual_pl = converter_para_float(linha_atual[4])
                atual_pvp = converter_para_float(linha_atual[5])
            else:
                atual_preco, atual_dy, atual_pl, atual_pvp = 0.0, 0.0, 0.0, 0.0

            # Trava Anti-Spam
            valor_af = linha_atual[31] if linha_busca <= len(todas_linhas) and len(linha_atual) > 31 else ""
            if valor_af and comando != "PESQUISAR":
                try:
                    if datetime.strptime(str(valor_af).split()[0], '%d/%m/%Y').date() == data_hoje: continue
                except: pass

            # BUSCA DADOS YAHOO
            acao = yf.Ticker(f"{ticker}.SA")
            info = acao.info
            y_preco = info.get('currentPrice', info.get('regularMarketPrice', 0)) or 0
            y_pl = info.get('trailingPE', 0) or 0
            y_pvp = info.get('priceToBook', 0) or 0
            y_dy = info.get('dividendYield', 0) or 0
            y_vmkt = info.get('marketCap', 0) or 0

            # BUSCA DADOS FUNDAMENTUS
            f_pl, f_pvp, f_dy, f_preco = 0.0, 0.0, 0.0, 0.0
            if ticker in fund_data_dict:
                d = fund_data_dict[ticker]
                f_pl = converter_para_float(d.get('P/L', 0))
                f_pvp = converter_para_float(d.get('P/VP', 0))
                f_dy = converter_para_float(d.get('Div.Yield', 0))
                f_preco = converter_para_float(d.get('Cotação', 0))

            # AUDITORIA
            lista_disc = []
            if calcular_discrepancia(y_pl, f_pl) > TOLERANCIA: lista_disc.append("P/L")
            if calcular_discrepancia(y_pvp, f_pvp) > TOLERANCIA: lista_disc.append("P/VP")
            if calcular_discrepancia(y_dy, f_dy) > TOLERANCIA: lista_disc.append("DY")

            is_seguro = len(lista_disc) == 0
            status_msg = "🟢 Sincronizado" if is_seguro else f"🔴 Discrepância: {', '.join(lista_disc)}"

            # Notificações e Automação
            if not is_seguro or (atual_preco == 0 and atual_pl == 0):
                # Se for discrepante ou for uma ação vazia (zerada), manda pro painel e pro WhatsApp
                aba_disc.append_row([agora_str, ticker, status_msg, f"Y:{y_pl}|F:{f_pl}"])
                enviar_alerta_whatsapp(ticker, f"🔴 ATENÇÃO: Revisão Necessária. Ativo: {ticker}.")
            else:
                # Se for 100% igual e tiver dados, injeta sozinho
                lote_updates.append({'range': f'AF{linha_busca}', 'values': [[agora_str]]})
                lote_updates.append({'range': f'B{linha_busca}', 'values': [[float(y_preco)]]})
                lote_updates.append({'range': f'C{linha_busca}', 'values': [[float(f_dy)]]})
                lote_updates.append({'range': f'E{linha_busca}', 'values': [[float(f_pl)]]})
                lote_updates.append({'range': f'F{linha_busca}', 'values': [[float(f_pvp)]]})
                lote_updates.append({'range': f'AE{linha_busca}', 'values': [[y_vmkt]]})
                lote_updates.append({'range': f'AH{linha_busca}', 'values': [[f"[{agora_str}] {status_msg}"]]})

            # Monta JSON do Dashboard para TUDO, assim você decide métrica por métrica
            dados_json_global[ticker] = {
                "linha": linha_busca,
                "status": status_msg,
                "atual": {"preco": float(atual_preco), "pl": float(atual_pl), "pvp": float(atual_pvp), "dy": float(atual_dy)},
                "y": {"preco": float(y_preco), "pl": float(round(y_pl, 2)), "pvp": float(round(y_pvp, 2)), "dy": float(round(y_dy, 4))},
                "f": {"preco": float(f_preco), "pl": float(round(f_pl, 2)), "pvp": float(round(f_pvp, 2)), "dy": float(round(f_dy, 4))}
            }

        except Exception as e: print(f"Erro em {ticker}: {e}")

    if lote_updates: aba_base.batch_update(lote_updates)
    aba_base.update_acell('AG1', json.dumps({"DADOS": dados_json_global}))
    return "Sucesso."

if __name__ == "__main__":
    atualizar_financeiro(None)