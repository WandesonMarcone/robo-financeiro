import gspread
import pandas as pd
import yfinance as yf
import requests
import io
import random
import pytz
import urllib.parse
import module_macro
import telebot # Necessário instalar: pip install pyTelegramBotAPI
from datetime import datetime

# --- CONFIGURAÇÕES DO SISTEMA ---
FIXAS = ["PETR4", "VALE3", "ITUB4", "BBDC4"] 
JSON_KEY = 'credenciais.json' 
SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk' 

# --- CONFIGURAÇÕES DE NOTIFICAÇÃO (API OFICIAL) ---
# 1. Telegram
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
def enviar_telegram(msg):
    try:
        bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
        bot.send_message(TELEGRAM_CHAT_ID, msg, parse_mode='Markdown')
        print("📲 [Telegram] Notificação entregue com sucesso!")
    except Exception as e:
        print(f"⚠️ [Telegram] Erro de conexão: {e}")

def disparar_alertas(msg):
    """Garante a entrega da notificação via Telegram."""
    enviar_telegram(msg)

# --- TRAVA DE 2 HORAS ---
def precisa_atualizar(ticker, mapa_atualizacao, agora_dt, sp_tz):
    if ticker not in mapa_atualizacao:
        return True # Se é ação nova, atualiza

    val = str(mapa_atualizacao[ticker]).strip()
    if 'OK' not in val:
        return True # Se a célula AG estiver vazia ou com erro, atualiza

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
    print("🚀 INICIANDO AUDITORIA COM TRAVA DE 2 HORAS E MODO CAÇADOR 🚀")

    # Conexão
    print("[1/5] Conectando ao Google Sheets...")
    gc = gspread.service_account(filename=JSON_KEY)
    planilha = gc.open_by_url(SPREADSHEET_URL) 

    # Horário de São Paulo
    sp_tz = pytz.timezone('America/Sao_Paulo')
    agora_dt = datetime.now(sp_tz)
    agora_sp = agora_dt.strftime('%d/%m %H:%M')
    hora_atual = agora_dt.hour

    # --- MÓDULO MACRO (Abertura 11h e Fechamento 19h) ---
    aba_macro = planilha.worksheet("BD_Macro")
    import module_macro

    msg_macro = ""
    # O robô vai verificar que horas são. Adicionado o 0 (meia-noite) para você testar agora.
    if hora_atual in [1, 11, 19]:
        msg_macro = module_macro.atualizar_macro(aba_macro)
    else:
        print(f"⏸️ [MACRO] Fora do horário de pregão ({hora_atual}h). Macro não será atualizado agora.")
    # ----------------------------------------------------

    aba_base = planilha.worksheet("BD_Acoes")
    aba_metodo = planilha.worksheet("Metodos_Acoes")

    # 1. BUSCA DADOS FUNDAMENTUS
    print("[2/5] Baixando dados globais do Fundamentus...")
    try:
        url = "https://www.fundamentus.com.br/resultado.php"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers)
        df = pd.read_html(io.StringIO(response.text), decimal=',', thousands='.')[0]

        df['Papel'] = df['Papel'].str.strip().str.upper()
        df = df.set_index('Papel')
    except Exception as e:
        print(f"❌ Erro crítico ao buscar Fundamentus: {e}")
        return

    print("\n[3/5] Organizando a Fila (Aplicando Trava de Tempo)...")

    # Lê a planilha inteira de uma vez (Mais rápido e mapeia a Coluna A e AG juntas)
    dados_planilha = aba_base.get_all_values()
    todas_originais = []
    mapa_atualizacao = {}

    for row in dados_planilha[1:]: # Pula cabeçalho
        if row and row[0].strip() and not row[0].replace(',', '').replace('.', '').isnumeric():
            t = row[0].strip().upper()
            todas_originais.append(t)
            # A Coluna AG agora é a 33ª (índice 32)
            mapa_atualizacao[t] = row[32] if len(row) > 32 else ""

    todas = list(todas_originais) # Cópia para trabalhar

    df_filtros = df.copy()
    for col in ['P/L', 'P/VP', 'Div.Yield', 'ROE', 'Liq.2meses']:
        df_filtros[col] = df_filtros[col].apply(formatar)

    # --- 2.1 Fixas (Só entram se a Trava de 2h permitir) ---
    cat_fixas = [f for f in FIXAS if f in todas and precisa_atualizar(f, mapa_atualizacao, agora_dt, sp_tz)]
    fixas_travadas = [f for f in FIXAS if f in todas and f not in cat_fixas]
    if fixas_travadas: print(f"🔒 TRAVA ATIVADA: Ignorando {fixas_travadas} (Atualizadas há menos de 2h)")

    # --- 2.2 Metodologia (C3) ---
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

    # --- 2.3 Oportunidades Reais --- PL > 0 E < 12 / P/VP < 1.5 / ROE >= 8.0 (Filtro Antilixo)
    opps_brutas = df_filtros[(df_filtros['P/L'] > 0) & (df_filtros['P/L'] < 12) & (df_filtros['P/VP'] < 1.5) & (df_filtros['ROE'] >= 8.0)].index.tolist()
    # Pega apenas as que precisam de atualização e não estão nas categorias acima
    cat_opps = [o for o in opps_brutas if o in todas_originais and o not in cat_fixas and o not in cat_metodologia and precisa_atualizar(o, mapa_atualizacao, agora_dt, sp_tz)][:5]

    # --- 2.4 Modo Caçador ---
    candidatas_prev = df_filtros[
        (df_filtros['P/L'] >= 2) & (df_filtros['P/L'] <= 15) &
        (df_filtros['P/VP'] >= 0.2) & (df_filtros['P/VP'] <= 1.5) &
        (df_filtros['Div.Yield'] >= 6.0) & 
        (df_filtros['ROE'] >= 10.0) &      
        (df_filtros['Liq.2meses'] >= 2000000) 
    ].index.tolist()
    cat_novatas = [c for c in candidatas_prev if c not in todas][:2] 
    todas.extend(cat_novatas) 

    # --- 2.5 Aleatórias (Prioriza quem não atualiza há muito tempo) ---
    usadas = set(cat_fixas + cat_metodologia + cat_opps + cat_novatas)
    precisam_urgente = [t for t in todas_originais if t not in usadas and precisa_atualizar(t, mapa_atualizacao, agora_dt, sp_tz)]

    if len(precisam_urgente) >= 3:
        cat_aleatorias = random.sample(precisam_urgente, 3)
    else:
        cat_aleatorias = precisam_urgente

    fila = cat_fixas + cat_metodologia + cat_opps + cat_aleatorias + cat_novatas

    # Log Limpo do GitHub
    print(f"-> Ações Fixas na Fila: {cat_fixas}")
    if cat_metodologia: print(f"-> Metodologia (C3): {cat_metodologia} {'(Nova!)' if c3_nova else ''}")
    if cat_opps: print(f"-> Oportunidades garimpadas: {cat_opps}")
    if cat_novatas: print(f"-> 🌟 ALERTA CAÇADOR (Novas): {cat_novatas}")
    print(f"-> Varredura de Desatualizadas: {cat_aleatorias}")
    print(f"-> TOTAL PARA ATUALIZAR: {len(fila)} ações.\n")

    # 3. PROCESSAMENTO E CAPTURA YAHOO FINANCE
    print("[4/5] Processando cruzamento de dados linha a linha...")
    batch_updates = []
    relatorio_opps = []
    relatorio_novatas = []
    relatorio_fixas_opps = [] # LISTA VIP

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

            # Buscando e traduzindo o Setor no Yahoo Finance
            setor_eng = yf_info.get('sector', 'N/D')
            traducao_setores = {
                'Energy': 'Energia', 'Financial Services': 'Financeiro', 'Basic Materials': 'Materiais Básicos', 
                'Utilities': 'Utilidade Pública', 'Industrials': 'Indústria', 'Consumer Defensive': 'Consumo Defensivo', 
                'Consumer Cyclical': 'Consumo Cíclico', 'Healthcare': 'Saúde', 'Technology': 'Tecnologia', 
                'Communication Services': 'Comunicações', 'Real Estate': 'Imobiliário'
            }
            setor = traducao_setores.get(setor_eng, setor_eng)

            f = df.loc[ticker] if ticker in df.index else {}

            row_base = [
                setor,                                    # B: Setor (NEW)
                preco,                                    # C: Preço (YF)
                formatar(f.get('Div.Yield', 0)),          # D: DY
                n_acoes,                                  # E: Nº Ações (YF)
                formatar(f.get('P/L', 0)),                # F: P/L
                formatar(f.get('P/VP', 0)),               # G: P/VP
                formatar(f.get('P/Ativo', 0)),            # H: P/Ativo
                formatar(f.get('Mrg Bruta', 0)),          # I: Marg. Bruta
                formatar(f.get('Mrg Ebit', 0)),           # J: Marg. EBIT
                formatar(f.get('Mrg. Líq.', 0)),          # K: Marg. Líq.
                formatar(f.get('P/EBIT', 0)),             # L: P/EBIT
                formatar(f.get('EV/EBIT', 0)),            # M: EV/EBIT
                formatar(f.get('Dív.Líq/ Patrim.', 0)),   # N: Div.Liq/Ebit
                formatar(f.get('Dív.Líq/ Patrim.', 0)),   # O: Div.Liq/Patri
                formatar(f.get('PSR', 0)),                # P: PSR
                formatar(f.get('P/Cap.Giro', 0)),         # Q: P/Cap.Giro
                formatar(f.get('P/Ativ Circ.Liq', 0)),    # R: P.At.Circ.Liq
                formatar(f.get('Liq. Corr.', 0)),         # S: Liq. Corr
                formatar(f.get('ROE', 0)),                # T: ROE
                roa,                                      # U: ROA (YF)
                formatar(f.get('ROIC', 0)),               # V: ROIC
                0, 0, 0,                                  # W, X, Y
                formatar(f.get('Cresc. Rec.5a', 0)),      # Z: CAGR Rec
                0,                                        # AA: CAGR Lucros
                formatar(f.get('Liq.2meses', 0)),         # AB: Liq. Media
                vpa,                                      # AC: VPA (YF)
                lpa,                                      # AD: LPA (YF)
                peg_ratio,                                # AE: PEG Ratio (YF)
                valor_mercado,                            # AF: Valor Mercado (YF)
                f"{agora_sp} OK"                          # AG: Atualização
            ]

            if ticker in cat_novatas or (ticker == ticker_c3 and c3_nova):
                row_final = [ticker] + row_base
                range_update = f'A{linha_idx}:AG{linha_idx}' 
            else:
                row_final = row_base
                range_update = f'B{linha_idx}:AG{linha_idx}' 

            batch_updates.append({'range': range_update, 'values': [row_final]})

            cat_atual = "Fixa" if ticker in cat_fixas else "Novata" if ticker in cat_novatas else "Metodologia" if ticker in cat_metodologia else "Oportunidade" if ticker in cat_opps else "Aleatória"

            tag_extra = ""
            if ticker in opps_brutas:
                if ticker in FIXAS: tag_extra = " (Ação Fixa)"
                elif ticker == ticker_c3: tag_extra = " (C3)"

            log_print = f"{cat_atual} / Oportunidade" if tag_extra else cat_atual
            print(f"   ✅ [OK] {ticker} ({log_print}) | Concluída com sucesso.")

            if ticker in opps_brutas:
                roe_wpp = formatar(f.get('ROE', 0)) * 100
                pl_wpp = formatar(f.get('P/L', 0))
                pvp_wpp = formatar(f.get('P/VP', 0))

                detalhe_msg = f"R$ {preco} | 🏢 {setor} (P/L: {pl_wpp} | P/VP: {pvp_wpp} | ROE: {roe_wpp:.1f}%)"

                if ticker in FIXAS:
                    relatorio_fixas_opps.append(f"• *{ticker}* está barata!\n   Motivo: P/L ({pl_wpp}) abaixo de 12, P/VP ({pvp_wpp}) abaixo de 1.5 e ROE ({roe_wpp:.1f}%) Saudável.\n   🏢 Setor: {setor}")

                relatorio_opps.append(f"• *{ticker}*{tag_extra}: {detalhe_msg}")

            if ticker in cat_novatas:
                dy_wpp = formatar(f.get('Div.Yield', 0)) * 100
                roe_wpp = formatar(f.get('ROE', 0)) * 100
                relatorio_novatas.append(f"• *{ticker}*: R$ {preco} | 🏢 {setor} (DY: {dy_wpp:.1f}% | ROE: {roe_wpp:.1f}%)")

        except Exception as e:
            print(f"   ❌ [ERRO] Falha ao processar {ticker}: {e}")

    # 4. ESCRITA EM LOTE E NOTIFICAÇÃO
    print("\n[5/5] Salvando na Planilha e Disparando Notificações...")
    
    # Prepara a mensagem final
    msg_telegram = ""
    if msg_macro:
        msg_telegram += msg_macro # Adiciona o macro no topo, se houver

    if batch_updates:
        aba_base.batch_update(batch_updates)
        print(f"💾 Sucesso: {len(batch_updates)} ações atualizadas na planilha.")

        msg_telegram += "🤖 *Relatório de Ações* 🤖\n\n"

        if relatorio_fixas_opps:
            msg_telegram += "🚨 *ALERTA VIP: AÇÕES FIXAS EM OPORTUNIDADE* 🚨\n" + "\n".join(relatorio_fixas_opps) + "\n\n"

        if cat_fixas: msg_telegram += f"📌 *Fixas Processadas:*\n{', '.join(cat_fixas)}\n\n"

        if cat_metodologia: 
            status_c3 = "(Adicionada na Planilha!)" if c3_nova else ""
            msg_telegram += f"🔍 *Metodologia (C3):*\n{', '.join(cat_metodologia)} {status_c3}\n\n"

        if cat_aleatorias: msg_telegram += f"🎲 *Varredura de Desatualizadas:*\n{', '.join(cat_aleatorias)}\n\n"

        if relatorio_opps: msg_telegram += "🎯 *Ações em Oportunidade:*\n" + "\n".join(relatorio_opps) + "\n\n"

        if relatorio_novatas: msg_telegram += "🌟 *NOVA PREVIDENCIÁRIA ADICIONADA:*\n" + "\n".join(relatorio_novatas)

    # Dispara o alerta se o Macro rodou OU se alguma ação atualizou
    if msg_telegram != "":
        disparar_alertas(msg_telegram)
    else:
        print("✅ Nenhuma atualização de Ações ou Macro necessária neste horário.")

if __name__ == "__main__":
    atualizar_financeiro()