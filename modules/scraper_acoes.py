import io
import random
import requests
import pandas as pd
import yfinance as yf
import config
from modules.utils import formatar, precisa_atualizar, get_request_with_retry

def rodar_garimpo_acoes(planilha, agora_dt, agora_sp, sp_tz):
    print("📈 [1/5] Iniciando auditoria completa de Ações...")
    aba_base = planilha.worksheet("BD_Acoes")

    try:
        url = "https://www.fundamentus.com.br/resultado.php"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = get_request_with_retry(url, headers=headers)
        df = pd.read_html(io.StringIO(response.text), decimal=',', thousands='.')[0]
        df['Papel'] = df['Papel'].str.strip().str.upper()
        df = df.set_index('Papel')
        for col in ['P/L', 'P/VP', 'Div.Yield', 'ROE', 'Liq.2meses']:
            if col in df.columns: df[col] = df[col].apply(formatar)
    except Exception as e:
        print(f"⚠️ Fundamentus indisponível: {e}. Alternando para Yahoo.")
        df = pd.DataFrame() 

    dados_planilha = aba_base.get_all_values()
    todas_originais, mapa_atualizacao, precos_antigos = [], {}, {}
    for row in dados_planilha[1:]:
        if row and row[0].strip() and not row[0].replace(',', '').replace('.', '').isnumeric():
            t = row[0].strip().upper()
            todas_originais.append(t)
            precos_antigos[t] = formatar(row[2]) if len(row) > 2 else 0 # Coluna C
            mapa_atualizacao[t] = row[32] if len(row) > 32 else "" # Coluna AG

    todas = list(todas_originais)
    cat_fixas = [f for f in config.FIXAS_ACOES if f in todas and precisa_atualizar(f, mapa_atualizacao, agora_dt, sp_tz)]
    
    opps_brutas, cat_novatas = [], []
    if not df.empty:
        opps_brutas = df[(df['P/L'] > 0) & (df['P/L'] < 12) & (df['P/VP'] < 1.5) & (df['ROE'] >= 8.0)].index.tolist()
        cat_opps = [o for o in opps_brutas if o in todas_originais and o not in cat_fixas and precisa_atualizar(o, mapa_atualizacao, agora_dt, sp_tz)][:5]
        candidatas = df[(df['P/L']>=2)&(df['P/L']<=15)&(df['P/VP']>=0.2)&(df['P/VP']<=1.5)&(df['Div.Yield']>=6.0)&(df['ROE']>=10.0)].index.tolist()
        cat_novatas = [c for c in candidatas if c not in todas][:2] 
        todas.extend(cat_novatas)
    else:
        cat_opps = []

    usadas = set(cat_fixas + cat_opps + cat_novatas)
    precisam_urgente = [t for t in todas_originais if t not in usadas and precisa_atualizar(t, mapa_atualizacao, agora_dt, sp_tz)]
    cat_aleatorias = random.sample(precisam_urgente, 3) if len(precisam_urgente) >= 3 else precisam_urgente

    fila = cat_fixas + cat_opps + cat_aleatorias + cat_novatas
    if not fila: return [], "", aba_base

    print(f"-> Fila de Ações: {fila}")

    batch_updates = []
    relatorio_fixas = []
    relatorio_opps = []
    relatorio_novatas = []
    relatorio_atualizados = []
    relatorio_fixas_opps = [] 

    for ticker in fila:
        linha_idx = todas.index(ticker) + 2
        try:
            yf_info = yf.Ticker(f"{ticker}.SA").info
            preco_yf = formatar(yf_info.get('currentPrice') or yf_info.get('regularMarketPrice') or 0)
            f = df.loc[ticker] if (not df.empty and ticker in df.index) else {}
            preco = preco_yf if preco_yf > 0 else formatar(f.get('Cotação', 0))
            
            # 🔥 Correção da Divisão por Zero
            lpa_yf = formatar(yf_info.get('trailingEps', 0))
            vpa_yf = formatar(yf_info.get('bookValue', 0))
            
            pl = formatar(f.get('P/L', 0)) if f.get('P/L') else ((preco / lpa_yf) if lpa_yf > 0 else 0)
            pvp = formatar(f.get('P/VP', 0)) if f.get('P/VP') else ((preco / vpa_yf) if vpa_yf > 0 else 0)
            roe = formatar(f.get('ROE', 0))
            setor = yf_info.get('sector', 'N/D')

            # =========================================================================
            # 🗺️ MAPEAMENTO COMPLETO (32 Colunas: B até AG)
            # =========================================================================
            row_base = [
                setor,                                    # 00 | B: Setor
                preco,                                    # 01 | C: Preço
                formatar(f.get('Div.Yield', 0)),          # 02 | D: DY
                formatar(yf_info.get('sharesOutstanding', 0)), # 03 | E: Qtd Ações
                pl,                                       # 04 | F: P/L
                pvp,                                      # 05 | G: P/VP
                formatar(f.get('P/Ativo', 0)),            # 06 | H: P/Ativo
                formatar(f.get('Mrg Bruta', 0)),          # 07 | I: Marg. Bruta
                formatar(f.get('Mrg Ebit', 0)),           # 08 | J: Marg. EBIT
                formatar(f.get('Mrg. Líq.', 0)),          # 09 | K: Marg. Líq
                formatar(f.get('P/EBIT', 0)),             # 10 | L: P/EBIT
                formatar(f.get('EV/EBIT', 0)),            # 11 | M: EV/EBIT
                formatar(f.get('Dív.Líq/ Patrim.', 0)),   # 12 | N: Dív.Liq/EBIT
                formatar(f.get('Dív.Líq/ Patrim.', 0)),   # 13 | O: Dív.Liq/Patri
                formatar(f.get('PSR', 0)),                # 14 | P: PSR
                formatar(f.get('P/Cap.Giro', 0)),         # 15 | Q: P/Cap.Giro
                formatar(f.get('P/Ativ Circ.Liq', 0)),    # 16 | R: P/At.Circ.Liq
                formatar(f.get('Liq. Corr.', 0)),         # 17 | S: Liq. Corr
                roe,                                      # 18 | T: ROE
                formatar(yf_info.get('returnOnAssets', 0)),# 19 | U: ROA
                formatar(f.get('ROIC', 0)),               # 20 | V: ROIC
                0,                                        # 21 | W: Reservado
                0,                                        # 22 | X: Reservado
                0,                                        # 23 | Y: Reservado
                formatar(f.get('Cresc. Rec.5a', 0)),      # 24 | Z: CAGR Rec. 5a
                0,                                        # 25 | AA: Reservado
                formatar(f.get('Liq.2meses', 0)),         # 26 | AB: Liq. Média
                vpa_yf,                                   # 27 | AC: VPA
                lpa_yf,                                   # 28 | AD: LPA
                formatar(yf_info.get('trailingPegRatio', 0)),# 29 | AE: PEG Ratio
                formatar(yf_info.get('marketCap', 0)),    # 30 | AF: Valor Mercado
                f"{agora_sp} OK"                          # 31 | AG: Carimbo Atualização
            ]
            
            if ticker in cat_novatas: batch_updates.append({'range': f'A{linha_idx}:AG{linha_idx}', 'values': [[ticker] + row_base]})
            else: batch_updates.append({'range': f'B{linha_idx}:AG{linha_idx}', 'values': [row_base]})

            # --- CONSTRUÇÃO DO TELEGRAM ---
            p_v = precos_antigos.get(ticker, preco)
            ico = "📈" if preco > p_v else ("📉" if preco < p_v else "➖")

            if ticker in config.FIXAS_ACOES:
                txt = f"🏭 *{ticker}*\n   R$ {p_v:.2f} ➔ R$ {preco:.2f} {ico}\n   P/L: {pl:.1f} | P/VP: {pvp:.2f} | ROE: {roe*100:.1f}%"
                if ticker in opps_brutas: 
                    relatorio_fixas_opps.append(f"🚨 *{ticker} EM OPORTUNIDADE!* 🚨\n{txt}")
                else: 
                    relatorio_fixas.append(txt)
            elif ticker in opps_brutas:
                txt = f"🏭 *{ticker}* (Oportunidade)\n   R$ {preco:.2f}\n   P/L: {pl:.1f} | P/VP: {pvp:.2f} | ROE: {roe*100:.1f}%"
                relatorio_opps.append(txt)
            elif ticker in cat_novatas: 
                txt = f"🏭 *{ticker}* (Nova Garimpada)\n   R$ {preco:.2f}\n   P/L: {pl:.1f} | P/VP: {pvp:.2f} | ROE: {roe*100:.1f}%"
                relatorio_novatas.append(txt)
            else: 
                txt = f"🏭 *{ticker}*\n   R$ {p_v:.2f} ➔ R$ {preco:.2f} {ico}\n   P/L: {pl:.1f} | P/VP: {pvp:.2f} | ROE: {roe*100:.1f}%"
                relatorio_atualizados.append(txt)

            print(f"   ✅ [OK] {ticker} mapeado e processado.")
        except Exception as e: print(f"   ❌ [ERRO] Falha {ticker}: {e}")

    # --- MONTAGEM MODULAR COM SEPARADOR ---
    msg_blocos = ["🤖 *MOVIMENTAÇÃO DE AÇÕES* 🤖"]
    if relatorio_fixas_opps: msg_blocos.append("🏆 *ALERTA VIP (Fixas em Oportunidade):*\n" + "\n\n".join(relatorio_fixas_opps))
    if relatorio_fixas: msg_blocos.append("📌 *CARTEIRA FIXA:*\n" + "\n\n".join(relatorio_fixas))
    if relatorio_opps: msg_blocos.append("🎯 *OPORTUNIDADES:*\n" + "\n\n".join(relatorio_opps))
    if relatorio_novatas: msg_blocos.append("🌟 *GARIMPADAS:*\n" + "\n\n".join(relatorio_novatas))
    if relatorio_atualizados: msg_blocos.append("🔄 *OUTRAS ATUALIZADAS:*\n" + "\n\n".join(relatorio_atualizados))
    
    msg_out = "\n\n➖➖➖➖➖➖➖➖➖➖\n\n".join(msg_blocos) if batch_updates else ""
    
    return batch_updates, msg_out, aba_base