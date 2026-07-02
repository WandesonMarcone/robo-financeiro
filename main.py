import gspread
import pandas as pd
import yfinance as yf
import requests
import io
import random
import pytz
from datetime import datetime

# --- CONFIGURAÇÕES ---
FIXAS = ["PETR4", "VALE3", "ITUB4", "BBDC4"] 
JSON_KEY = 'credenciais.json' 
SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk' 

def formatar(val):
    """Garante float e conserta o bug do % exorbitante."""
    try: 
        if isinstance(val, str):
            is_percent = '%' in val # Verifica se é uma porcentagem
            val = val.replace('%', '').replace('.', '').replace(',', '.')
            numero = float(val)
            # Se for porcentagem, divide por 100 para o Sheets exibir corretamente
            return numero / 100 if is_percent else numero
            
        return float(val) if val is not None and not pd.isna(val) else 0.0
    except: return 0.0

def atualizar_financeiro():
    # Conexão
    gc = gspread.service_account(filename=JSON_KEY)
    planilha = gc.open_by_url(SPREADSHEET_URL)
    aba_base = planilha.worksheet("Base de Dados")
    aba_metodo = planilha.worksheet("Metodologia Projetiva")
    
    # Horário de São Paulo
    sp_tz = pytz.timezone('America/Sao_Paulo')
    agora_sp = datetime.now(sp_tz).strftime('%d/%m %H:%M')
    
    # 1. BUSCA DADOS FUNDAMENTUS
    try:
        url = "https://www.fundamentus.com.br/resultado.php"
        df = pd.read_html(io.StringIO(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).text), decimal=',', thousands='.')[0]
        df['Papel'] = df['Papel'].str.strip().str.upper()
        df = df.set_index('Papel')
    except Exception as e:
        print(f"Erro ao buscar Fundamentus: {e}")
        return

    # 2. DEFINIÇÃO DA FILA (A Mecânica 4-em-1)
    # 2.1 - C3 (Metodologia)
    ticker_c3 = str(aba_metodo.acell('C3').value).strip().upper()
    
    # 2.2 - Oportunidades (Parâmetros: P/L abaixo de 12 e P/VP abaixo de 1.5)
    opps = df[(df['P/L'].astype(float) < 12) & (df['P/VP'].astype(float) < 1.5)].index.tolist()[:5]
    
    # 2.3 - Aleatórias da Planilha
    todas = aba_base.col_values(1)[1:]
    aleatorias = random.sample(todas, min(len(todas), 3))
    
    # Junta todas, remove duplicadas e garante que existam na planilha
    fila = list(set(FIXAS + [ticker_c3] + opps + aleatorias))
    fila = [t for t in fila if t in df.index and t in todas]

    # 3. PROCESSAMENTO E CAPTURA YAHOO FINANCE
    batch_updates = []
    
    for ticker in fila:
        linha_idx = todas.index(ticker) + 2
        try:
            # 3.1 - YFINANCE (Preenchendo as falhas do Fundamentus)
            yf_info = yf.Ticker(f"{ticker}.SA").info
            preco = formatar(yf_info.get('currentPrice') or yf_info.get('regularMarketPrice'))
            n_acoes = formatar(yf_info.get('sharesOutstanding')) # Coluna D
            roa = formatar(yf_info.get('returnOnAssets'))        # Coluna T
            peg_ratio = formatar(yf_info.get('trailingPegRatio') or yf_info.get('pegRatio')) # Coluna AD
            valor_mercado = formatar(yf_info.get('marketCap'))   # Coluna AE
            
            # 3.2 - FUNDAMENTUS (Base primária)
            f = df.loc[ticker]
            
            # 3.3 - MAPEAMENTO COMPLETO (B até AF)
            row = [
                preco,                                    # B: Preço (YF)
                formatar(f.get('Div.Yield', 0)),          # C: DY
                n_acoes,                                  # D: Nº Ações (YF)
                formatar(f.get('P/L', 0)),                # E: P/L
                formatar(f.get('P/VP', 0)),               # F: P/VP
                formatar(f.get('P/Ativo', 0)),            # G: P/Ativo
                formatar(f.get('Mrg Bruta', 0)),          # H: Marg. Bruta
                formatar(f.get('Mrg Ebit', 0)),           # I: Marg. EBIT
                formatar(f.get('Mrg. Líq.', 0)),          # J: Marg. Líq.
                formatar(f.get('P/EBIT', 0)),             # K: P/EBIT
                formatar(f.get('EV/EBIT', 0)),            # L: EV/EBIT
                formatar(f.get('Dív.Líq/ Patrim.', 0)),   # M: Div.Liq/Ebit (Mapeado via Patrimônio)
                formatar(f.get('Dív.Líq/ Patrim.', 0)),   # N: Div.Liq/Patri
                formatar(f.get('PSR', 0)),                # O: PSR
                formatar(f.get('P/Cap.Giro', 0)),         # P: P/Cap.Giro
                formatar(f.get('P/Ativ Circ.Liq', 0)),    # Q: P.At.Circ.Liq
                formatar(f.get('Liq. Corr.', 0)),         # R: Liq. Corr
                formatar(f.get('ROE', 0)),                # S: ROE
                roa,                                      # T: ROA (YF)
                formatar(f.get('ROIC', 0)),               # U: ROIC
                0, 0, 0,                                  # V, W, X (Vazios Intencionais)
                formatar(f.get('Cresc. Rec.5a', 0)),      # Y: CAGR Rec
                0,                                        # Z: CAGR Lucros (Vazio Intencional)
                formatar(f.get('Liq.2meses', 0)),         # AA: Liq. Media
                formatar(f.get('VPA', 0)),                # AB: VPA
                formatar(f.get('LPA', 0)),                # AC: LPA
                peg_ratio,                                # AD: PEG Ratio (YF)
                valor_mercado,                            # AE: Valor Mercado (YF)
                f"{agora_sp} OK"                          # AF: Atualização
            ]
            batch_updates.append({'range': f'B{linha_idx}:AF{linha_idx}', 'values': [row]})
        except Exception as e:
            print(f"Erro ao processar {ticker}: {e}")

    # 4. ESCRITA EM LOTE
    if batch_updates:
        aba_base.batch_update(batch_updates)
        print(f"Sucesso: Atualizadas {len(batch_updates)} ações.")

if __name__ == "__main__":
    atualizar_financeiro()