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

# --- TRAVA DE 2 HORAS ---
def precisa_atualizar(ticker, mapa_atualizacao, agora_dt, sp_tz):
    if ticker not in mapa_atualizacao: return True
    val = str(mapa_atualizacao[ticker]).strip()
    if 'OK' not in val: return True
    val = val.replace('OK', '').strip()
    try:
        dia, resto = val.split('/')
        mes, horario = resto.split(' ')
        hora, minuto = horario.split(':')
        dt_af = datetime(agora_dt.year, int(mes), int(dia), int(hora), int(minuto))
        dt_af = sp_tz.localize(dt_af)
        if dt_af > agora_dt: dt_af = dt_af.replace(year=agora_dt.year - 1)
        if (agora_dt - dt_af).total_seconds() < 7200: return False
    except: pass
    return True

def atualizar_financeiro():
    print("🚀 INICIANDO AUDITORIA (TRAVA TOTAL ATIVADA) 🚀")
    
    # Conexão
    print("[1/5] Conectando ao Google Sheets...")
    gc = gspread.service_account(filename=JSON_KEY)
    planilha = gc.open_by_url(SPREADSHEET_URL)
    aba_base = planilha.worksheet("Base de Dados")
    aba_metodo = planilha.worksheet("Metodologia Projetiva")
    
    sp_tz = pytz.timezone('America/Sao_Paulo')
    agora_dt = datetime.now(sp_tz)
    agora_sp = agora_dt.strftime('%d/%m %H:%M')
    
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

    print("\n[3/5] Organizando a Fila (Aplicando Trava de 2h Total)...")
    
    dados_planilha = aba_base.get_all_values()
    todas_originais = []
    mapa_atualizacao = {}
    for row in dados_planilha[1:]:
        if row and row[0].strip() and not row[0].replace(',', '').replace('.', '').isnumeric():
            t = row[0].strip().upper()
            todas_originais.append(t)
            mapa_atualizacao[t] = row[31] if len(row) > 31 else ""
            
    todas = list(todas_originais)
    df_filtros = df.copy()
    for col in ['P/L', 'P/VP', 'Div.Yield', 'ROE', 'Liq.2meses']:
        df_filtros[col] = df_filtros[col].apply(formatar)
    
    # --- FILTRAGEM COM TRAVA TOTAL ---
    # Fixas (Passam pela trava)
    cat_fixas = [f for f in FIXAS if f in todas and precisa_atualizar(f, mapa_atualizacao, agora_dt, sp_tz)]
    
    # Metodologia (Passam pela trava)
    ticker_c3 = str(aba_metodo.acell('C3').value).strip().upper()
    cat_metodologia = []
    c3_nova = False
    if ticker_c3 and ticker_c3 in df.index:
        if ticker_c3 not in todas:
            c3_nova = True
            todas.append(ticker_c3)
            cat_metodologia = [ticker_c3]
        elif precisa_atualizar(ticker_c3, mapa_atualizacao, agora_dt, sp_tz) and ticker_c3 not in cat_fixas:
            cat_metodologia = [ticker_c3]
            
    # Oportunidades (Passam pela trava)
    opps_brutas = df_filtros[(df_filtros['P/L'] > 0.1) & (df_filtros['P/L'] < 12) & (df_filtros['P/VP'] < 1.5)].index.tolist()
    cat_opps = [o for o in opps_brutas if o in todas_originais and o not in cat_fixas and o not in cat_metodologia and precisa_atualizar(o, mapa_atualizacao, agora_dt, sp_tz)][:5]
    
    # Modo Caçador (Não possuem tempo de atualização ainda, logo passam)
    candidatas_prev = df_filtros[
        (df_filtros['P/L'] >= 2) & (df_filtros['P/L'] <= 15) &
        (df_filtros['P/VP'] >= 0.2) & (df_filtros['P/VP'] <= 1.5) &
        (df_filtros['Div.Yield'] >= 6.0) & (df_filtros['ROE'] >= 10.0) & (df_filtros['Liq.2meses'] >= 2000000) 
    ].index.tolist()
    cat_novatas = [c for c in candidatas_prev if c not in todas][:2]
    todas.extend(cat_novatas)
    
    # Aleatórias (Passam pela trava)
    usadas = set(cat_fixas + cat_metodologia + cat_opps + cat_novatas)
    precisam_urgente = [t for t in todas_originais if t not in usadas and precisa_atualizar(t, mapa_atualizacao, agora_dt, sp_tz)]
    if len(precisam_urgente) >= 3: cat_aleatorias = random.sample(precisam_urgente, 3)
    else: 
        cat_aleatorias = precisam_urgente
        resto = [t for t in todas_originais if t not in usadas and t not in cat_aleatorias]
        cat_aleatorias += random.sample(resto, min(3 - len(cat_aleatorias), len(resto)))
    
    fila = cat_fixas + cat_metodologia + cat_opps + cat_aleatorias + cat_novatas
    print(f"-> TOTAL PARA ATUALIZAR: {len(fila)} ações.\n")

    # 4. PROCESSAMENTO
    batch_updates = []
    relatorio_opps = []
    relatorio_novatas = []
    
    for ticker in fila:
        linha_idx = todas.index(ticker) + 2
        try:
            yf_info = yf.Ticker(f"{ticker}.SA").info
            preco = formatar(yf_info.get('currentPrice') or yf_info.get('regularMarketPrice'))
            f = df.loc[ticker] if ticker in df.index else {}
            
            row_base = [
                preco, formatar(f.get('Div.Yield', 0)), formatar(yf_info.get('sharesOutstanding')),
                formatar(f.get('P/L', 0)), formatar(f.get('P/VP', 0)), formatar(f.get('P/Ativo', 0)),
                formatar(f.get('Mrg Bruta', 0)), formatar(f.get('Mrg Ebit', 0)), formatar(f.get('Mrg. Líq.', 0)),
                formatar(f.get('P/EBIT', 0)), formatar(f.get('EV/EBIT', 0)), formatar(f.get('Dív.Líq/ Patrim.', 0)),
                formatar(f.get('Dív.Líq/ Patrim.', 0)), formatar(f.get('PSR', 0)), formatar(f.get('P/Cap.Giro', 0)),
                formatar(f.get('P/Ativ Circ.Liq', 0)), formatar(f.get('Liq. Corr.', 0)), formatar(f.get('ROE', 0)),
                formatar(yf_info.get('returnOnAssets')), formatar(f.get('ROIC', 0)), 0, 0, 0,
                formatar(f.get('Cresc. Rec.5a', 0)), 0, formatar(f.get('Liq.2meses', 0)),
                formatar(yf_info.get('bookValue')), formatar(yf_info.get('trailingEps')),
                formatar(yf_info.get('trailingPegRatio') or yf_info.get('pegRatio')),
                formatar(yf_info.get('marketCap')), f"{agora_sp} OK"
            ]
            
            if ticker in cat_novatas or (ticker == ticker_c3 and c3_nova):
                batch_updates.append({'range': f'A{linha_idx}:AF{linha_idx}', 'values': [[ticker] + row_base]})
            else:
                batch_updates.append({'range': f'B{linha_idx}:AF{linha_idx}', 'values': [row_base]})
            
            print(f"   ✅ [OK] {ticker} | Concluída.")
            
            if ticker in opps_brutas:
                relatorio_opps.append(f"• *{ticker}*: R$ {preco} (P/L: {formatar(f.get('P/L', 0))} | P/VP: {formatar(f.get('P/VP', 0))} | ROE: {formatar(f.get('ROE', 0))*100:.1f}%)")
            if ticker in cat_novatas:
                relatorio_novatas.append(f"• *{ticker}*: R$ {preco} (DY: {formatar(f.get('Div.Yield', 0))*100:.1f}% | ROE: {formatar(f.get('ROE', 0))*100:.1f}%)")
        except Exception as e:
            print(f"   ❌ [ERRO] {ticker}: {e}")

    # 5. SALVAMENTO
    if batch_updates:
        aba_base.batch_update(batch_updates)
        msg_wpp = "🤖 *Relatório Mestre* 🤖\n\n"
        if cat_fixas: msg_wpp += f"📌 *Fixas:* {', '.join(cat_fixas)}\n\n"
        if relatorio_opps: msg_wpp += "🎯 *Oportunidades:*\n" + "\n".join(relatorio_opps) + "\n\n"
        if relatorio_novatas: msg_wpp += "🌟 *Novas:* \n" + "\n".join(relatorio_novatas)
        enviar_whatsapp(msg_wpp)
    else:
        print("✅ Tudo atualizado! Nada a processar.")

if __name__ == "__main__":
    atualizar_financeiro()