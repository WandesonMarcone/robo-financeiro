import gspread
import pandas as pd
import yfinance as yf
import requests
from bs4 import BeautifulSoup
import re
import json

def atualizar_financeiro(request):
    # 1. Configurações
    JSON_KEY = 'credenciais.json' # Nome do arquivo que você vai subir
    SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit' # <--- NÃO ESQUEÇA DE TROCAR

    # 2. Autenticação (Serviço)
    gc = gspread.service_account(filename=JSON_KEY)
    planilha = gc.open_by_url(SPREADSHEET_URL)
    aba_base = planilha.worksheet("Base de Dados")

    # 3. Leitura dos dados
    df = pd.DataFrame(aba_base.get_all_records())

    # Lista de ativos (Você pode futuramente automatizar isso)
    ativos = ["ITSA4", "ITSA3", "VALE3"]

    def limpar_preco_fundamentus(texto):
        # Remove tudo que não for dígito ou vírgula/ponto
        texto_limpo = re.sub(r'[^\d,]', '', texto).replace(',', '.')
        try:
            return float(texto_limpo)
        except:
            return 0.0

    print("Iniciando varredura na nuvem...")

    for ticker in ativos:
        try:
            # Encontra a linha
            celula = aba_base.find(ticker, in_column=1)
            linha_busca = celula.row

            # 🟢 FONTE 1: YAHOO
            f1_preco = 0.0
            try:
                acao = yf.Ticker(f"{ticker}.SA")
                f1_preco = round(acao.history(period="1d")['Close'].iloc[-1], 2)
            except: pass

            # 🔵 FONTE 2: FUNDAMENTUS
            f2_preco = 0.0
            try:
                url = f"https://www.fundamentus.com.br/detalhes.php?papel={ticker}"
                headers = {'User-Agent': 'Mozilla/5.0'}
                resp = requests.get(url, headers=headers, timeout=5)
                sopa = BeautifulSoup(resp.text, 'html.parser')

                # Parser de alta precisão
                for td in sopa.find_all('td', class_='label'):
                    if 'Cotação' in td.text:
                        valor_td = td.find_next_sibling('td')
                        if valor_td:
                            f2_preco = limpar_preco_fundamentus(valor_td.text.strip())
                            break
            except: pass

            # Atualiza a planilha apenas se encontrou valores válidos
            if f1_preco > 0:
                aba_base.update_cell(linha_busca, 2, f"{f1_preco:.2f}".replace('.', ','))
                print(f"Atualizado {ticker}: {f1_preco}")

        except Exception as e:
            print(f"Erro no ativo {ticker}: {e}")

    return "Sucesso! Base atualizada."
