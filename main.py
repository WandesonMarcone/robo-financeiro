import gspread
import pandas as pd
import yfinance as yf
import requests
from bs4 import BeautifulSoup
import re
import json

def atualizar_financeiro(request):
    # 1. Configurações
    JSON_KEY = 'credenciais.json' 
    SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk' 

    # 2. Autenticação (Serviço)
    gc = gspread.service_account(filename=JSON_KEY)
    planilha = gc.open_by_url(SPREADSHEET_URL)
    aba_base = planilha.worksheet("Base de Dados")

    # --- ESPECIFICAÇÃO 1: VALIDAÇÃO C3 ---
    gatilho = str(aba_base.acell('C3').value).strip().upper()
    if gatilho != "ATIVO":
        print("Processo interrompido pela validação C3.")
        return "Pausado"

  # 2. Definição da Carteira (10 Fixas + 5 Oportunidades)
    ativos_core = ["ITUB4", "BBAS3", "EGIE3", "TAEE11", "VALE3", "WEGE3", "SUZB3", "RADL3", "B3SA3", "VIVO3"]
    
    # Lógica de Oportunidade (Fundamentus)
    try:
        url = "https://www.fundamentus.com.br/resultado.php"
        headers = {'User-Agent': 'Mozilla/5.0'}
        df = pd.read_html(requests.get(url, headers=headers).text, decimal=',', thousands='.')[0]
        oportunidades = df[(df['P/L'] > 0) & (df['ROE'] > 0.10)].sort_values(by='Liq.2meses', ascending=False).head(5)['Papel'].tolist()
    except:
        oportunidades = ["PRIO3", "RENT3", "HAPV3", "AZUL4", "CVCB3"]

    ativos_finais = list(set(ativos_core + oportunidades))

    # Adaptado da sua função original para limpar qualquer métrica e tratar porcentagens
    def limpar_numero_fundamentus(texto, is_pct=False):
        if not texto or texto == "-" or texto == "0": return 0.0
        texto_limpo = re.sub(r'[^\d,]', '', texto).replace(',', '.')
        try:
            val = float(texto_limpo)
            return val / 100 if is_pct else val
        except:
            return 0.0

    print("Iniciando varredura na nuvem...")
    
    coluna_a = aba_base.col_values(1)
    lote_atualizacao = []
    dados_json = {}

    for ticker in ativos:
        try:
            # Encontra a linha (adaptado para criar linha nova se a ação de oportunidade não existir)
            if ticker in coluna_a:
                linha_busca = coluna_a.index(ticker) + 1
            else:
                linha_busca = len(coluna_a) + 1
                aba_base.update_cell(linha_busca, 1, ticker)
                coluna_a.append(ticker)

            # 🟢 FONTE 1: YAHOO (Agora com Dados Raízes)
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

            # 🔵 FONTE 2: FUNDAMENTUS (Agora com Dados Raízes)
            f_preco, f_pl, f_dy, f_vpa, f_roe = 0.0, 0.0, 0.0, 0.0, 0.0
            try:
                url = f"https://www.fundamentus.com.br/detalhes.php?papel={ticker}"
                headers = {'User-Agent': 'Mozilla/5.0'}
                resp = requests.get(url, headers=headers, timeout=5)
                sopa = BeautifulSoup(resp.text, 'html.parser')

                # O seu parser original, encapsulado numa função para buscar várias métricas
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

            # Prepara a formatação para gravar na planilha (com vírgula)
            def fmt(v): return f"{v:.2f}".replace('.', ',') if v else "N/D"

            # Atualiza a planilha: Yahoo (Colunas B até F) | Fundamentus (Colunas H até L)
            lote_atualizacao.append({'range': f'B{linha_busca}:F{linha_busca}', 'values': [[fmt(y_preco), fmt(y_pl), fmt(y_dy), fmt(y_vpa), fmt(y_roe)]]})
            lote_atualizacao.append({'range': f'H{linha_busca}:L{linha_busca}', 'values': [[fmt(f_preco), fmt(f_pl), fmt(f_dy), fmt(f_vpa), fmt(f_roe)]]})
            
            print(f"Coletado {ticker} | Yahoo Preço: {y_preco} | Fundamentus Preço: {f_preco}")

            # --- ESPECIFICAÇÃO 3: JSON DO MODAL (AG1) ---
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

        except Exception as e:
            print(f"Erro no ativo {ticker}: {e}")

    # Escreve todos os dados e o JSON na planilha de uma vez só
    if lote_atualizacao:
        aba_base.batch_update(lote_atualizacao)
        aba_base.update_acell('AG1', json.dumps(dados_json))

    return "Sucesso! Base atualizada."

if __name__ == "__main__":
    atualizar_financeiro(None)
