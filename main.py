import gspread
import pandas as pd
import yfinance as yf
import requests
from bs4 import BeautifulSoup
import re
import json
from datetime import datetime

# --- FUNÇÕES AUXILIARES ---
def fmt_moeda(valor):
    if valor is None: return "R$ 0,00"
    return f"R$ {valor:,.2f}".replace('.', 'X').replace(',', '.').replace('X', ',')

def fmt_pct(valor):
    if valor is None: return "0,00%"
    return f"{valor*100:.2f}%"

def limpar_numero(texto):
    if not texto or texto == "-" or texto == "0": return 0.0
    # Remove tudo exceto dígitos, vírgula e ponto. Converte para float padrão
    texto_limpo = re.sub(r'[^\d.,]', '', str(texto)).replace('.', '').replace(',', '.')
    try: return float(texto_limpo)
    except: return 0.0

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

    # Mapeamento do Fundamentus (Carrega a tabela completa uma única vez)
    fund_data_dict = {}
    ativos_finais = []
    
    # 1. Carrega dados do Fundamentus (Mina de ouro para PL, PVP, Valor Mkt)
    try:
        url_ops = "https://www.fundamentus.com.br/resultado.php"
        df = pd.read_html(requests.get(url_ops, headers={'User-Agent': 'Mozilla/5.0'}).text, decimal=',', thousands='.')[0]
        df['Papel'] = df['Papel'].str.strip().str.upper()
        fund_data_dict = df.set_index('Papel').to_dict('index')
    except Exception as e: print(f"Erro ao baixar Fundamentus: {e}")

    # 2. Define quais ativos pesquisar
    if comando == "PESQUISAR":
        # (Sua lógica atual de rotatividade que você já confia)
        ativos_finais = df['Papel'].head(10).tolist() # Exemplo: apenas os 10 primeiros por liquidez ou seus fixos
    else:
        ativos_finais = [comando]

    print(f"Ativos processando: {ativos_finais}")

    lote_updates = []
    coluna_a = aba_base.col_values(1)
    agora_str = datetime.now().strftime('%d/%m/%Y %H:%M:%S')

    for ticker in ativos_finais:
        try:
            # Encontra linha
            linha_busca = coluna_a.index(ticker) + 1 if ticker in coluna_a else len(coluna_a) + 1
            if ticker not in coluna_a:
                aba_base.update_cell(linha_busca, 1, ticker)
                coluna_a.append(ticker)

            # Busca Yahoo (Preço)
            acao = yf.Ticker(f"{ticker}.SA")
            y_preco = acao.info.get('currentPrice', 0)

            # Busca Fundamentus (PL, PVP, ValMkt)
            p_l, p_vp, v_mkt = 0.0, 0.0, 0.0
            if ticker in fund_data_dict:
                p_l = fund_data_dict[ticker].get('P/L', 0)
                p_vp = fund_data_dict[ticker].get('P/VP', 0)
                v_mkt = fund_data_dict[ticker].get('Valor de mercado', 0)

            # --- PREPARA LOTE (Ajuste as colunas aqui se necessário) ---
            # AF=32 (Data), E=5 (PL), F=6 (PVP), AE=31 (ValorMercado)
            lote_updates.append({'range': f'AF{linha_busca}', 'values': [[agora_str]]})
            lote_updates.append({'range': f'E{linha_busca}', 'values': [[str(p_l).replace('.',',')]]})
            lote_updates.append({'range': f'F{linha_busca}', 'values': [[str(p_vp).replace('.',',')]]})
            lote_updates.append({'range': f'AE{linha_busca}', 'values': [[str(v_mkt).replace('.',',')]]})
            lote_updates.append({'range': f'B{linha_busca}', 'values': [[str(y_preco).replace('.',',')]]}) # Preço

        except Exception as e: print(f"Erro {ticker}: {e}")

    # Envia tudo de uma vez
    if lote_updates:
        aba_base.batch_update(lote_updates)
    
    return "Sucesso."

if __name__ == "__main__":
    atualizar_financeiro(None)
