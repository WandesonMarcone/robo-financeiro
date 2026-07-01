import gspread
import pandas as pd
import yfinance as yf
import requests
from bs4 import BeautifulSoup
import re
import json
from datetime import datetime

# Função auxiliar para ordenar as datas da coluna AF
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

    # --- LEITURA DO COMANDO (C3) ---
    comando = str(aba_metodo.acell('C3').value).strip().upper()
    if not comando or comando == "CONCLUÍDO":
        return "Aguardando comando na aba Metodologia Projetiva."

    # 3. Definição da Carteira Base (10 Fixas)
    ativos_core = ["ITUB4", "BBAS3", "EGIE3", "TAEE11", "VALE3", "WEGE3", "SUZB3", "RADL3", "B3SA3", "VIVO3"]

    # 4. Lógica de Ativos Finais
    if comando == "PESQUISAR":
        # Ciclo Completo
        try:
            url_ops = "https://www.fundamentus.com.br/resultado.php"
            df_ops = pd.read_html(requests.get(url_ops, headers={'User-Agent': 'Mozilla/5.0'}).text, decimal=',', thousands='.')[0]
            df_ops['P/L'] = pd.to_numeric(df_ops['P/L'], errors='coerce')
            df_ops['ROE'] = df_ops['ROE'].str.replace('%', '').str.replace('.', '').str.replace(',', '.').astype(float) / 100
            oportunidades = df_ops[(df_ops['P/L'] > 0) & (df_ops['ROE'] > 0.10)].sort_values(by='Liq.2meses', ascending=False).head(5)['Papel'].tolist()
        except:
            oportunidades = []

        # Rotação (Coluna AF - índice 31)
        todas_linhas = aba_base.get_all_values()
        coluna_a = [linha[0].strip().upper() for linha in todas_linhas if linha]
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
        dados_json = {"META_INFO": {"oportunidades_garimpadas": oportunidades}}
    else:
        # Modo Único (Ticker na C3)
        ativos_finais = [comando]
        dados_json = {}

    print(f"Ativos da rodada: {ativos_finais}")
    
    coluna_a = aba_base.col_values(1)
    agora_str = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    data_hoje = datetime.now().date()

    for ticker in ativos_finais:
        try:
            # Encontra ou cria a linha
            if ticker in coluna_a:
                linha_busca = coluna_a.index(ticker) + 1
            else:
                linha_busca = len(coluna_a) + 1
                aba_base.update_cell(linha_busca, 1, ticker)
                coluna_a.append(ticker)

            # TRAVA: Checa data na coluna AF (índice 31)
            valor_af = aba_base.cell(linha_busca, 32).value # Coluna AF = 32
            if valor_af:
                try:
                    data_ultima = datetime.strptime(str(valor_af).split()[0], '%d/%m/%Y').date()
                    if data_ultima == data_hoje and comando != "PESQUISAR":
                        print(f"Skipping {ticker}: Já atualizado hoje.")
                        continue
                except: pass

            # 🟢 FONTE 1: YAHOO
            y_preco = 0.0
            try:
                acao = yf.Ticker(f"{ticker}.SA")
                y_preco = acao.info.get('currentPrice', 0)
            except: pass

            # 🔵 FONTE 2: FUNDAMENTUS
            f_preco = 0.0
            try:
                url = f"https://www.fundamentus.com.br/detalhes.php?papel={ticker.upper()}"
                sopa = BeautifulSoup(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5).text, 'html.parser')
                for td in sopa.find_all('td', class_='label'):
                    if 'Cotação' in td.text:
                        f_preco = limpar_numero_fundamentus(td.find_next_sibling('td').text.strip())
                        break
            except: pass

            # Carimba AF com data de hoje
            aba_base.update_cell(linha_busca, 32, agora_str)

            # JSON para o Modal
            dif = abs(y_preco - f_preco)
            dados_json[ticker] = {
                "linha": linha_busca,
                "f1_preco": y_preco,
                "f2_preco": f_preco,
                "media": round((y_preco + f_preco) / 2, 2),
                "status": "DISCREPÂNCIA" if dif > 0.5 else "100% SINCRONIZADO"
            }
        except Exception as e:
            print(f"Erro {ticker}: {e}")

    aba_base.update_acell('AG1', json.dumps(dados_json))
    return "Sucesso."

if __name__ == "__main__":
    atualizar_financeiro(None)
