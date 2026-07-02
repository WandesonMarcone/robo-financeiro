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
        else:
            print(f"⚠️ Erro ao enviar WhatsApp. Código: {res.status_code}")
    except Exception as e:
        print(f"⚠️ Falha de conexão com CallMeBot: {e}")

def atualizar_financeiro():
    print("🚀 INICIANDO AUDITORIA E MODO CAÇADOR 🚀")
    
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
        print(f"✅ Sucesso: {len(df)} ativos mapeados do Fundamentus.")
    except Exception as e:
        print(f"❌ Erro crítico ao buscar Fundamentus: {e}")
        return

    print("[3/5] Organizando a Fila de Prioridades e Caçando Novatas...")
    todas = aba_base.col_values(1)[1:] # Pula o cabeçalho
    
    # 2.1 - C3 (Metodologia)
    ticker_c3 = str(aba_metodo.acell('C3').value).strip().upper()
    cat_metodologia = [ticker_c3] if ticker_c3 and ticker_c3 in todas else []
    
    # 2.2 - Preparando o DataFrame para filtros rigorosos
    df_filtros = df.copy()
    for col in ['P/L', 'P/VP', 'Div.Yield', 'ROE', 'Liq.2meses']:
        df_filtros[col] = df_filtros[col].apply(formatar)
        
    # 2.3 - Oportunidades (Ações que JÁ ESTÃO na planilha)
    opps_brutas = df_filtros[(df_filtros['P/L'] > 0.1) & (df_filtros['P/L'] < 12) & (df_filtros['P/VP'] < 1.5)].index.tolist()
    cat_opps = [o for o in opps_brutas if o in todas and o not in FIXAS and o != ticker_c3][:5]
    
    # 2.4 - MODO CAÇADOR: Novas ações previdenciárias (NÃO ESTÃO na planilha)
    candidatas_previdenciarias = df_filtros[
        (df_filtros['P/L'] >= 2) & (df_filtros['P/L'] <= 15) &
        (df_filtros['P/VP'] >= 0.2) & (df_filtros['P/VP'] <= 1.5) &
        (df_filtros['Div.Yield'] >= 6.0) & # DY maior que 6%
        (df_filtros['ROE'] >= 10.0) &      # Eficiência maior que 10%
        (df_filtros['Liq.2meses'] >= 2000000) # Alta liquidez
    ].index.tolist()
    
    # Pega no máximo 2 ações novas por rodada para não bagunçar a planilha
    cat_novatas = [c for c in candidatas_previdenciarias if c not in todas][:2]
    todas.extend(cat_novatas) # Adiciona na lista em memória para ganhar uma linha
    
    # 2.5 - Fixas e Aleatórias
    cat_fixas = [f for f in FIXAS if f in todas]
    usadas = set(cat_fixas + cat_metodologia + cat_opps + cat_novatas)
    disponiveis = [t for t in todas if t not in usadas]
    cat_aleatorias = random.sample(disponiveis, min(len(disponiveis), 3))
    
    # Junta todas
    fila = cat_fixas + cat_metodologia + cat_opps + cat_aleatorias + cat_novatas
    print(f"📋 Fila montada com {len(fila)} ativos.")
    if cat_novatas: print(f"🌟 ALERTA CAÇADOR: Novas ações encontradas -> {cat_novatas}")

    print("\n[4/5] Processando cruzamento de dados (YF + Fundamentus)...")
    batch_updates = []
    relatorio_opps = []
    relatorio_novatas = []
    
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
            
            f = df.loc[ticker]
            dy_fmt = formatar(f.get('Div.Yield', 0))
            roe_fmt = formatar(f.get('ROE', 0))
            pl_fmt = formatar(f.get('P/L', 0))
            pvp_fmt = formatar(f.get('P/VP', 0))
            
            # MAPEAMENTO COMPLETO (A até AF - ATENÇÃO: Adicionado Ticker na Coluna A)
            row = [
                ticker,                                   # A: Ticker (Gravado automaticamente)
                preco,                                    # B: Preço (YF)
                dy_fmt,                                   # C: DY
                n_acoes,                                  # D: Nº Ações (YF)
                pl_fmt,                                   # E: P/L
                pvp_fmt,                                  # F: P/VP
                formatar(f.get('P/Ativo', 0)),            # G: P/Ativo
                formatar(f.get('Mrg Bruta', 0)),          # H: Marg. Bruta
                formatar(f.get('Mrg Ebit', 0)),           # I: Marg. EBIT
                formatar(f.get('Mrg. Líq.', 0)),          # J: Marg. Líq.
                formatar(f.get('P/EBIT', 0)),             # K: P/EBIT
                formatar(f.get('EV/EBIT', 0)),            # L: EV/EBIT
                formatar(f.get('Dív.Líq/ Patrim.', 0)),   # M: Div.Liq/Ebit 
                formatar(f.get('Dív.Líq/ Patrim.', 0)),   # N: Div.Liq/Patri
                formatar(f.get('PSR', 0)),                # O: PSR
                formatar(f.get('P/Cap.Giro', 0)),         # P: P/Cap.Giro
                formatar(f.get('P/Ativ Circ.Liq', 0)),    # Q: P.At.Circ.Liq
                formatar(f.get('Liq. Corr.', 0)),         # R: Liq. Corr
                roe_fmt,                                  # S: ROE
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
            
            # ATENÇÃO: Range agora é A:AF
            batch_updates.append({'range': f'A{linha_idx}:AF{linha_idx}', 'values': [row]})
            
            # Logs no GitHub (Limpos)
            cat_atual = "Fixa" if ticker in cat_fixas else "Novata" if ticker in cat_novatas else "Metodologia" if ticker in cat_metodologia else "Oportunidade" if ticker in cat_opps else "Aleatória"
            
            verificacao = {"Preço": preco, "Nº Ações": n_acoes, "VPA": vpa, "LPA": lpa, "Valor Mercado": valor_mercado, "P/L": pl_fmt}
            dados_zerados = [k for k, v in verificacao.items() if v == 0.0]
            
            if dados_zerados: print(f"   ✅ [OK] {ticker} ({cat_atual}) | ⚠️ Faltou: {', '.join(dados_zerados)}")
            else: print(f"   ✅ [OK] {ticker} ({cat_atual}) | Completa.")
            
            # Prepara Relatórios do WhatsApp
            if ticker in cat_opps:
                relatorio_opps.append(f"• *{ticker}*: R$ {preco} (P/L: {pl_fmt} | P/VP: {pvp_fmt} | ROE: {roe_fmt * 100:.1f}%)")
            
            if ticker in cat_novatas:
                relatorio_novatas.append(f"• *{ticker}*: R$ {preco} (DY: {dy_fmt * 100:.1f}% | ROE: {roe_fmt * 100:.1f}%)")
                
        except Exception as e:
            print(f"   ❌ [ERRO] Falha ao processar {ticker}: {e}")

    print("\n[5/5] Escrevendo lote no Google Sheets e Notificando...")
    if batch_updates:
        aba_base.batch_update(batch_updates)
        print(f"💾 Planilha atualizada ({len(batch_updates)} ações).")
        
        # Monta WhatsApp
        msg_wpp = "🤖 *Relatório de Atualização Mestre* 🤖\n\n"
        if cat_fixas: msg_wpp += f"📌 *Fixas:*\n{', '.join(cat_fixas)}\n\n"
        if cat_metodologia: msg_wpp += f"🔍 *Metodologia:*\n{', '.join(cat_metodologia)}\n\n"
        if cat_aleatorias: msg_wpp += f"🎲 *Aleatórias:*\n{', '.join(cat_aleatorias)}\n\n"
            
        if relatorio_opps:
            msg_wpp += "🎯 *Oportunidades Atualizadas:*\n" + "\n".join(relatorio_opps) + "\n\n"
            
        if relatorio_novatas:
            msg_wpp += "🌟 *NOVA AÇÃO PREVIDENCIÁRIA ADICIONADA:*\n" + "\n".join(relatorio_novatas)
            
        enviar_whatsapp(msg_wpp)
    else:
        print("⚠️ Nenhum dado para atualizar nesta rodada.")

    print("\n🏁 --- PROCESSO FINALIZADO --- 🏁")

if __name__ == "__main__":
    atualizar_financeiro()