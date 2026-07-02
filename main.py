import gspread
import pandas as pd
import yfinance as yf
import requests
import io
from datetime import datetime

# --- CONFIGURAÇÕES ---
# Sua lista de 17 ações
ATIVOS = ["PETR4", "VALE3", "ITUB4", "BBDC4", "BBAS3", "B3SA3", "WEGE3", "ABEV3", 
          "SUZB3", "GGBR4", "BBSE3", "CSAN3", "RADL3", "CMIG4", "VIVT3", "MGLU3", "PRIO3"]

# Mapeamento para garantir que o script saiba onde gravar cada dado
# Colunas: B=Preço, C=DY, E=P/L, F=P/VP, ...
# Este script assume que o Fundamentus trará os campos compatíveis.
def atualizar_carteira_completa():
    gc = gspread.service_account(filename='credenciais.json')
    aba = gc.open_by_url('https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk').worksheet("Base de Dados")
    
    # 1. PEGAR DADOS FUNDAMENTAIS
    try:
        url = "https://www.fundamentus.com.br/resultado.php"
        df = pd.read_html(io.StringIO(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).text), decimal=',', thousands='.')[0]
        df['Papel'] = df['Papel'].str.strip().str.upper()
        df = df.set_index('Papel')
    except Exception as e:
        print(f"Erro ao buscar Fundamentus: {e}")
        return

    batch_updates = []
    linha_atual = 2 
    
    for ticker in ATIVOS:
        try:
            # Dados Financeiros (Preço)
            yf_info = yf.Ticker(f"{ticker}.SA").info
            preco = yf_info.get('currentPrice') or yf_info.get('regularMarketPrice') or 0
            
            # Dados Fundamentais (Fundamentus)
            f = df.loc[ticker] if ticker in df.index else {}
            
            # Construção do Batch (Ajuste o índice se o nome da coluna no Fundamentus for diferente)
            # Exemplo de mapeamento simplificado:
            values = [
                [preco],                                    # B: Preco
                [str(f.get('Div.Yield', 0))],               # C: DY
                [''],                                       # D: Nº Ações (Placeholder)
                [str(f.get('P/L', 0))],                     # E: P/L
                [str(f.get('P/VP', 0))],                    # F: P/VP
                [''],                                       # G: P/Ativos (Placeholder)
                [str(f.get('Marg. Bruta', 0))],             # H: Margem Bruta
                [''],                                       # I: Margem EBIT
                [str(f.get('Marg. Líq.', 0))],              # J: Marg. Liquida
                [str(f.get('P/EBIT', 0))],                  # K: P/EBIT
                [str(f.get('EV/EBIT', 0))],                 # L: EV/EBIT
                [''],                                       # M: Dívida Líq/EBIT
                [''],                                       # N: Dív. Liq/Patri
                [str(f.get('PSR', 0))],                     # O: PSR
                [''],                                       # P: P/Cap Giro
                [''],                                       # Q: P/Ativo Circ. Liq
                [''],                                       # R: Liq. Corrente
                [str(f.get('ROE', 0))],                     # S: ROE
                [''],                                       # T: ROA
                [str(f.get('ROIC', 0))],                    # U: ROIC
                [''],                                       # V: Patrimônio/Ativos
                [''],                                       # W: Passivos/Ativos
                [''],                                       # X: Giro Ativos
                [''],                                       # Y: CAGR Receitas
                [''],                                       # Z: CAGR Lucros
                [str(f.get('Liq. Corr.', 0))],              # AA: Liq. Media Diaria (Ajustar campo)
                [str(f.get('VPA', 0))],                     # AB: VPA
                [str(f.get('LPA', 0))],                     # AC: LPA
                [''],                                       # AD: PEG Ratio
                [str(f.get('Valor de Mercado', 0))],        # AE: Valor Mercado
                [f"{datetime.now().strftime('%d/%m %H:%M')} OK"] # AF: Atualização
            ]
            
            # Prepara o lote de escrita para este ticker (Colunas B a AF)
            batch_updates.append({'range': f'B{linha_atual}:AF{linha_atual}', 'values': [values]})
            linha_atual += 1
            
        except Exception as e:
            print(f"Erro ao processar {ticker}: {e}")
            
    if batch_updates:
        aba.batch_update(batch_updates)
        print("Sucesso: Batch update enviado!")

if __name__ == "__main__":
    atualizar_carteira_completa()
