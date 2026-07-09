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

    # 🛡️ REDUNDÂNCIA 1: Tenta o Fundamentus. Se falhar, segue com Yahoo Finance.
    try:
        url = "https://www.fundamentus.com.br/resultado.php"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = get_request_with_retry(url, headers=headers)
        df = pd.read_html(io.StringIO(response.text), decimal=',', thousands='.')[0]
        df['Papel'] = df['Papel'].str.strip().str.upper()
        df = df.set_index('Papel')
        for col in ['P/L', 'P/VP', 'Div.Yield', 'ROE', 'Liq.2meses']:
            if col in df.columns:
                df[col] = df[col].apply(formatar)
    except Exception as e:
        print(f"⚠️ [AVISO] Fundamentus indisponível: {e}. Alternando para Yahoo Finance.")
        df = pd.DataFrame() 

    print("\n[2/5] Organizando a Fila (Trava de 2h)...")
    dados_planilha = aba_base.get_all_values()
    todas_originais = []
    mapa_atualizacao = {}
    precos_antigos = {} 

    for row in dados_planilha[1:]:
        if row and row[0].strip() and not row[0].replace(',', '').replace('.', '').isnumeric():
            t = row[0].strip().upper()
            todas_originais.append(t)
            # Carrega preço antigo (Coluna C / índice 2) e data (Coluna AG / índice 32)
            precos_antigos[t] = formatar(row[2]) if len(row) > 2 else 0
            mapa_atualizacao[t] = row[32] if len(row) > 32 else ""

    todas = list(todas_originais)
    cat_fixas = [f for f in config.FIXAS_ACOES if f in todas and precisa_atualizar(f, mapa_atualizacao, agora_dt, sp_tz)]

    cat_opps = []
    cat_novatas = []
    opps_brutas = []

    if not df.empty:
        opps_brutas = df[(df['P/L'] > 0) & (df['P/L'] < 12) & (df['P/VP'] < 1.5) & (df['ROE'] >= 8.0)].index.tolist()
        cat_opps = [o for o in opps_brutas if o in todas_originais and o not in cat_fixas and precisa_atualizar(o, mapa_atualizacao, agora_dt, sp_tz)][:5]

        candidatas_prev = df[
            (df['P/L'] >= 2) & (df['P/L'] <= 15) &
            (df['P/VP'] >= 0.2) & (df['P/VP'] <= 1.5) &
            (df['Div.Yield'] >= 6.0) & (df['ROE'] >= 10.0) &      
            (df['Liq.2meses'] >= 2000000) 
        ].index.tolist()
        cat_novatas = [c for c in candidatas_prev if c not in todas][:2] 
        todas.extend(cat_novatas) 

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
            
            # Mapeamento e Cálculos
            pl_final = formatar(f.get('P/L', 0))
            pvp_final = formatar(f.get('P/VP', 0))
            roe_final = formatar(f.get('ROE', 0))
            setor = f.get('Setor', 'N/D') 

            # ====================================================================================
            # 🗺️ MAPEAMENTO COMPLETO (32 Colunas: B até AG)
            # ====================================================================================
            row_base = [
                setor, preco, formatar(f.get('Div.Yield', 0)), formatar(yf_info.get('sharesOutstanding', 0)), 
                pl_final, pvp_final, formatar(f.get('P/Ativo', 0)), formatar(f.get('Mrg Bruta', 0)), 
                formatar(f.get('Mrg Ebit', 0)), formatar(f.get('Mrg. Líq.', 0)), formatar(f.get('P/EBIT', 0)), 
                formatar(f.get('EV/EBIT', 0)), formatar(f.get('Dív.Líq/ Patrim.', 0)), formatar(f.get('Dív.Líq/ Patrim.', 0)), 
                formatar(f.get('PSR', 0)), formatar(f.get('P/Cap.Giro', 0)), formatar(f.get('P/Ativ Circ.Liq', 0)), 
                formatar(f.get('Liq. Corr.', 0)), roe_final, formatar(yf_info.get('returnOnAssets', 0)), 
                formatar(f.get('ROIC', 0)), 0, 0, 0, formatar(f.get('Cresc. Rec.5a', 0)), 0, 
                formatar(f.get('Liq.2meses', 0)), formatar(yf_info.get('bookValue', 0)), 
                formatar(yf_info.get('trailingEps', 0)), formatar(yf_info.get('trailingPegRatio', 0)), 
                formatar(yf_info.get('marketCap', 0)), f"{agora_sp} OK"
            ]

            if ticker in cat_novatas:
                batch_updates.append({'range': f'A{linha_idx}:AG{linha_idx}', 'values': [[ticker] + row_base]})
            else:
                batch_updates.append({'range': f'B{linha_idx}:AG{linha_idx}', 'values': [row_base]})

            preco_velho = precos_antigos.get(ticker, preco)
            ico = "📈" if preco > preco_velho else ("📉" if preco < preco_velho else "➖")
            txt = f"🏭 *{ticker}*\n   R$ {preco_velho:.2f} ➔ R$ {preco:.2f} {ico}\n   P/L: {pl_final:.1f} | P/VP: {pvp_final:.2f} | ROE: {roe_final*100:.1f}%"

            if ticker in config.FIXAS_ACOES:
                if ticker in opps_brutas: relatorio_fixas_opps.append(f"🚨 *FIXA EM OPORTUNIDADE!* 🚨\n{txt}")
                else: relatorio_fixas.append(txt)
            elif ticker in opps_brutas: relatorio_opps.append(txt)
            elif ticker in cat_novatas: relatorio_novatas.append(txt)
            else: relatorio_atualizados.append(txt)
            
            print(f"   ✅ [OK] {ticker} mapeado e processado.")
        except Exception as e: print(f"   ❌ [ERRO] Falha {ticker}: {e}")

    msg = "🤖 *MOVIMENTAÇÃO AÇÕES* 🤖\n\n" + (f"🏆 *FIXAS:* \n" + "\n\n".join(relatorio_fixas_opps + relatorio_fixas) + "\n\n" if relatorio_fixas or relatorio_fixas_opps else "") + (f"🎯 *OPORTUNIDADES:*\n" + "\n\n".join(relatorio_opps) + "\n\n" if relatorio_opps else "") + (f"🔄 *OUTRAS:*\n" + "\n\n".join(relatorio_atualizados) if relatorio_atualizados else "")
    return batch_updates, msg, aba_base
