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

def enviar_whatsapp(msg):
    try:
        url = f"https://api.callmebot.com/whatsapp.php?phone={TELEFONE_WHATSAPP}&text={urllib.parse.quote(msg)}&apikey={API_KEY_WHATSAPP}"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            print("📲 Notificação enviada com sucesso no WhatsApp!")
        else:
            print(f"⚠️ Erro ao enviar WhatsApp. Código: {res.status_code}")
    except Exception as e:
        print(f"⚠️ Falha de conexão com CallMeBot: {e}")

# --- TRAVA DE 2 HORAS (TOTAL) ---
def precisa_atualizar(ticker, mapa_atualizacao, agora_dt, sp_tz):
    if ticker not in mapa_atualizacao:
        return True # Se é ação nova, atualiza

    val = str(mapa_atualizacao[ticker]).strip()
    if 'OK' not in val:
        return True # Se a célula AF estiver vazia ou com erro, atualiza

    val = val.replace('OK', '').strip() # Limpa para ficar só "03/07 08:34"
    try:
        dia, resto = val.split('/')
        mes, horario = resto.split(' ')
        hora, minuto = horario.split(':')

        # Reconstrói a data lida da planilha
        dt_af = datetime(agora_dt.year, int(mes), int(dia), int(hora), int(minuto))
        dt_af = sp_tz.localize(dt_af)

        # Correção de virada de ano
        if dt_af > agora_dt: 
            dt_af = dt_af.replace(year=agora_dt.year - 1)

        # Calcula a diferença em segundos (7200 segundos = 2 horas)
        if (agora_dt - dt_af).total_seconds() < 7200:
            return False # Trava Ativada! Atualizada há menos de 2h
    except:
        pass # Se der erro ao ler a data, atualiza por segurança

    return True

def atualizar_financeiro():
    print("🚀 INICIANDO AUDITORIA COM TRAVA TOTAL E MODO CAÇADOR 🚀")
    
    # Conexão
    print("[1/5] Conectando ao Google Sheets...")
    gc = gspread.service_account(filename=JSON_KEY)
    planilha = gc.open_by_url(SPREADSHEET_URL)
    aba_base = planilha.worksheet("Base de Dados")
    aba_metodo = planilha.worksheet("Metodologia Projetiva")
    
    # Horário de São Paulo
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
        print(f"✅ Sucesso: {len(df)} ativos mapeados do Fundamentus.")
    except Exception as e:
        print(f"❌ Erro crítico ao buscar Fundamentus: {e}")
        return

    # Preparação para Trava: Leitura de todos os horários da coluna AF
    dados_planilha = aba_base.get_all_values()
    mapa_atualizacao = {}
    for row in dados_planilha[1:]: # Pula cabeçalho
        if row and row[0].strip() and not row[0].replace(',', '').replace('.', '').isnumeric():
            ticker_linha = row[0].strip().upper()
            # A Coluna AF é a 32ª coluna (índice 31)
            mapa_atualizacao[ticker_linha] = row[31] if len(row) > 31 else ""

    print("\n[3/5] Organizando a Fila de Prioridades (Inteligência 4-em-1)...")
    
    todas = aba_base.col_values(1)[1:]
    
    # --- 2.1 Fixas (Com Trava) ---
    cat_fixas = [f for f in FIXAS if f in todas and precisa_atualizar(f, mapa_atualizacao, agora_dt, sp_tz)]
    
    # --- 2.2 Metodologia (C3) (Com Trava) ---
    ticker_c3 = str(aba_metodo.acell('C3').value).strip().upper()
    cat_metodologia = [ticker_c3] if ticker_c3 and ticker_c3 in todas and precisa_atualizar(ticker_c3, mapa_atualizacao, agora_dt, sp_tz) and ticker_c3 not in cat_fixas else []
    
    # --- 2.3 Oportunidades (Com Trava) ---
    opps_brutas = df[(df['P/L'].astype(float) > 0.1) & (df['P/L'].astype(float) < 12) & (df['P/VP'].astype(float) < 1.5)].index.tolist()
    cat_opps = [o for o in opps_brutas if o in todas and o not in FIXAS and o != ticker_c3 and precisa_atualizar(o, mapa_atualizacao, agora_dt, sp_tz)][:5]
    
    # --- 2.4 MODO CAÇADOR (Novas Ações) ---
    df_filtros = df.copy()
    for col in ['P/L', 'P/VP', 'Div.Yield', 'ROE', 'Liq.2meses']:
        df_filtros[col] = df_filtros[col].apply(formatar)
    
    candidatas_prev = df_filtros[
        (df_filtros['P/L'] >= 2) & (df_filtros['P/L'] <= 15) &
        (df_filtros['P/VP'] >= 0.2) & (df_filtros['P/VP'] <= 1.5) &
        (df_filtros['Div.Yield'] >= 6.0) & 
        (df_filtros['ROE'] >= 10.0) &      
        (df_filtros['Liq.2meses'] >= 2000000) 
    ].index.tolist()
    
    # Novas que ainda não estão na planilha (Essas passam pela trava automaticamente)
    cat_novatas = [c for c in candidatas_prev if c not in todas][:2] 
    
    # --- 2.5 Aleatórias (Com Trava Total) ---
    usadas = set(cat_fixas + cat_metodologia + cat_opps + cat_novatas)
    disponiveis = [t for t in todas if t not in usadas and precisa_atualizar(t, mapa_atualizacao, agora_dt, sp_tz)]
    cat_aleatorias = random.sample(disponiveis, min(len(disponiveis), 3))
    
    # Junta todas
    fila = cat_fixas + cat_metodologia + cat_opps + cat_aleatorias + cat_novatas
    print(f"📋 Fila montada com {len(fila)} ativos: {fila}")

    # 3. PROCESSAMENTO E CAPTURA YAHOO FINANCE
    print("\n[4/5] Processando cruzamento de dados linha a linha...")
    batch_updates = []
    relatorio_opps = []
    relatorio_novatas = []
    
    for ticker in fila:
        linha_idx = todas.index(ticker) + 2 if ticker in todas else -1
        try:
            # 3.1 - YFINANCE
            yf_info = yf.Ticker(f"{ticker}.SA").info
            preco = formatar(yf_info.get('currentPrice') or yf_info.get('regularMarketPrice'))
            n_acoes = formatar(yf_info.get('sharesOutstanding'))
            roa = formatar(yf_info.get('returnOnAssets'))
            peg_ratio = formatar(yf_info.get('trailingPegRatio') or yf_info.get('pegRatio'))
            valor_mercado = formatar(yf_info.get('marketCap'))
            vpa = formatar(yf_info.get('bookValue'))
            lpa = formatar(yf_info.get('trailingEps'))
            
            # 3.2 - FUNDAMENTUS (Base)
            f = df.loc[ticker] if ticker in df.index else {}
            
            row = [
                preco, formatar(f.get('Div.Yield', 0)), n_acoes, formatar(f.get('P/L', 0)),
                formatar(f.get('P/VP', 0)), formatar(f.get('P/Ativo', 0)), formatar(f.get('Mrg Bruta', 0)),
                formatar(f.get('Mrg Ebit', 0)), formatar(f.get('Mrg. Líq.', 0)), formatar(f.get('P/EBIT', 0)),
                formatar(f.get('EV/EBIT', 0)), formatar(f.get('Dív.Líq/ Patrim.', 0)), formatar(f.get('Dív.Líq/ Patrim.', 0)),
                formatar(f.get('PSR', 0)), formatar(f.get('P/Cap.Giro', 0)), formatar(f.get('P/Ativ Circ.Liq', 0)),
                formatar(f.get('Liq. Corr.', 0)), formatar(f.get('ROE', 0)), roa, formatar(f.get('ROIC', 0)),
                0, 0, 0, formatar(f.get('Cresc. Rec.5a', 0)), 0, formatar(f.get('Liq.2meses', 0)),
                vpa, lpa, peg_ratio, valor_mercado, f"{agora_sp} OK"
            ]

            if ticker in cat_novatas:
                # Adiciona nova linha no final da base
                aba_base.append_row([ticker] + row)
            else:
                batch_updates.append({'range': f'B{linha_idx}:AF{linha_idx}', 'values': [row]})
            
            # Logs
            cat_atual = "Fixa" if ticker in cat_fixas else "Metodologia" if ticker in cat_metodologia else "Oportunidade" if ticker in cat_opps else "Novata" if ticker in cat_novatas else "Aleatória"
            print(f"   ✅ [OK] {ticker} ({cat_atual}) | Concluída.")
            
            if ticker in cat_opps:
                relatorio_opps.append(f"• *{ticker}*: R$ {preco} (P/L: {formatar(f.get('P/L', 0))} | P/VP: {formatar(f.get('P/VP', 0))} | ROE: {formatar(f.get('ROE', 0))*100:.1f}%)")
            
            if ticker in cat_novatas:
                dy_fmt = formatar(f.get('Div.Yield', 0)) * 100
                roe_fmt = formatar(f.get('ROE', 0)) * 100
                relatorio_novatas.append(f"• *{ticker}*: R$ {preco} (DY: {dy_fmt:.1f}% | ROE: {roe_fmt:.1f}%)")
                
        except Exception as e:
            print(f"   ❌ [ERRO] Falha ao processar {ticker}: {e}")

    # 4. ESCRITA EM LOTE E NOTIFICAÇÃO
    print("\n[5/5] Escrevendo lote no Google Sheets e Notificando...")
    if batch_updates:
        aba_base.batch_update(batch_updates)
    
    if batch_updates or cat_novatas:
        msg_wpp = "🤖 *Relatório de Atualização Mestre* 🤖\n\n"
        if cat_fixas: msg_wpp += f"📌 *Fixas:* {', '.join(cat_fixas)}\n\n"
        if cat_metodologia: msg_wpp += f"🔍 *Metodologia (C3):*\n{', '.join(cat_metodologia)}\n\n"
        if cat_aleatorias: msg_wpp += f"🎲 *Atualização Aleatória:* {', '.join(cat_aleatorias)}\n\n"
        if relatorio_opps: msg_wpp += "🎯 *Oportunidades:*\n" + "\n".join(relatorio_opps) + "\n\n"
        if relatorio_novatas: msg_wpp += "🌟 *NOVA PREVIDENCIÁRIA ADICIONADA:*\n" + "\n".join(relatorio_novatas)
        
        enviar_whatsapp(msg_wpp)
    else:
        print("⚠️ Nenhum dado para atualizar nesta rodada.")

    print("\n🏁 --- PROCESSO FINALIZADO --- 🏁")

if __name__ == "__main__":
    atualizar_financeiro()