import gspread
import pandas as pd
import yfinance as yf
import requests
from bs4 import BeautifulSoup
import json
import warnings

warnings.filterwarnings('ignore')

# Função auxiliar para limpar números do Fundamentus
def limpa_fund(txt, is_pct=False):
    if not txt or txt == "0" or txt == "-": return 0.0
    t = str(txt).replace('.', '').replace(',', '.').replace('%', '')
    try:
        val = float(t)
        return val / 100 if is_pct else val
    except: return 0.0

def atualizar_financeiro(request):
    JSON_KEY = 'credenciais.json'
    SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit'

    gc = gspread.service_account(filename=JSON_KEY)
    aba = gc.open_by_url(SPREADSHEET_URL).worksheet("Base de Dados")

    # 1. Validação C3 (Gatilho)
    if str(aba.acell('C3').value).strip().upper() != "ATIVO":
        print("Robô pausado pelo gatilho C3.")
        return "Robô pausado."

    # 2. Definição da Carteira
    ativos_core = ["ITUB4", "BBAS3", "EGIE3", "TAEE11", "VALE3", "WEGE3", "SUZB3", "RADL3", "B3SA3", "VIVO3"]
    
    # 3. Oportunidades (Fundamentus)
    try:
        url = "https://www.fundamentus.com.br/resultado.php"
        df = pd.read_html(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).text, decimal=',', thousands='.')[0]
        oportunidades = df[(df['P/L'] > 0) & (df['ROE'].str.replace('%','').str.replace(',','.').astype(float) > 10)].sort_values(by='Liq.2meses', ascending=False).head(5)['Papel'].tolist()
    except:
        oportunidades = ["PRIO3", "RENT3", "HAPV3", "AZUL4", "CVCB3"]

    ativos_finais = list(set([a.upper() for a in (ativos_core + oportunidades)]))
    
    dados_json = {}
    coluna_a = aba.col_values(1)
    lote = []

    for ticker in ativos_finais:
        # Busca Yahoo
        y_preco, y_pl, y_dy, y_vpa, y_roe = 0.0, 0.0, 0.0, 0.0, 0.0
        try:
            acao = yf.Ticker(f"{ticker}.SA")
            info = acao.info
            y_preco = info.get('currentPrice', info.get('regularMarketPrice', 0))
            y_pl = info.get('trailingPE', 0)
            y_dy = info.get('dividendYield', 0) * 100
            y_vpa = info.get('bookValue', 0)
            y_roe = info.get('returnOnEquity', 0) * 100
        except: pass

        # Busca Fundamentus (Forçando Uppercase)
        f_preco, f_pl, f_dy, f_vpa, f_roe = 0.0, 0.0, 0.0, 0.0, 0.0
        try:
            url = f"https://www.fundamentus.com.br/detalhes.php?papel={ticker.upper()}"
            sopa = BeautifulSoup(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10).text, 'html.parser')
            def get_f(label):
                for td in sopa.find_all('td', class_='label'):
                    if label in td.text: return td.find_next_sibling('td').text.strip()
                return "0"
            f_preco = limpa_fund(get_f('Cotação'))
            f_pl = limpa_fund(get_f('P/L'))
            f_dy = limpa_fund(get_f('Div. Yield'), True)
            f_vpa = limpa_fund(get_f('VPA'))
            f_roe = limpa_fund(get_f('ROE'), True)
        except: pass

        # Linha na Planilha
        if ticker in coluna_a: linha = coluna_a.index(ticker) + 1
        else:
            linha = len(coluna_a) + 1
            aba.update_cell(linha, 1, ticker)
            coluna_a.append(ticker)

        # Prepara Lote (Yahoo nas colunas B-F, Fundamentus nas colunas H-L)
        # Formata com vírgula para planilha brasileira
        def f_br(v): return str(v).replace('.', ',')
        
        lote.append({'range': f'B{linha}:F{linha}', 'values': [[f_br(y_preco), f_br(y_pl), f_br(y_dy), f_br(y_vpa), f_br(y_roe)]]})
        lote.append({'range': f'H{linha}:L{linha}', 'values': [[f_br(f_preco), f_br(f_pl), f_br(f_dy), f_br(f_vpa), f_br(f_roe)]]})
        
        # JSON para o Modal
        dif = abs(y_preco - f_preco)
        dados_json[ticker] = {
            "linha": linha,
            "valor_atual": y_preco,
            "f1_preco": y_preco,
            "f2_preco": f_preco,
            "media": round((y_preco + f_preco) / 2, 2),
            "status": "DISCREPÂNCIA" if dif > 0.5 else "100% SINCRONIZADO",
            "variacao_pct": f"{((dif/y_preco)*100 if y_preco != 0 else 0):.2f}%"
        }

    aba.batch_update(lote)
    aba.update_acell('AG1', json.dumps(dados_json))
    return "Sucesso."

if __name__ == "__main__":
    atualizar_financeiro(None)
