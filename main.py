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

# --- WHATSAPP CONFIG ---
TELEFONE_WHATSAPP = "553491503895" 
API_KEY_WHATSAPP = "5116767"

def formatar(val):
    try: 
        if isinstance(val, str):
            is_percent = '%' in val 
            val = val.replace('%', '').replace('.', '').replace(',', '.')
            numero = float(val)
            return numero / 100 if is_percent else numero
        return float(val) if val is not None and not pd.isna(val) else 0.0
    except: return 0.0

def enviar_whatsapp(msg):
    try:
        url = f"https://api.callmebot.com/whatsapp.php?phone={TELEFONE_WHATSAPP}&text={urllib.parse.quote(msg)}&apikey={API_KEY_WHATSAPP}"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            print("📲 Notificação enviada com sucesso no WhatsApp!")
    except Exception as e:
        print(f"⚠️ Falha de conexão com CallMeBot: {e}")

def atualizar_financeiro():
    print("🚀 INICIANDO AUDITORIA E MODO CAÇADOR 🚀")
    
    # Conexão
    print("[1/5] Conectando ao Google Sheets...")
    gc = gspread.service_account(filename=JSON_KEY)
    planilha = gc.open_by_url(SPREADSHEET_URL)
    aba_base = planilha.worksheet("Base de Dados")
    aba_metodo = planilha.worksheet("Metodologia Projetiva")
    
    # Horário de São Paulo
    sp_tz = pytz.timezone('America/Sao_Paulo')
    agora_sp = datetime.now(sp_tz).strftime('%d/%m %H:%M')
    
    # 1. BUSCA DADOS FUNDAMENTUS
    print("[2/5] Baixando dados globais do Fundamentus...")
    try:
        url = "https://www.fundamentus.com.br/resultado.php"
        df = pd.read_html(io.StringIO(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).text), decimal=',', thousands='.')[0]
        df['Papel'] = df['Papel'].str.strip().str.upper()
        df = df.set_index('Papel')
    except Exception as e:
        print(f"❌ Erro crítico ao buscar Fundamentus: {e}")
        return

    print("\n[3/5] Organizando a Fila de Prioridades e Caçando Novatas...")
    
    # IGNORA ERROS NA PLANILHA (Trava anti-números na Coluna A)
    coluna_a_bruta = aba_base.col_values(1)[1:]
    todas = [t.strip().upper() for t in coluna_a_bruta if t.strip() and not t.replace(',', '').replace('.', '').isnumeric()]
    todas_originais = set(todas) # Guarda quem já existia para não sortear espaço vazio
    
    # Prepara cópia do DF com os números limpos
    df_filtros = df.copy()
    for col in ['P/L', 'P/VP', 'Div.Yield', 'ROE', 'Liq.2meses']:
        df_filtros[col] = df_filtros[col].apply(formatar)
    
    # --- 2.1 Fixas ---
    cat_fixas = [f for f in FIXAS if f in todas]
    
    # --- 2.2 Metodologia (C3) com Inteligência de Adição ---
    ticker_c3 = str(aba_metodo.acell('C3').value).strip().upper()
    cat_metodologia = []
    c3_nova = False
    
    if ticker_c3 and ticker_c3 in df.index:
        if ticker_c3 not in cat_fixas:
            cat_metodologia = [ticker_c3]
        if ticker_c3 not in todas:
            c3_nova = True
            todas.append(ticker_c3) # Adiciona na lista para ganhar uma nova linha no final
    
    # --- 2.3 Oportunidades ---
    opps_brutas = df_filtros[(df_filtros['P/L'] > 0.1) & (df_filtros['P/L'] < 12) & (df_filtros['P/VP'] < 1.5)].index.tolist()
    cat_opps = [o for o in opps_brutas if o in todas_originais and o not in cat_fixas and o != ticker_c3][:5]
    
    # --- 2.4 Modo Caçador ---
    candidatas_prev = df_filtros[
        (df_filtros['P/L'] >= 2) & (df_filtros['P/L'] <= 15) &
        (df_filtros['P/VP'] >= 0.2) & (df_filtros['P/VP'] <= 1.5) &
        (df_filtros['Div.Yield'] >= 6.0) & 
        (df_filtros['ROE'] >= 10.0) &      
        (df_filtros['Liq.2meses'] >= 2000000) 
    ].index.tolist()
    cat_novatas = [c for c in candidatas_prev if c not in todas][:2] 
    todas.extend(cat_novatas) # Adiciona na memória para ganhar linha
    
    # --- 2.5 Aleatórias ---
    usadas = set(cat_fixas + cat_metodologia + cat_opps + cat_novatas)
    disponiveis = [t for t in todas_originais if t not in usadas]
    cat_aleatorias = random.sample(disponiveis, min(len(disponiveis), 3))
    
    # Junta todas
    fila = cat_fixas + cat_metodologia + cat_opps + cat_aleatorias + cat_novatas
    
    # Log Limpo do GitHub
    print(f"-> Ações Fixas: {cat_fixas}")
    if cat_metodologia: print(f"-> Metodologia (C3): {cat_metodologia} {'(Nova na planilha!)' if c3_nova else ''}")
    if cat_opps: print(f"-> Oportunidades garimpadas: {cat_opps}")
    if cat_novatas: print(f"-> 🌟 ALERTA CAÇADOR (Novas): {cat_novatas}")
    print(f"-> Sorteio aleatório de manutenção: {cat_aleatorias}")
    print(f"-> TOTAL NA FILA: {len(fila)} ações.\n")

    # 3. PROCESSAMENTO E CAPTURA YAHOO FINANCE
    print("[4/5] Processando cruzamento de dados linha a linha...")
    batch_updates = []
    relatorio_opps = []
    relatorio_novatas = []
    
    for ticker in fila:
        linha_idx = todas.index(ticker) + 2
        try:
            # Captura Yahoo
            yf_info = yf.Ticker(f"{ticker}.SA").info
            preco = formatar(yf_info.get('currentPrice') or yf_info.get('regularMarketPrice'))
            n_acoes = formatar(yf_info.get('sharesOutstanding')) 
            roa = formatar(yf_info.get('returnOnAssets'))        
            peg_ratio = formatar(yf_info.get('trailingPegRatio') or yf_info.get('pegRatio')) 
            valor_mercado = formatar(yf_info.get('marketCap'))   
            vpa = formatar(yf_info.get('bookValue'))             
            lpa = formatar(yf_info.get('trailingEps'))           
            
            # Captura Fundamentus
            f = df.loc[ticker] if ticker in df.index else {}
            
            # DADOS BASE RESTAURADOS (COLUNA B até AF)
            row_base = [
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
                formatar(f.get('Dív.Líq/ Patrim.', 0)),   # M: Div.Liq/Ebit (Aprox)
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
                vpa,                                      # AB: VPA (YF)
                lpa,                                      # AC: LPA (YF)
                peg_ratio,                                # AD: PEG Ratio (YF)
                valor_mercado,                            # AE: Valor Mercado (YF)
                f"{agora_sp} OK"                          # AF: Atualização
            ]
            
            # --- TRAVA DE SEGURANÇA E AUTO-ADIÇÃO ---
            if ticker in cat_novatas or (ticker == ticker_c3 and c3_nova):
                # É ação Nova (Caçador ou C3): Escreve da Coluna A até AF
                row_final = [ticker] + row_base
                range_update = f'A{linha_idx}:AF{linha_idx}'
            else:
                # Já existe na planilha: Escreve da Coluna B até AF
                row_final = row_base
                range_update = f'B{linha_idx}:AF{linha_idx}'
                
            batch_updates.append({'range': range_update, 'values': [row_final]})
            
            # Log Individual
            cat_atual = "Fixa" if ticker in cat_fixas else "Novata" if ticker in cat_novatas else "Metodologia" if ticker in cat_metodologia else "Oportunidade" if ticker in cat_opps else "Aleatória"
            print(f"   ✅ [OK] {ticker} ({cat_atual}) | Concluída com sucesso.")
            
            # WhatsApp Formatação
            if ticker in cat_opps:
                roe_wpp = formatar(f.get('ROE', 0)) * 100
                pl_wpp = formatar(f.get('P/L', 0))
                pvp_wpp = formatar(f.get('P/VP', 0))
                relatorio_opps.append(f"• *{ticker}*: R$ {preco} (P/L: {pl_wpp} | P/VP: {pvp_wpp} | ROE: {roe_wpp:.1f}%)")
            if ticker in cat_novatas:
                dy_wpp = formatar(f.get('Div.Yield', 0)) * 100
                roe_wpp = formatar(f.get('ROE', 0)) * 100
                relatorio_novatas.append(f"• *{ticker}*: R$ {preco} (DY: {dy_wpp:.1f}% | ROE: {roe_wpp:.1f}%)")
                
        except Exception as e:
            print(f"   ❌ [ERRO] Falha ao processar {ticker}: {e}")

    # 4. ESCRITA EM LOTE E NOTIFICAÇÃO
    print("\n[5/5] Salvando na Planilha...")
    if batch_updates:
        aba_base.batch_update(batch_updates)
        print(f"💾 Sucesso: {len(batch_updates)} ações atualizadas.")
        
        # Monta a mensagem final do WhatsApp
        msg_wpp = "🤖 *Relatório Mestre* 🤖\n\n"
        if cat_fixas: msg_wpp += f"📌 *Fixas:*\n{', '.join(cat_fixas)}\n\n"
        if cat_metodologia: 
            status_c3 = "(Adicionada na Planilha!)" if c3_nova else ""
            msg_wpp += f"🔍 *Metodologia (C3):*\n{', '.join(cat_metodologia)} {status_c3}\n\n"
        if cat_aleatorias: msg_wpp += f"🎲 *Aleatórias:*\n{', '.join(cat_aleatorias)}\n\n"
        if relatorio_opps: msg_wpp += "🎯 *Oportunidades Atualizadas:*\n" + "\n".join(relatorio_opps) + "\n\n"
        if relatorio_novatas: msg_wpp += "🌟 *NOVA PREVIDENCIÁRIA ADICIONADA:*\n" + "\n".join(relatorio_novatas)
        
        enviar_whatsapp(msg_wpp)
    else:
        print("⚠️ Sem dados para atualizar.")

    print("\n🏁 --- PROCESSO FINALIZADO --- 🏁")

if __name__ == "__main__":
    atualizar_financeiro()