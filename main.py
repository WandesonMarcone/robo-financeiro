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

def obter_data_ordenacao(txt):
    try: return datetime.strptime(str(txt).strip(), '%d/%m/%Y %H:%M:%S')
    except: return datetime.min

def limpar_numero_fundamentus(texto, is_pct=False):
    if not texto or texto == "-" or texto == "0": return 0.0
    texto_limpo = re.sub(r'[^\d,]', '', texto).replace(',', '.')
    try:
        val = float(texto_limpo)
        return val / 100 if is_pct else val
    except: return 0.0

# --- MAIN ---
def atualizar_financeiro(request):
    JSON_KEY = 'credenciais.json' 
    SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk' 

    gc = gspread.service_account(filename=JSON_KEY)
    planilha = gc.open_by_url(SPREADSHEET_URL)
    aba_base = planilha.worksheet("Base de Dados")
    aba_metodo = planilha.worksheet("Metodologia Projetiva")

    comando = str(aba_metodo.acell('C3').value).strip().upper()
    if not comando or comando == "CONCLUÍDO":
        return "Aguardando comando."

    ativos_core = ["ITUB4", "BBAS3", "PSSA3", "CMIG4", "VALE3", "SANB11", "SBSP3", "BBSE3", "BBDC3", "PETR4"]
    oportunidades = []
    fund_data_dict = {} # Dicionário para busca rápida

    # Lógica de seleção e Mapeamento de Fundamentos
    if comando == "PESQUISAR":
        try:
            url_ops = "https://www.fundamentus.com.br/resultado.php"
            df_ops = pd.read_html(requests.get(url_ops, headers={'User-Agent': 'Mozilla/5.0'}).text, decimal=',', thousands='.')[0]
            # Converte em dicionário para consulta rápida
            fund_data_dict = df_ops.set_index('Papel').to_dict('index')
            
            df_ops['P/L'] = pd.to_numeric(df_ops['P/L'], errors='coerce')
            df_ops['ROE'] = df_ops['ROE'].str.replace('%', '').str.replace('.', '').str.replace(',', '.').astype(float) / 100
            oportunidades = df_ops[(df_ops['P/L'] > 0) & (df_ops['ROE'] > 0.10)].sort_values(by='Liq.2meses', ascending=False).head(5)['Papel'].tolist()
        except: pass

        todas_linhas = aba_base.get_all_values()
        outros_ativos_Fila = []
        for idx, linha in enumerate(todas_linhas[1:], start=2):
            if len(linha) > 0 and linha[0]:
                ticker_planilha = linha[0].strip().upper()
                if ticker_planilha != "TICKER" and ticker_planilha not in ativos_core and ticker_planilha not in oportunidades:
                    data_af = linha[31].strip() if len(linha) > 31 else ""
                    outros_ativos_Fila.append({"ticker": ticker_planilha, "data": data_af})
        
        outros_ativos_Fila.sort(key=lambda x: obter_data_ordenacao(x["data"]))
        ativos_rotativos = [item["ticker"] for item in outros_ativos_Fila[:5]]
        ativos_finais = list(set([a.upper() for a in (ativos_core + oportunidades + ativos_rotativos)]))
    else:
        ativos_finais = [comando]

    dados_json = {}
    lote_updates = [] # Armazena tudo para enviar de uma vez
    coluna_a = aba_base.col_values(1)
    agora_str = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    data_hoje = datetime.now().date()

    for ticker in ativos_finais:
        try:
            if ticker in coluna_a: linha_busca = coluna_a.index(ticker) + 1
            else:
                linha_busca = len(coluna_a) + 1
                aba_base.update_cell(linha_busca, 1, ticker)
                coluna_a.append(ticker)

            # TRAVA AF
            valor_af = aba_base.cell(linha_busca, 32).value
            if valor_af:
                try:
                    if datetime.strptime(str(valor_af).split()[0], '%d/%m/%Y').date() == data_hoje and comando != "PESQUISAR":
                        continue
                except: pass

            # --- BUSCA YAHOO ---
            acao = yf.Ticker(f"{ticker}.SA")
            info = acao.info
            y_preco = info.get('currentPrice', info.get('regularMarketPrice', 0))
            y_dy = info.get('dividendYield', 0) or 0

            # --- BUSCA FUNDAMENTUS (ou usa o cache do df_ops) ---
            f_preco = 0.0
            p_l, p_vp, v_mkt = 0.0, 0.0, 0.0
            
            # Tenta pegar do cache (Se PESQUISAR) ou busca página individual
            if ticker in fund_data_dict:
                d = fund_data_dict[ticker]
                p_l = d.get('P/L', 0)
                p_vp = d.get('P/VP', 0)
                v_mkt = d.get('Valor de mercado', 0)
                f_preco = d.get('Cotação', 0)
            else:
                # Fallback: Scraper individual se não estiver na lista geral
                try:
                    url = f"https://www.fundamentus.com.br/detalhes.php?papel={ticker.upper()}"
                    sopa = BeautifulSoup(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5).text, 'html.parser')
                    f_preco = limpar_numero_fundamentus(sopa.find('td', text='Cotação').find_next_sibling('td').text.strip())
                except: pass

            # --- PREPARA ATUALIZAÇÃO EM LOTE ---
            # Coluna AF (Data) = 32, E (P/L) = 5, F (P/VP) = 6, AE (ValMercado) = 31
            lote_updates.append({'range': f'AH{linha_busca}', 'values': [[agora_str]]}) # Nota: Ajuste se AF for 32
            lote_updates.append({'range': f'E{linha_busca}', 'values': [[str(p_l).replace('.',',')]]})
            lote_updates.append({'range': f'F{linha_busca}', 'values': [[str(p_vp).replace('.',',')]]})
            lote_updates.append({'range': f'AE{linha_busca}', 'values': [[str(v_mkt).replace('.',',')]]})

            dados_json[ticker] = {
                "linha": linha_busca,
                "valor_atual": fmt_moeda(y_preco), 
                "f1_preco": fmt_moeda(y_preco),
                "f2_preco": fmt_moeda(f_preco),
                "media": fmt_moeda((y_preco + f_preco) / 2),
                "status": "DISCREPÂNCIA" if abs(y_preco - f_preco) > 0.5 else "100% SINCRONIZADO",
                "dy": fmt_pct(y_dy)
            }
        except Exception as e: print(f"Erro {ticker}: {e}")

    # Envio ÚNICO para o Google Sheets (muito mais rápido)
    aba_base.batch_update(lote_updates)
    aba_base.update_acell('AG1', json.dumps({"META": {"oportunidades": oportunidades}, "DADOS": dados_json}))
    return "Sucesso."

if __name__ == "__main__":
    atualizar_financeiro(None)
