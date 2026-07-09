import io
import random
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime
import pytz
import config
from modules.utils import formatar, precisa_atualizar

def classificar_fii_e_emoji(setor):
    s = str(setor).upper()
    if any(x in s for x in ["TÍTULOS", "PAPEL", "RECEBÍVEL", "VALORES MOBILIÁRIOS"]): 
        return "Papel", "📜"
    if any(x in s for x in ["FUNDO DE FUNDOS", "FOF"]): 
        return "FOF", "🔄"
    if any(x in s for x in ["HÍBRIDO", "MISTO"]): 
        return "Híbrido", "🧩"
    return "Tijolo", "🧱"

def rodar_garimpo_fiis(planilha, agora_dt, agora_sp, sp_tz):
    print("🏢 [1/5] Iniciando motor de FIIs...")
    aba_fiis = planilha.worksheet("BD_FIIs")

    try:
        url = "https://www.fundamentus.com.br/fii_resultado.php"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        df = pd.read_html(io.StringIO(response.text), decimal=',', thousands='.')[0]
        df['Papel'] = df['Papel'].str.strip().str.upper()
        df = df.set_index('Papel')
        # Adicionado 'Cotação' para servir de backup caso o Yahoo falhe (Bug do R$ 0)
        for col in ['Cotação', 'P/VP', 'Dividend Yield', 'Liquidez', 'Vacância Média', 'Valor de Mercado', 'Qtd de imóveis']:
            if col in df.columns:
                df[col] = df[col].apply(formatar)
    except Exception as e:
        print(f"❌ Erro Fundamentus FIIs: {e}")
        df = pd.DataFrame() 

    dados_planilha = aba_fiis.get_all_values()
    tickers_planilha = []
    mapa_atualizacao = {}
    precos_antigos = {}
    
    for row in dados_planilha[1:]: 
        if row and row[0].strip():
            t = row[0].strip().upper()
            tickers_planilha.append(t)
            precos_antigos[t] = formatar(row[3]) if len(row) > 3 else 0 # O preço antigo está na coluna D
            mapa_atualizacao[t] = row[15] if len(row) > 15 else ""

    cat_fixas = [f for f in config.FIXAS_FIIS if f in tickers_planilha and precisa_atualizar(f, mapa_atualizacao, agora_dt, sp_tz)]
    
    novatos_garimpados = []
    if not df.empty:
        df_cacador = df[
            (df['P/VP'] >= 0.85) & (df['P/VP'] <= 1.05) &  
            (df['Dividend Yield'] >= 0.08) &               
            (df['Liquidez'] >= 1000000) &                  
            (df['Vacância Média'] <= 0.10)                 
        ]
        # Pega as top 3 oportunidades com maior DY
        oportunidades_gerais = df_cacador.sort_values(by='Dividend Yield', ascending=False).index.tolist()
        novatos_garimpados = [fii for fii in oportunidades_gerais if fii not in tickers_planilha and fii not in cat_fixas][:3]
    
    usadas = set(cat_fixas + novatos_garimpados)
    precisam_urgente = [t for t in tickers_planilha if t not in usadas and precisa_atualizar(t, mapa_atualizacao, agora_dt, sp_tz)]
    cat_desatualizadas = random.sample(precisam_urgente, 2) if len(precisam_urgente) >= 2 else precisam_urgente

    fila_total = cat_fixas + novatos_garimpados + cat_desatualizadas
    if not fila_total: return [], "", aba_fiis

    batch_updates = []
    relatorio_fixas = []
    relatorio_opps = []
    relatorio_atualizados = []
    proxima_linha_vazia = len(dados_planilha) + 1 

    for ticker in fila_total:
        try:
            yf_info = yf.Ticker(f"{ticker}.SA").info
            preco_yf = formatar(yf_info.get('currentPrice') or yf_info.get('regularMarketPrice') or 0)
            
            f = df.loc[ticker] if (not df.empty and ticker in df.index) else {}
            preco_fundamentus = formatar(f.get('Cotação', 0))
            
            # 🔥 CORREÇÃO DO BUG DO R$ 0 (Fallback Inteligente)
            preco = preco_yf if preco_yf > 0 else preco_fundamentus

            setor = f.get('Segmento', 'N/D') if isinstance(f.get('Segmento'), str) else 'N/D'
            
            if ticker == "GARE11": setor, tipo, emoji = "Galpões/Renda Urbana", "Tijolo", "🧱"
            elif ticker == "VISC11": setor, tipo, emoji = "Shoppings", "Tijolo", "🧱"
            elif ticker == "MXRF11": setor, tipo, emoji = "Papel/Múltiplo", "Papel", "📜"
            else: tipo, emoji = classificar_fii_e_emoji(setor)

            pvp = formatar(f.get('P/VP', 0))
            dy = formatar(f.get('Dividend Yield', 0))
            vacancia = formatar(f.get('Vacância Média', 0))
            liquidez = formatar(f.get('Liquidez', 0))
            valor_mercado = formatar(f.get('Valor de Mercado', 0))
            qtd_imoveis = formatar(f.get('Qtd de imóveis', 0)) 

            vpa = preco / pvp if pvp > 0 else (valor_mercado / (valor_mercado / preco) if preco > 0 else 0)
            numero_cotas = valor_mercado / preco if preco > 0 else 0
            media_div_mensal = (preco * dy) / 12
            lucro_12m = valor_mercado * dy 

            row_update_completo = [
                ticker, tipo, setor, preco, numero_cotas, pvp, dy, vacancia, qtd_imoveis, 
                "Mapeamento em Curso", "Pendente", liquidez, valor_mercado, vpa, lucro_12m, media_div_mensal, f"{agora_sp} OK"
            ]
            row_update_parcial = row_update_completo[1:] 

            if ticker in tickers_planilha:
                linha_idx = tickers_planilha.index(ticker) + 2
                batch_updates.append({'range': f'B{linha_idx}:Q{linha_idx}', 'values': [row_update_parcial]})
            else:
                batch_updates.append({'range': f'A{proxima_linha_vazia}:Q{proxima_linha_vazia}', 'values': [row_update_completo]})
                proxima_linha_vazia += 1
                
            # --- CONSTRUÇÃO DO TELEGRAM (Old vs New & Vacância Condicional) ---
            preco_velho = precos_antigos.get(ticker, preco)
            icone_variacao = "📈" if preco > preco_velho else ("📉" if preco < preco_velho else "➖")
            txt_vacancia = f" | 🏚️ Vacância: {vacancia*100:.1f}%" if tipo == "Tijolo" else ""
            
            texto_ativo = f"{emoji} *{ticker}* ({tipo})\n   R$ {preco_velho:.2f} ➔ R$ {preco:.2f} {icone_variacao}\n   P/VP: {pvp:.2f} | DY: {dy*100:.1f}%{txt_vacancia}"

            if ticker in cat_fixas: relatorio_fixas.append(texto_ativo)
            elif ticker in novatos_garimpados: relatorio_opps.append(texto_ativo)
            else: relatorio_atualizados.append(texto_ativo)

        except Exception as e:
            print(f"   ❌ [ERRO] Falha {ticker}: {e}")

    msg_out = ""
    if batch_updates:
        msg_out = "🏢 *MOVIMENTAÇÃO DE FIIs* 🏢\n\n"
        if relatorio_fixas: msg_out += "📌 *SUA CARTEIRA FIXA:*\n" + "\n\n".join(relatorio_fixas) + "\n\n"
        if relatorio_opps: msg_out += "🎯 *TOP OPORTUNIDADES (Desconto + DY):*\n" + "\n\n".join(relatorio_opps) + "\n\n"
        if relatorio_atualizados: msg_out += "🔄 *OUTROS ATUALIZADOS:*\n" + "\n\n".join(relatorio_atualizados) + "\n\n"

    return batch_updates, msg_out, aba_fiis