import gspread
import pandas as pd
import yfinance as yf
import requests
from bs4 import BeautifulSoup
import re
import json
from datetime import datetime

# --- FUNÇÕES AUXILIARES ---
def fmt_moeda_sheet(valor):
    """Retorna o valor como string formatada para o padrão BR (vírgula decimal)"""
    try:
        if valor is None or valor == 0: return "0,00"
        return f"{float(valor):.2f}".replace('.', ',')
    except: return "0,00"

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
        # Lê a tabela e limpa os nomes das colunas
        df = pd.read_html(requests.get(url_ops, headers={'User-Agent': 'Mozilla/5.0'}).text, decimal=',', thousands='.')[0]
        df.columns = df.columns.str.strip()
        df['Papel'] = df['Papel'].str.strip().str.upper()
        
        # Converte colunas chave para numérico, forçando erro se não for número
        for col in ['P/L', 'P/VP', 'Valor de mercado', 'Cotação']:
            if col in df.columns:
                # Remove pontos e converte para float
                df[col] = pd.to_numeric(df[col].astype(str).str.replace('.', '').str.replace(',', '.'), errors='coerce')
        
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

            # Busca Yahoo (Preço)
            acao = yf.Ticker(f"{ticker}.SA")
            y_preco = acao.info.get('currentPrice', 0)

            # Busca Fundamentus (valores processados acima)
            p_l, p_vp, v_mkt, f_preco = 0.0, 0.0, 0.0, 0.0
            
            if ticker in fund_data_dict:
                d = fund_data_dict[ticker]
                p_l = d.get('P/L', 0)
                p_vp = d.get('P/VP', 0)
                v_mkt = d.get('Valor de mercado', 0)
                f_preco = d.get('Cotação', 0)
                print(f"DEBUG {ticker}: P/L={p_l}, P/VP={p_vp}, V_MKT={v_mkt}")
            else:
                print(f"AVISO: {ticker} não encontrado no Fundamentus.")

            # --- PREPARA LOTE ---
            # AF=32, E=5, F=6, AE=31, B=2
            lote_updates.append({'range': f'AF{linha_busca}', 'values': [[agora_str]]})
            lote_updates.append({'range': f'E{linha_busca}', 'values': [[fmt_moeda_sheet(p_l)]]})
            lote_updates.append({'range': f'F{linha_busca}', 'values': [[fmt_moeda_sheet(p_vp)]]})
            lote_updates.append({'range': f'AE{linha_busca}', 'values': [[fmt_moeda_sheet(v_mkt)]]})
            lote_updates.append({'range': f'B{linha_busca}', 'values': [[fmt_moeda_sheet(y_preco)]]})

        except Exception as e: print(f"Erro no processamento de {ticker}: {e}")

    if lote_updates:
        aba_base.batch_update(lote_updates)
        print("Atualização concluída com sucesso!")
    
    return "Sucesso."

if __name__ == "__main__":
    atualizar_financeiro(None)