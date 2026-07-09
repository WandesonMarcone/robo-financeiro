import io
import random
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime
import pytz
import config
from modules.utils import formatar, precisa_atualizar, get_request_with_retry

def classificar_fii_e_emoji(setor):
    s = str(setor).upper()
    if any(x in s for x in ["TÍTULOS", "PAPEL", "RECEBÍVEL"]): return "Papel", "📜"
    if any(x in s for x in ["FUNDO DE FUNDOS", "FOF"]): return "FOF", "🔄"
    return "Tijolo", "🧱"

def rodar_garimpo_fiis(planilha, agora_dt, agora_sp, sp_tz):
    print("🏢 [1/5] Iniciando motor de FIIs...")
    aba_fiis = planilha.worksheet("BD_FIIs")
    try:
        url = "https://www.fundamentus.com.br/fii_resultado.php"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = get_request_with_retry(url, headers=headers)
        df = pd.read_html(io.StringIO(response.text), decimal=',', thousands='.')[0]
        df['Papel'] = df['Papel'].str.strip().str.upper()
        df = df.set_index('Papel')
        for col in ['Cotação', 'P/VP', 'Dividend Yield', 'Vacância Média', 'Qtd de imóveis']:
            if col in df.columns: df[col] = df[col].apply(formatar)
    except: df = pd.DataFrame()

    dados_planilha = aba_fiis.get_all_values()
    tickers, mapa_atualizacao, precos_antigos = [], {}, {}
    for row in dados_planilha[1:]:
        if row and row[0].strip():
            t = row[0].strip().upper()
            tickers.append(t)
            precos_antigos[t] = formatar(row[3]) if len(row) > 3 else 0
            mapa_atualizacao[t] = row[15] if len(row) > 15 else ""

    cat_fixas = [f for f in config.FIXAS_FIIS if f in tickers and precisa_atualizar(f, mapa_atualizacao, agora_dt, sp_tz)]
    novatos = []
    if not df.empty:
        df_cacador = df[(df['P/VP'] >= 0.85) & (df['P/VP'] <= 1.05) & (df['Dividend Yield'] >= 0.08) & (df['Vacância Média'] <= 0.10)]
        novatos = [fii for fii in df_cacador.index if fii not in tickers and fii not in cat_fixas][:3]

    fila = cat_fixas + novatos + [t for t in tickers if t not in cat_fixas and t not in novatos and precisa_atualizar(t, mapa_atualizacao, agora_dt, sp_tz)][:2]
    if not fila: return [], "", aba_fiis

    batch_updates, rel_fixas, rel_opps, rel_at, rel_fixas_opps = [], [], [], [], []
    for ticker in fila:
        try:
            yf_info = yf.Ticker(f"{ticker}.SA").info
            preco = formatar(yf_info.get('currentPrice') or yf_info.get('regularMarketPrice') or 0)
            f = df.loc[ticker] if (not df.empty and ticker in df.index) else {}
            if preco <= 0: preco = formatar(f.get('Cotação', 0))
            
            tipo, emoji = ("Tijolo", "🧱") if ticker in ["GARE11", "VISC11"] else classificar_fii_e_emoji(f.get('Segmento', ''))
            pvp, dy = formatar(f.get('P/VP', 0)), formatar(f.get('Dividend Yield', 0))
            
            # =========================================================================
            # 🗺️ MAPEAMENTO COMPLETO (16 Colunas: A até Q)
            # =========================================================================
            row = [ticker, tipo, f.get('Segmento', 'N/D'), preco, (f.get('Valor de Mercado', 0)/preco if preco>0 else 0), 
                   pvp, dy, formatar(f.get('Vacância Média', 0)), formatar(f.get('Qtd de imóveis', 0)), 
                   "Mapeamento", "Pendente", formatar(f.get('Liquidez', 0)), formatar(f.get('Valor de Mercado', 0)), 
                   (preco/pvp if pvp>0 else 0), (f.get('Valor de Mercado', 0)*dy), ((preco*dy)/12), f"{agora_sp} OK"]
            
            if ticker in tickers: batch_updates.append({'range': f'B{tickers.index(ticker)+2}:Q{tickers.index(ticker)+2}', 'values': [row[1:]]})
            else: batch_updates.append({'range': f'A{len(dados_planilha)+1}:Q{len(dados_planilha)+1}', 'values': [row]})

            p_velho = precos_antigos.get(ticker, preco)
            ico = "📈" if preco > p_velho else ("📉" if preco < p_velho else "➖")
            txt = f"{emoji} *{ticker}*\n   R$ {p_velho:.2f} ➔ R$ {preco:.2f} {ico}\n   P/VP: {pvp:.2f} | DY: {dy*100:.1f}%"
            
            if ticker in config.FIXAS_FIIS:
                if ticker in novatos: rel_fixas_opps.append(f"🚨 *{ticker} EM OPORTUNIDADE!* 🚨\n{txt}")
                else: rel_fixas.append(txt)
            elif ticker in novatos: rel_opps.append(f"{emoji} *{ticker}* (Oportunidade)\n   R$ {preco:.2f}")
            else: rel_at.append(txt)
            print(f"   ✅ [OK] FII {ticker} processado.")
        except Exception as e: print(f"   ❌ [ERRO] {ticker}: {e}")

    # --- MONTAGEM ORGANIZADA E MODULAR ---
    msg_blocos = ["🏢 *MOVIMENTAÇÃO DE FIIs* 🏢"]

    if rel_fixas_opps:
        bloco = "🏆 *ALERTA VIP: FIXAS EM OPORTUNIDADE* 🏆\n" + "\n\n".join(rel_fixas_opps)
        msg_blocos.append(bloco)

    if rel_fixas:
        bloco = "📌 *CARTEIRA FIXA:*\n" + "\n\n".join(rel_fixas)
        msg_blocos.append(bloco)

    if rel_opps:
        bloco = "🎯 *TOP OPORTUNIDADES:*\n" + "\n\n".join(rel_opps)
        msg_blocos.append(bloco)

    if rel_at:
        bloco = "🔄 *ATUALIZAÇÕES DE FIIs:*\n" + "\n\n".join(rel_at)
        msg_blocos.append(bloco)

    # Une os blocos com uma linha divisória clara
    msg = "\n\n➖➖➖➖➖➖➖➖➖➖\n\n".join(msg_blocos)

    return batch_updates, msg, aba_fiis