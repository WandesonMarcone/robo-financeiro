import gspread
import pandas as pd
import yfinance as yf
import requests
import io
import random
import pytz
import urllib.parse
from datetime import datetime

# --- CONFIGURAÇÕES ---
FIXAS = ["PETR4", "VALE3", "ITUB4", "BBDC4"] 
JSON_KEY = 'credenciais.json' 
SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk' 
TELEFONE_WHATSAPP = "553491503895" 
API_KEY_WHATSAPP = "5116767"

def formatar(val):
    """Garante float e conserta o bug do % exorbitante."""
    try: 
        if isinstance(val, str):
            is_percent = '%' in val
            val = val.replace('%', '').replace('.', '').replace(',', '.')
            numero = float(val)
            return numero / 100 if is_percent else numero
        return float(val) if val is not None and not pd.isna(val) else 0.0
    except: return 0.0

def enviar_whatsapp(categorias):
    print("\n[5/5] Preparando notificação do WhatsApp...")
    msg = "📊 *Relatório B3 - Mestre* 📊\n\n"
    if categorias['Fixas']: msg += f"📌 *Fixas:* {', '.join(categorias['Fixas'])}\n"
    if categorias['Metodologia']: msg += f"🔍 *Metodologia:* {', '.join(categorias['Metodologia'])}\n"
    if categorias['Oportunidades']: msg += f"🎯 *Oportunidades:* {', '.join(categorias['Oportunidades'])}\n"
    if categorias['Aleatorias']: msg += f"🎲 *Aleatórias:* {', '.join(categorias['Aleatorias'])}\n"
    
    try:
        url = f"https://api.callmebot.com/whatsapp.php?phone={TELEFONE_WHATSAPP}&text={urllib.parse.quote(msg)}&apikey={API_KEY_WHATSAPP}"
        resposta = requests.get(url, timeout=5)
        if resposta.status_code == 200: print(" -> WhatsApp enviado com sucesso!")
        else: print(f" -> Falha no WhatsApp. Status: {resposta.status_code}")
    except Exception as e:
        print(f" -> Erro ao enviar WhatsApp: {e}")

def atualizar_financeiro():
    print("--- INICIANDO AUDITORIA MESTRE ---")
    
    print("[1/5] Conectando ao Google Sheets...")
    gc = gspread.service_account(filename=JSON_KEY)
    planilha = gc.open_by_url(SPREADSHEET_URL)
    aba_base = planilha.worksheet("Base de Dados")
    aba_metodo = planilha.worksheet("Metodologia Projetiva")
    
    sp_tz = pytz.timezone('America/Sao_Paulo')
    agora_sp = datetime.now(sp_tz).strftime('%d/%m %H:%M')
    
    print("[2/5] Baixando dados globais do Fundamentus...")
    try:
        url = "https://www.fundamentus.com.br/resultado.php"
        df = pd.read_html(io.StringIO(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).text), decimal=',', thousands='.')[0]
        df['Papel'] = df['Papel'].str.strip().str.upper()
        df = df.set_index('Papel')
        print(f" -> Sucesso: {len(df)} ativos encontrados no Fundamentus.")
    except Exception as e:
        print(f" -> ERRO CRÍTICO no Fundamentus: {e}")
        return

    print("[3/5] Triagem de Inteligência Artificial (Categorizando a fila)...")
    todas = aba_base.col_values(1)[1:]
    categorias = {'Fixas': [], 'Oportunidades': [], 'Metodologia': [], 'Aleatorias': []}
    
    # Metodologia (C3)
    ticker_c3 = str(aba_metodo.acell('C3').value).strip().upper()
    if ticker_c3 and ticker_c3 in todas:
        categorias['Metodologia'].append(ticker_c3)
        print(f" -> C3 identificada: {ticker_c3}")
    
    # Oportunidades (P/L > 0.1 evita distorções de lucro negativo)
    opps_brutas = df[(df['P/L'].astype(float) > 0.1) & (df['P/L'].astype(float) < 12) & (df['P/VP'].astype(float) < 1.5)].index.tolist()
    opps_validas = [o for o in opps_brutas if o in todas and o not in FIXAS and o != ticker_c3][:5]
    categorias['Oportunidades'] = opps_validas
    print(f" -> Oportunidades garimpadas: {opps_validas}")
    
    # Fixas
    categorias['Fixas'] = [f for f in FIXAS if f in todas]
    
    # Aleatórias (Evitando repetição)
    usadas = set(categorias['Fixas'] + categorias['Metodologia'] + categorias['Oportunidades'])
    disponiveis = [t for t in todas if t not in usadas]
    categorias['Aleatorias'] = random.sample(disponiveis, min(len(disponiveis), 3))
    print(f" -> Sorteio aleatório de manutenção: {categorias['Aleatorias']}")
    
    # Fila Consolidada
    fila = categorias['Fixas'] + categorias['Metodologia'] + categorias['Oportunidades'] + categorias['Aleatorias']
    print(f" -> TOTAL NA FILA: {len(fila)} ações.")

    print("\n[4/5] Processando cruzamento de dados (Yahoo + Fundamentus)...")
    batch_updates = []
    
    for ticker in fila:
        linha_idx = todas.index(ticker) + 2
        try:
            # Captura Yahoo Finance
            yf_info = yf.Ticker(f"{ticker}.SA").info
            preco = formatar(yf_info.get('currentPrice') or yf_info.get('regularMarketPrice'))
            n_acoes = formatar(yf_info.get('sharesOutstanding'))
            roa = formatar(yf_info.get('returnOnAssets'))
            peg_ratio = formatar(yf_info.get('trailingPegRatio') or yf_info.get('pegRatio'))
            valor_mercado = formatar(yf_info.get('marketCap'))
            vpa = formatar(yf_info.get('bookValue'))      # <--- NOVO GARIMPO
            lpa = formatar(yf_info.get('trailingEps'))    # <--- NOVO GARIMPO
            
            # Captura Fundamentus
            f = df.loc[ticker] if ticker in df.index else {}
            
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
                0, 0, 0,                                  # V, W, X 
                formatar(f.get('Cresc. Rec.5a', 0)),      # Y: CAGR Rec
                0,                                        # Z: CAGR Lucros 
                formatar(f.get('Liq.2meses', 0)),         # AA: Liq. Media
                vpa,                                      # AB: VPA (YF) <--- ADICIONADO
                lpa,                                      # AC: LPA (YF) <--- ADICIONADO
                peg_ratio,                                # AD: PEG Ratio (YF)
                valor_mercado,                            # AE: Valor Mercado (YF)
                f"{agora_sp} OK"                          # AF: Atualização
            ]
            batch_updates.append({'range': f'B{linha_idx}:AF{linha_idx}', 'values': [row]})
            print(f"   [OK] {ticker} processada. Preço: {preco}, VPA: {vpa}, LPA: {lpa}")
        except Exception as e:
            print(f"   [ERRO] Falha ao processar {ticker}: {e}")

    print("\n[5/5] Escrevendo lote no Google Sheets...")
    if batch_updates:
        aba_base.batch_update(batch_updates)
        print(f" -> Planilha atualizada perfeitamente ({len(batch_updates)} linhas).")
        
        # Só envia o WhatsApp se a planilha atualizar com sucesso
        enviar_whatsapp(categorias)
    else:
        print(" -> Nenhum dado para atualizar.")
        
    print("--- PROCESSO FINALIZADO ---")

if __name__ == "__main__":
    atualizar_financeiro()