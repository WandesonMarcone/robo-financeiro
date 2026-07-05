import gspread
import pandas as pd
import yfinance as yf
import requests
import io
import random
import pytz
import urllib.parse
import telebot 
from datetime import datetime
import os
import json

# --- CONFIGURAÇÕES DO SISTEMA ---
FIXAS = ["PETR4", "VALE3", "ITUB4", "BBDC4"] 
JSON_KEY = 'credenciais.json' 
SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk' 

# --- CONFIGURAÇÕES DE NOTIFICAÇÃO (API OFICIAL) ---
TELEGRAM_BOT_TOKEN = "7777811765:AAEk3XQibBBYSFKRfQLzOWs_KpGOcPFR274"
TELEGRAM_CHAT_ID = "8867098987"

def formatar(val):
    try: 
        if isinstance(val, str):
            is_percent = '%' in val 
            val = val.replace('%', '').replace('.', '').replace(',', '.')
            numero = float(val)
            return numero / 100 if is_percent else numero
        return float(val) if val is not None and not pd.isna(val) else 0.0
    except: return 0.0

# --- MÓDULO DE NOTIFICAÇÕES (TELEGRAM) ---
def disparar_alertas(msg):
    """Garante a entrega da notificação via Telegram."""
    if msg.strip() == "": return
    try:
        bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
        bot.send_message(TELEGRAM_CHAT_ID, msg, parse_mode='Markdown')
        print("📲 [Telegram] Notificação de ALERTA entregue com sucesso!")
    except Exception as e:
        print(f"⚠️ [Telegram] Erro de conexão: {e}")

# --- TRAVA DE 2 HORAS ---
def precisa_atualizar(ticker, mapa_atualizacao, agora_dt, sp_tz):
    if ticker not in mapa_atualizacao:
        return True # Se é ação nova, atualiza

    val = str(mapa_atualizacao[ticker]).strip()
    if 'OK' not in val:
        return True # Se a célula AG estiver vazia ou com erro, atualiza

    val = val.replace('OK', '').strip() 
    try:
        dia, resto = val.split('/')
        mes, horario = resto.split(' ')
        hora, minuto = horario.split(':')

        dt_af = datetime(agora_dt.year, int(mes), int(dia), int(hora), int(minuto))
        dt_af = sp_tz.localize(dt_af)
        if dt_af > agora_dt: 
            dt_af = dt_af.replace(year=agora_dt.year - 1)

        if (agora_dt - dt_af).total_seconds() < 7200:
            return False 
    except:
        pass 
    return True

def conectar_gspread():
    google_creds = os.environ.get('GOOGLE_CREDS')
    if google_creds:
        creds_dict = json.loads(google_creds)
        gc = gspread.service_account_from_dict(creds_dict)
    else:
        gc = gspread.service_account(filename=JSON_KEY)
    return gc

def atualizar_financeiro():
    print("🚀 INICIANDO AUDITORIA COM TRAVA DE 2 HORAS E MODO CAÇADOR SILENCIOSO 🚀")

    # Conexão
    print("[1/5] Conectando ao Google Sheets...")
    gc = conectar_gspread()
    planilha = gc.open_by_url(SPREADSHEET_URL) 

    sp_tz = pytz.timezone('America/Sao_Paulo')
    agora_dt = datetime.now(sp_tz)
    agora_sp = agora_dt.strftime('%d/%m %H:%M')

    aba_base = planilha.worksheet("BD_Acoes")
    aba_metodo = planilha.worksheet("Metodos_Acoes")
    aba_fiis = planilha.worksheet("BD_FIIs")

    # --- MÓDULO FIIs ---
    import module_fiis
    msg_fiis = module_fiis.atualizar_fiis(aba_fiis)
    # -------------------

    # 1. BUSCA DADOS FUNDAMENTUS
    print("[2/5] Baixando dados globais do Fundamentus...")
    try:
        url = "https://www.fundamentus.com.br/resultado.php"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers)
        df = pd.read_html(io.StringIO(response.text), decimal=',', thousands='.')[0]
        df['Papel'] = df['Papel'].str.strip().str.upper()
        df = df.set_index('Papel')
    except Exception as e:
        print(f"❌ Erro crítico ao buscar Fundamentus: {e}")
        return

    print("\n[3/5] Organizando a Fila (Aplicando Trava de Tempo)...")
    dados_planilha = aba_base.get_all_values()
    todas_originais = []
    mapa_atualizacao = {}

    for row in dados_planilha[1:]:
        if row and row[0].strip() and not row[0].replace(',', '').replace('.', '').isnumeric():
            t = row[0].strip().upper()
            todas_originais.append(t)
            mapa_atualizacao[t] = row[32] if len(row) > 32 else ""

    todas = list(todas_originais)
    df_filtros = df.copy()
    for col in ['P/L', 'P/VP', 'Div.Yield', 'ROE', 'Liq.2meses']:
        df_filtros[col] = df_filtros[col].apply(formatar)

    cat_fixas = [f for f in FIXAS if f in todas and precisa_atualizar(f, mapa_atualizacao, agora_dt, sp_tz)]
    
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

    # Oportunidades Reais 
    opps_brutas = df_filtros[(df_filtros['P/L'] > 0) & (df_filtros['P/L'] < 12) & (df_filtros['P/VP'] < 1.5) & (df_filtros['ROE'] >= 8.0)].index.tolist()
    cat_opps = [o for o in opps_brutas if o in todas_originais and o not in cat_fixas and o not in cat_metodologia and precisa_atualizar(o, mapa_atualizacao, agora_dt, sp_tz)][:5]

    # Modo Caçador 
    candidatas_prev = df_filtros[
        (df_filtros['P/L'] >= 2) & (df_filtros['P/L'] <= 15) &
        (df_filtros['P/VP'] >= 0.2) & (df_filtros['P/VP'] <= 1.5) &
        (df_filtros['Div.Yield'] >= 6.0) & (df_filtros['ROE'] >= 10.0) &      
        (df_filtros['Liq.2meses'] >= 2000000) 
    ].index.tolist()
    cat_novatas = [c for c in candidatas_prev if c not in todas][:2] 
    todas.extend(cat_novatas) 

    # Aleatórias
    usadas = set(cat_fixas + cat_metodologia + cat_opps + cat_novatas)
    precisam_urgente = [t for t in todas_originais if t not in usadas and precisa_atualizar(t, mapa_atualizacao, agora_dt, sp_tz)]
    cat_aleatorias = random.sample(precisam_urgente, 3) if len(precisam_urgente) >= 3 else precisam_urgente

    fila = cat_fixas + cat_metodologia + cat_opps + cat_aleatorias + cat_novatas

    print(f"-> Ações Fixas na Fila: {cat_fixas}")
    print(f"-> TOTAL PARA ATUALIZAR: {len(fila)} ações.\n")

    # 3. PROCESSAMENTO YAHOO FINANCE
    print("[4/5] Processando cruzamento de dados linha a linha...")
    batch_updates = []
    
    # ⚠️ O SEGREDO DO "SILÊNCIO": Só notificamos o que for VIP ou OPORTUNIDADE
    relatorio_opps_telegram = []
    relatorio_fixas_telegram = [] 
    relatorio_novatas_telegram = []

    for ticker in fila:
        linha_idx = todas.index(ticker) + 2
        try:
            yf_info = yf.Ticker(f"{ticker}.SA").info
            preco = formatar(yf_info.get('currentPrice') or yf_info.get('regularMarketPrice'))
            n_acoes = formatar(yf_info.get('sharesOutstanding')) 
            roa = formatar(yf_info.get('returnOnAssets'))        
            peg_ratio = formatar(yf_info.get('trailingPegRatio') or yf_info.get('pegRatio')) 
            valor_mercado = formatar(yf_info.get('marketCap'))   
            vpa = formatar(yf_info.get('bookValue'))             
            lpa = formatar(yf_info.get('trailingEps'))           

            setor_eng = yf_info.get('sector', 'N/D')
            traducao_setores = {'Energy': 'Energia', 'Financial Services': 'Financeiro', 'Basic Materials': 'Materiais Básicos', 'Utilities': 'Utilidade Pública', 'Industrials': 'Indústria', 'Consumer Defensive': 'Consumo Defensivo', 'Consumer Cyclical': 'Consumo Cíclico', 'Healthcare': 'Saúde', 'Technology': 'Tecnologia', 'Communication Services': 'Comunicações', 'Real Estate': 'Imobiliário'}
            setor = traducao_setores.get(setor_eng, setor_eng)

            f = df.loc[ticker] if ticker in df.index else {}

            row_base = [setor, preco, formatar(f.get('Div.Yield', 0)), n_acoes, formatar(f.get('P/L', 0)), formatar(f.get('P/VP', 0)), formatar(f.get('P/Ativo', 0)), formatar(f.get('Mrg Bruta', 0)), formatar(f.get('Mrg Ebit', 0)), formatar(f.get('Mrg. Líq.', 0)), formatar(f.get('P/EBIT', 0)), formatar(f.get('EV/EBIT', 0)), formatar(f.get('Dív.Líq/ Patrim.', 0)), formatar(f.get('Dív.Líq/ Patrim.', 0)), formatar(f.get('PSR', 0)), formatar(f.get('P/Cap.Giro', 0)), formatar(f.get('P/Ativ Circ.Liq', 0)), formatar(f.get('Liq. Corr.', 0)), formatar(f.get('ROE', 0)), roa, formatar(f.get('ROIC', 0)), 0, 0, 0, formatar(f.get('Cresc. Rec.5a', 0)), 0, formatar(f.get('Liq.2meses', 0)), vpa, lpa, peg_ratio, valor_mercado, f"{agora_sp} OK"]

            if ticker in cat_novatas or (ticker == ticker_c3 and c3_nova):
                row_final = [ticker] + row_base
                range_update = f'A{linha_idx}:AG{linha_idx}' 
            else:
                row_final = row_base
                range_update = f'B{linha_idx}:AG{linha_idx}' 

            batch_updates.append({'range': range_update, 'values': [row_final]})

            print(f"   ✅ [OK] {ticker} | Dados atualizados.")

            # SELEÇÃO PARA NOTIFICAR O TELEGRAM (A REGRA DE OURO)
            if ticker in opps_brutas:
                roe_wpp = formatar(f.get('ROE', 0)) * 100
                pl_wpp = formatar(f.get('P/L', 0))
                pvp_wpp = formatar(f.get('P/VP', 0))

                detalhe_msg = f"R$ {preco} | (P/L: {pl_wpp} | P/VP: {pvp_wpp})"

                # Se a Oportunidade for de uma das suas Fixas, alerta máximo
                if ticker in FIXAS:
                    relatorio_fixas_telegram.append(f"🟢 *Sinal Verde em {ticker}*\n   Preço: R$ {preco} | P/VP caiu para {pvp_wpp}\n   ROE Saudável de {roe_wpp:.1f}%")
                else:
                    relatorio_opps_telegram.append(f"• *{ticker}*: {detalhe_msg}")

            if ticker in cat_novatas:
                dy_wpp = formatar(f.get('Div.Yield', 0)) * 100
                relatorio_novatas_telegram.append(f"• *{ticker}*: R$ {preco} | 🏭 {setor} (DY: {dy_wpp:.1f}%)")

        except Exception as e:
            print(f"   ❌ [ERRO] Falha ao processar {ticker}: {e}")

    # 4. ESCRITA EM LOTE E NOTIFICAÇÃO SILENCIOSA
    print("\n[5/5] Salvando na Planilha e Disparando Notificações (Modo Oportunidade)...")
    msg_telegram = ""
    
    if msg_fiis: # Se o FII mudou muito e gritou, a gente repassa
        msg_telegram += msg_fiis 

    if batch_updates:
        aba_base.batch_update(batch_updates)
        print(f"💾 Sucesso: {len(batch_updates)} ações atualizadas na planilha.")

        # Só cria título se houver relatórios úteis
        if relatorio_fixas_telegram or relatorio_opps_telegram or relatorio_novatas_telegram:
            msg_telegram += "🤖 *Caçador de Ações* 🤖\n\n"

        if relatorio_fixas_telegram:
            msg_telegram += "🚨 *ALERTA VIP: SUAS AÇÕES FIXAS ESTÃO BARATAS* 🚨\n" + "\n".join(relatorio_fixas_telegram) + "\n\n"

        if relatorio_opps_telegram: 
            msg_telegram += "🎯 *Oportunidades do Mercado (P/VP < 1.5):*\n" + "\n".join(relatorio_opps_telegram) + "\n\n"

        if relatorio_novatas_telegram: 
            msg_telegram += "🌟 *NOVAS EMPRESAS CAÇADAS:*\n" + "\n".join(relatorio_novatas_telegram)

    # Dispara o alerta SÓ se o Caçador encontrou coisas relevantes
    if msg_telegram.strip():
        disparar_alertas(msg_telegram)
    else:
        print("✅ Planilha atualizada. (Sem Notificação: O mercado está em repouso e não há barganhas ativas).")

if __name__ == "__main__":
    atualizar_financeiro()