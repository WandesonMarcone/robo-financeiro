import gspread
import pandas as pd
import yfinance as yf
import requests
from bs4 import BeautifulSoup
import re
import json

def atualizar_financeiro(request):
    JSON_KEY = 'credenciais.json' 
    SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk' 

    gc = gspread.service_account(filename=JSON_KEY)
    planilha = gc.open_by_url(SPREADSHEET_URL)
    aba_base = planilha.worksheet("Base de Dados")

    gatilho = str(aba_base.acell('C3').value).strip().upper()
    if gatilho != "ATIVO":
        print("Processo interrompido pela validação C3.")
        return "Pausado"

    ativos_core = ["ITUB4", "BBAS3", "EGIE3", "TAEE11", "VALE3", "WEGE3", "SUZB3", "RADL3", "B3SA3", "VIVO3"]

    # Lógica de Oportunidade (SEM PLANO B)
    try:
        url = "https://www.fundamentus.com.br/resultado.php"
        headers = {'User-Agent': 'Mozilla/5.0'}
        df = pd.read_html(requests.get(url, headers=headers).text, decimal=',', thousands='.')[0]
        
        df['P/L'] = pd.to_numeric(df['P/L'], errors='coerce')
        df['ROE'] = df['ROE'].str.replace('%', '').str.replace('.', '').str.replace(',', '.').astype(float) / 100
        
        oportunidades = df[(df['P/L'] > 0) & (df['ROE'] > 0.10)].sort_values(by='Liq.2meses', ascending=False).head(5)['Papel'].tolist()
    except Exception as e:
        print(f"Erro na busca do Fundamentus: {e}")
        # Se der erro, a lista fica vazia. Não há mais "ações inventadas".
        oportunidades = []

    ativos_finais = list(set([a.upper() for a in (ativos_core + oportunidades)]))

    def limpar_numero_fundamentus(texto, is_pct=False):
        if not texto or texto == "-" or texto == "0": return 0.0
        texto_limpo = re.sub(r'[^\d,]', '', texto).replace(',', '.')
        try:
            val = float(texto_limpo)
            return val / 100 if is_pct else val
        except:
            return 0.0

    coluna_a = aba_base.col_values(1)
    lote_atualizacao = []
    
    # Adicionando as oportunidades garimpadas no JSON para o App Script ler
    dados_json = {
        "META_INFO": {
            "oportunidades_garimpadas": oportunidades
        }
    }

    for ticker in ativos_finais:
        try:
            if ticker in coluna_a:
                linha_busca = coluna_a.index(ticker) + 1
            else:
                linha_busca = len(coluna_a) + 1
                aba_base.update_cell(linha_busca, 1, ticker)
                coluna_a.append(ticker)

            y_preco, y_pl, y_dy, y_vpa, y_roe = 0.0, 0.0, 0.0, 0.0, 0.0
            try:
                acao = yf.Ticker(f"{ticker}.SA")
                info = acao.info
                y_preco = info.get('currentPrice', info.get('regularMarketPrice', 0))
                y_pl = info.get('trailingPE', 0)
                y_dy = (info.get('dividendYield', 0) or 0) * 100
                y_vpa = info.get('bookValue', 0)
                y_roe = (info.get('returnOnEquity', 0) or 0) * 100
            except: pass

            f_preco, f_pl, f_dy, f_vpa, f_roe = 0.0, 0.0, 0.0, 0.0, 0.0
            try:
                url = f"https://www.fundamentus.com.br/detalhes.php?papel={ticker.upper()}"
                headers = {'User-Agent': 'Mozilla/5.0'}
                sopa = BeautifulSoup(requests.get(url, headers=headers, timeout=5).text, 'html.parser')

                def extrair_dado_sopa(label):
                    for td in sopa.find_all('td', class_='label'):
                        if label in td.text:
                            valor_td = td.find_next_sibling('td')
                            if valor_td: return valor_td.text.strip()
                    return "0"

                f_preco = limpar_numero_fundamentus(extrair_dado_sopa('Cotação'))
                f_pl = limpar_numero_fundamentus(extrair_dado_sopa('P/L'))
                f_dy = limpar_numero_fundamentus(extrair_dado_sopa('Div. Yield'), True)
                f_vpa = limpar_numero_fundamentus(extrair_dado_sopa('VPA'))
                f_roe = limpar_numero_fundamentus(extrair_dado_sopa('ROE'), True)
            except: pass

            def fmt(v): return f"{v:.2f}".replace('.', ',') if v else "N/D"

            lote_atualizacao.append({'range': f'B{linha_busca}:F{linha_busca}', 'values': [[fmt(y_preco), fmt(y_pl), fmt(y_dy), fmt(y_vpa), fmt(y_roe)]]})
            lote_atualizacao.append({'range': f'H{linha_busca}:L{linha_busca}', 'values': [[fmt(f_preco), fmt(f_pl), fmt(f_dy), fmt(f_vpa), fmt(f_roe)]]})

            dif = abs(y_preco - f_preco)
            dados_json[ticker] = {
                "linha": linha_busca,
                "valor_atual": y_preco,
                "f1_preco": y_preco,
                "f2_preco": f_preco,
                "media": round((y_preco + f_preco) / 2, 2),
                "status": "DISCREPÂNCIA" if dif > 0.5 else "100% SINCRONIZADO",
                "variacao_pct": f"{((dif/y_preco)*100 if y_preco != 0 else 0):.2f}%"
            }
        except: pass

    if lote_atualizacao:
        aba_base.batch_update(lote_atualizacao)
        aba_base.update_acell('AG1', json.dumps(dados_json))

    return "Sucesso! Base atualizada."

if __name__ == "__main__":
    atualizar_financeiro(None)
