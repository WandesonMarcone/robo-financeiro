import gspread
import pandas as pd
import yfinance as yf
import requests
from bs4 import BeautifulSoup
import re
import json
from datetime import datetime

# Função auxiliar para ordenar as datas da coluna AH (vazias ou mais antigas vêm primeiro)
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

    # 3. Definição da Carteira Base (10 Fixas)
    ativos_core = ["ITUB4", "BBAS3", "EGIE3", "TAEE11", "VALE3", "WEGE3", "SUZB3", "RADL3", "B3SA3", "VIVO3"]

    # 4. Busca Oportunidades do Dia (5 mais quentes)
    try:
        url_ops = "https://www.fundamentus.com.br/resultado.php"
        df_ops = pd.read_html(requests.get(url_ops, headers={'User-Agent': 'Mozilla/5.0'}).text, decimal=',', thousands='.')[0]
        df_ops['P/L'] = pd.to_numeric(df_ops['P/L'], errors='coerce')
        df_ops['ROE'] = df_ops['ROE'].str.replace('%', '').str.replace('.', '').str.replace(',', '.').astype(float) / 100
        oportunidades = df_ops[(df_ops['P/L'] > 0) & (df_ops['ROE'] > 0.10)].sort_values(by='Liq.2meses', ascending=False).head(5)['Papel'].tolist()
    except:
        oportunidades = []

    # --- ESPECIFICAÇÃO 2: SISTEMA DE ROTAÇÃO POR DATA (COLUNA AH) ---
    todas_linhas = aba_base.get_all_values()
    coluna_a = [linha[0].strip().upper() for linha in todas_linhas if linha]
    
    outros_ativos_Fila = []
    for idx, linha in enumerate(todas_linhas[1:], start=2):
        if len(linha) > 0 and linha[0]:
            ticker_planilha = linha[0].strip().upper()
            # Ignora o cabeçalho e ativos que já são fixos ou oportunidades do dia
            if ticker_planilha != "TICKER" and ticker_planilha not in ativos_core and ticker_planilha not in oportunidades:
                # Coluna AF é a 32ª coluna (índice 31 no Python)
                data_ah = linha[31].strip() if len(linha) > 31 else ""
                outros_ativos_Fila.append({"ticker": ticker_planilha, "data": data_ah})

    # Ordena os outros ativos colocando os que estão sem data ou com a data mais antiga primeiro
    outros_ativos_Fila.sort(key=lambda x: obter_data_ordenacao(x["data"]))
    
    # Seleciona as 5 ações que estão há mais tempo sem atualização para entrarem nesta rodada
    ativos_rotativos = [item["ticker"] for item in outros_ativos_Fila[:5]]

    # Consolida a lista final de execução da rodada
    ativos_finais = list(set([a.upper() for a in (ativos_core + oportunidades + ativos_rotativos)]))
    print(f"Ativos da rodada: {ativos_finais} (Incluindo rotativos: {ativos_rotativos})")

    print("Iniciando varredura na nuvem...")
    lote_atualizacao = []
    dados_json = {}
    agora_str = datetime.now().strftime('%d/%m/%Y %H:%M:%S')

    for ticker in ativos_finais:
        try:
            if ticker in coluna_a:
                linha_busca = coluna_a.index(ticker) + 1
            else:
                linha_busca = len(coluna_a) + 1
                aba_base.update_cell(linha_busca, 1, ticker)
                coluna_a.append(ticker)

            # 🟢 FONTE 1: YAHOO
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

            # 🔵 FONTE 2: FUNDAMENTUS
            f_preco, f_pl, f_dy, f_vpa, f_roe = 0.0, 0.0, 0.0, 0.0, 0.0
            try:
                url = f"https://www.fundamentus.com.br/detalhes.php?papel={ticker}"
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

            # Atualiza dados fundamentalistas nas colunas correspondentes
            lote_atualizacao.append({'range': f'B{linha_busca}:F{linha_busca}', 'values': [[fmt(y_preco), fmt(y_pl), fmt(y_dy), fmt(y_vpa), fmt(y_roe)]]})
            lote_atualizacao.append({'range': f'H{linha_busca}:L{linha_busca}', 'values': [[fmt(f_preco), fmt(f_pl), fmt(f_dy), fmt(f_vpa), fmt(f_roe)]]})
            
            # Carimba a data e hora da atualização na coluna AH (coluna 34)
            lote_atualizacao.append({'range': f'AH{linha_busca}', 'values': [[agora_str]]})

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

    # Envia o pacote de atualizações estruturado para a planilha
    if lote_atualizacao:
        aba_base.batch_update(lote_atualizacao)
        
    # Injeta a lista de oportunidades no formato que o aviso do seu App Script espera
    dados_json["META_INFO"] = {"oportunidades_garimpadas": oportunidades}
    aba_base.update_acell('AG1', json.dumps(dados_json))

    return "Sucesso! Base e fila de rotação atualizadas."

if __name__ == "__main__":
    atualizar_financeiro(None)
