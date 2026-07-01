import gspread
import pandas as pd
import yfinance as yf
import requests
import json
from datetime import datetime

# --- FUNÇÃO AUXILIAR ---
def converter_para_float(valor):
    try:
        if isinstance(valor, str):
            valor = valor.replace(',', '.')
        return float(valor)
    except:
        return 0.0

# --- MAIN ---
def atualizar_financeiro(request):
    print("Iniciando execução oficial...")
    JSON_KEY = 'credenciais.json' 
    SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk' 

    gc = gspread.service_account(filename=JSON_KEY)
    planilha = gc.open_by_url(SPREADSHEET_URL)
    aba_base = planilha.worksheet("Base de Dados")
    aba_metodo = planilha.worksheet("Metodologia Projetiva")

    comando = str(aba_metodo.acell('C3').value).strip().upper()
    if not comando or comando == "CONCLUÍDO": return "Aguardando comando."

    # 1. Carrega dados do Fundamentus
    fund_data_dict = {}
    try:
        url_ops = "https://www.fundamentus.com.br/resultado.php"
        # O Pandas já faz a conversão perfeita da matemática brasileira (decimal=',' e thousands='.')
        df = pd.read_html(requests.get(url_ops, headers={'User-Agent': 'Mozilla/5.0'}).text, decimal=',', thousands='.')[0]
        df.columns = df.columns.str.strip()
        df['Papel'] = df['Papel'].str.strip().str.upper()
        fund_data_dict = df.set_index('Papel').to_dict('index')
    except Exception as e: print(f"Erro ao baixar Fundamentus: {e}")

    # 2. Define quais ativos pesquisar
    ativos_finais = df['Papel'].head(10).tolist() if comando == "PESQUISAR" else [comando]
    print(f"Processando ativos: {ativos_finais}")

    lote_updates = []
    coluna_a = aba_base.col_values(1)
    agora_str = datetime.now().strftime('%d/%m/%Y %H:%M:%S')

    for ticker in ativos_finais:
        try:
            linha_busca = coluna_a.index(ticker) + 1 if ticker in coluna_a else len(coluna_a) + 1
            if ticker not in coluna_a:
                aba_base.update_cell(linha_busca, 1, ticker)
                coluna_a.append(ticker)

            # --- BUSCA YAHOO (Preço, DY e Valor de Mercado) ---
            acao = yf.Ticker(f"{ticker}.SA")
            info = acao.info
            y_preco = info.get('currentPrice', info.get('regularMarketPrice', 0))
            y_dy = info.get('dividendYield', 0)
            if y_dy is None: y_dy = 0
            
            # Pegamos o Valor de Mercado do Yahoo pois é mais rápido e confiável
            v_mkt = info.get('marketCap', 0) 

            # --- BUSCA FUNDAMENTUS (PL e PVP) ---
            p_l, p_vp = 0.0, 0.0
            if ticker in fund_data_dict:
                d = fund_data_dict[ticker]
                p_l = d.get('P/L', 0)
                p_vp = d.get('P/VP', 0)
            
            print(f"DEBUG {ticker}: P/L={p_l}, P/VP={p_vp}, V_MKT={v_mkt}, DY={y_dy}")

            # --- PREPARA LOTE PARA O GOOGLE SHEETS ---
            # AF=32(Data), B=2(Preço), C=3(DY), E=5(PL), F=6(PVP), AE=31(ValorMercado)
            lote_updates.append({'range': f'AF{linha_busca}', 'values': [[agora_str]]})
            lote_updates.append({'range': f'B{linha_busca}', 'values': [[converter_para_float(y_preco)]]})
            lote_updates.append({'range': f'C{linha_busca}', 'values': [[converter_para_float(y_dy)]]})
            lote_updates.append({'range': f'E{linha_busca}', 'values': [[converter_para_float(p_l)]]})
            lote_updates.append({'range': f'F{linha_busca}', 'values': [[converter_para_float(p_vp)]]})
            lote_updates.append({'range': f'AE{linha_busca}', 'values': [[converter_para_float(v_mkt)]]})

        except Exception as e: print(f"Erro no processamento de {ticker}: {e}")

    # Envia tudo de uma única vez para a planilha
    if lote_updates:
        aba_base.batch_update(lote_updates)
        print("Atualização concluída com sucesso!")

    return "Sucesso."

if __name__ == "__main__":
    atualizar_financeiro(None)
