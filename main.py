import gspread
import pandas as pd
import yfinance as yf
import requests
from bs4 import BeautifulSoup
import re
import json
from datetime import datetime

# --- FUNÇÕES AUXILIARES NO TOPO ---
def fmt_moeda(valor):
    if valor is None: return "R$ 0,00"
    return f"R$ {valor:,.2f}".replace('.', 'X').replace(',', '.').replace('X', ',')

def fmt_pct(valor):
    if valor is None: return "0,00%"
    return f"{valor*100:.2f}%" # Multiplica por 100 para transformar 0.1029 em 10.29%

def obter_data_ordenacao(txt):
    try:
        return datetime.strptime(str(txt).strip(), '%d/%m/%Y %H:%M:%S')
    except:
        return datetime.min

def limpar_numero_fundamentus(texto, is_pct=False):
    if not texto or texto == "-" or texto == "0": return 0.0
    texto_limpo = re.sub(r'[^\d,]', '', texto).replace(',', '.')
    try:
        val = float(texto_limpo)
        return val / 100 if is_pct else val
    except:
        return 0.0

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
    oportunidades = [] # Inicializa vazio

    # Lógica de seleção de ativos
    if comando == "PESQUISAR":
        try:
            url_ops = "https://www.fundamentus.com.br/resultado.php"
            df_ops = pd.read_html(requests.get(url_ops, headers={'User-Agent': 'Mozilla/5.0'}).text, decimal=',', thousands='.')[0]
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
    coluna_a = aba_base.col_values(1)
    agora_str = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    data_hoje = datetime.now().date()

    # LOOP PRINCIPAL
    for ticker in ativos_finais:
        try:
            if ticker in coluna_a:
                linha_busca = coluna_a.index(ticker) + 1
            else:
                linha_busca = len(coluna_a) + 1
                aba_base.update_cell(linha_busca, 1, ticker)
                coluna_a.append(ticker)

            # Busca Yahoo
            acao = yf.Ticker(f"{ticker}.SA")
            info = acao.info
            y_preco = info.get('currentPrice', 0)
            y_dy = info.get('dividendYield', 0)
            if y_dy is None: y_dy = 0

            # Busca Fundamentus
            f_preco = 0.0
            try:
                url = f"https://www.fundamentus.com.br/detalhes.php?papel={ticker.upper()}"
                sopa = BeautifulSoup(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5).text, 'html.parser')
                for td in sopa.find_all('td', class_='label'):
                    if 'Cotação' in td.text:
                        f_preco = limpar_numero_fundamentus(td.find_next_sibling('td').text.strip())
                        break
            except: pass

            aba_base.update_cell(linha_busca, 32, agora_str)

            # Monta o JSON
            dados_json[ticker] = {
                "linha": linha_busca,
                "valor_atual": fmt_moeda(y_preco), 
                "f1_preco": fmt_moeda(y_preco),
                "f2_preco": fmt_moeda(f_preco),
                "media": fmt_moeda((y_preco + f_preco) / 2),
                "status": "DISCREPÂNCIA" if abs(y_preco - f_preco) > 0.5 else "100% SINCRONIZADO",
                "dy": fmt_pct(y_dy)
            }
        except Exception as e:
            print(f"Erro {ticker}: {e}")

    # EMPACOTAMENTO FINAL (Fora do Loop)
    pacote_final = {
        "META": {"oportunidades": oportunidades},
        "DADOS": dados_json
    }
    aba_base.update_acell('AG1', json.dumps(pacote_final))
    return "Sucesso."

if __name__ == "__main__":
    atualizar_financeiro(None)
