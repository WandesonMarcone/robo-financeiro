import gspread
import pandas as pd
import yfinance as yf
import requests
import json
import re
from datetime import datetime

# --- FUNÇÕES AUXILIARES ---
def converter_para_float(valor):
    try:
        if isinstance(valor, str): valor = valor.replace(',', '.')
        return float(valor)
    except: return 0.0

def calcular_discrepancia(v1, v2):
    """Calcula a diferença percentual entre dois números."""
    v1, v2 = abs(float(v1 or 0)), abs(float(v2 or 0))
    if v1 == 0 and v2 == 0: return 0.0
    if v1 == 0 or v2 == 0: return 1.0 
    return abs(v1 - v2) / max(v1, v2)

def obter_data_ordenacao(txt):
    try: return datetime.strptime(str(txt).strip(), '%d/%m/%Y %H:%M:%S')
    except: return datetime.min

# --- MAIN ---
def atualizar_financeiro(request):
    print("Iniciando Motor Completo + Auditoria...")
    JSON_KEY = 'credenciais.json' 
    SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk' 

    gc = gspread.service_account(filename=JSON_KEY)
    planilha = gc.open_by_url(SPREADSHEET_URL)
    aba_base = planilha.worksheet("Base de Dados")
    aba_metodo = planilha.worksheet("Metodologia Projetiva")

    comando = str(aba_metodo.acell('C3').value).strip().upper()
    if not comando or comando == "CONCLUÍDO": return "Aguardando comando."

    ativos_core = ["ITUB4", "BBAS3", "PSSA3", "CMIG4", "VALE3", "SANB11", "SBSP3", "BBSE3", "BBDC3", "PETR4"]
    oportunidades = []
    fund_data_dict = {}

    # 1. LÓGICA ORIGINAL: RASPAGEM E SELEÇÃO DE ATIVOS
    if comando == "PESQUISAR":
        try:
            url_ops = "https://www.fundamentus.com.br/resultado.php"
            df = pd.read_html(requests.get(url_ops, headers={'User-Agent': 'Mozilla/5.0'}).text, decimal=',', thousands='.')[0]
            df.columns = df.columns.str.strip()
            df['Papel'] = df['Papel'].str.strip().str.upper()
            
            # Converte DY e ROE para float
            if 'Div.Yield' in df.columns:
                df['Div.Yield'] = pd.to_numeric(df['Div.Yield'].astype(str).str.replace('%', '').str.replace('.', '').str.replace(',', '.'), errors='coerce') / 100
            if 'ROE' in df.columns:
                df['ROE'] = pd.to_numeric(df['ROE'].astype(str).str.replace('%', '').str.replace('.', '').str.replace(',', '.'), errors='coerce') / 100
                
            fund_data_dict = df.set_index('Papel').to_dict('index')

            # Oportunidades: P/L > 0 e ROE > 10%
            df['P/L'] = pd.to_numeric(df['P/L'].astype(str).str.replace('.', '').str.replace(',', '.'), errors='coerce')
            oportunidades = df[(df['P/L'] > 0) & (df['ROE'] > 0.10)].sort_values(by='Liq.2meses', ascending=False).head(5)['Papel'].tolist()
        except Exception as e: print(f"Erro ao baixar Fundamentus: {e}")

        # Rotatividade: pega os 5 mais antigos da planilha
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
        
        # Junta tudo
        ativos_finais = list(set([a.upper() for a in (ativos_core + oportunidades + ativos_rotativos)]))
    else:
        ativos_finais = [comando]

    print(f"Processando ativos: {ativos_finais}")

    # 2. LÓGICA DE AUDITORIA E ATUALIZAÇÃO
    dados_json_global = {} # Para o Modal original
    lote_updates = []
    coluna_a = aba_base.col_values(1)
    agora_str = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    data_hoje = datetime.now().date()

    for ticker in ativos_finais:
        try:
            linha_busca = coluna_a.index(ticker) + 1 if ticker in coluna_a else len(coluna_a) + 1
            if ticker not in coluna_a:
                aba_base.update_cell(linha_busca, 1, ticker)
                coluna_a.append(ticker)

            # TRAVA ORIGINAL DE DATA
            valor_af = aba_base.cell(linha_busca, 32).value
            if valor_af:
                try:
                    if datetime.strptime(str(valor_af).split()[0], '%d/%m/%Y').date() == data_hoje and comando != "PESQUISAR":
                        print(f"[{ticker}] Ignorado: Já atualizado hoje.")
                        continue
                except: pass

            # --- BUSCA YAHOO E FUNDAMENTUS ---
            acao = yf.Ticker(f"{ticker}.SA")
            info = acao.info
            y_preco = info.get('currentPrice', info.get('regularMarketPrice', 0)) or 0
            y_dy = info.get('dividendYield', 0) or 0
            y_pl = info.get('trailingPE', 0) or 0
            y_pvp = info.get('priceToBook', 0) or 0
            y_vmkt = info.get('marketCap', 0) or 0

            f_preco, f_pl, f_pvp, f_dy = 0.0, 0.0, 0.0, 0.0
            if ticker in fund_data_dict:
                d = fund_data_dict[ticker]
                f_preco = converter_para_float(d.get('Cotação', 0))
                f_pl = converter_para_float(d.get('P/L', 0))
                f_pvp = converter_para_float(d.get('P/VP', 0))
                f_dy = converter_para_float(d.get('Div.Yield', 0))

            # --- AVALIAÇÃO DE CONFIANÇA (Tolerância 5%) ---
            sinc_preco = calcular_discrepancia(y_preco, f_preco) <= 0.05
            sinc_pl = calcular_discrepancia(y_pl, f_pl) <= 0.05
            is_seguro = sinc_preco and sinc_pl

            # Popula o JSON Global para o seu App Script continuar funcionando
            def fmt(v): return f"R$ {v:,.2f}".replace('.', 'X').replace(',', '.').replace('X', ',') if v else "R$ 0,00"
            dados_json_global[ticker] = {
                "linha": linha_busca,
                "valor_atual": fmt(y_preco), 
                "f1_preco": fmt(y_preco),
                "f2_preco": fmt(f_preco),
                "status": "100% SINCRONIZADO" if is_seguro else "DISCREPÂNCIA"
            }

            if is_seguro:
                # 🟢 TUDO CONFERE: SALVA AUTOMÁTICO
                lote_updates.append({'range': f'AF{linha_busca}', 'values': [[agora_str]]})
                lote_updates.append({'range': f'B{linha_busca}', 'values': [[converter_para_float(y_preco)]]})
                lote_updates.append({'range': f'C{linha_busca}', 'values': [[converter_para_float(f_dy)]]})
                lote_updates.append({'range': f'E{linha_busca}', 'values': [[converter_para_float(f_pl)]]})
                lote_updates.append({'range': f'F{linha_busca}', 'values': [[converter_para_float(f_pvp)]]})
                lote_updates.append({'range': f'AE{linha_busca}', 'values': [[converter_para_float(y_vmkt)]]})
                
                lote_updates.append({'range': f'AG{linha_busca}', 'values': [[""]]}) # Limpa alerta local
                lote_updates.append({'range': f'AH{linha_busca}', 'values': [[f"[{agora_str}] 🟢 Sincronizado Automático."]]})
            else:
                # 🔴 DISCREPÂNCIA
                pacote_auditoria = {
                    "status": "DISCREPANCIA", "ticker": ticker,
                    "yahoo": {"preco": y_preco, "pl": y_pl, "pvp": y_pvp, "dy": y_dy},
                    "fundamentus": {"preco": f_preco, "pl": f_pl, "pvp": f_pvp, "dy": f_dy}
                }
                lote_updates.append({'range': f'AG{linha_busca}', 'values': [[json.dumps(pacote_auditoria)]]})
                lote_updates.append({'range': f'AH{linha_busca}', 'values': [[f"[{agora_str}] 🔴 Discrepância de fontes. Aguardando decisão."]]})

        except Exception as e: print(f"Erro em {ticker}: {e}")

    # Envia dados em lote para as linhas
    if lote_updates:
        aba_base.batch_update(lote_updates)
        print("Células e Históricos atualizados!")

    # DEVOLVE O SEU SISTEMA DE NOTIFICAÇÃO ORIGINAL (AG1)
    aba_base.update_acell('AG1', json.dumps({"META": {"oportunidades": oportunidades}, "DADOS": dados_json_global}))

    return "Sucesso."

if __name__ == "__main__":
    atualizar_financeiro(None)
