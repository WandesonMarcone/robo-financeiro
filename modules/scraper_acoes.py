import io
import random
import requests
import pandas as pd
import yfinance as yf
import config
from modules.utils import formatar, precisa_atualizar

def rodar_garimpo_acoes(planilha, agora_dt, agora_sp, sp_tz):
    print("[2/5] Baixando dados globais do Fundamentus...")
    aba_base = planilha.worksheet("BD_Acoes")

    # REDUNDÂNCIA 1: Se o Fundamentus cair, criamos um DataFrame vazio e o Yahoo assume.
    try:
        url = "https://www.fundamentus.com.br/resultado.php"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        df = pd.read_html(io.StringIO(response.text), decimal=',', thousands='.')[0]
        df['Papel'] = df['Papel'].str.strip().str.upper()
        df = df.set_index('Papel')
        for col in ['P/L', 'P/VP', 'Div.Yield', 'ROE', 'Liq.2meses']:
            if col in df.columns:
                df[col] = df[col].apply(formatar)
    except Exception as e:
        print(f"⚠️ [AVISO] Fundamentus indisponível ({e}). Alternando para Yahoo Finance 100%.")
        df = pd.DataFrame() # DataFrame vazio para não quebrar o código

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

    cat_fixas = [f for f in config.FIXAS_ACOES if f in todas and precisa_atualizar(f, mapa_atualizacao, agora_dt, sp_tz)]

    # Oportunidades Reais e Caçador (Só rodam se o Fundamentus estiver online, pois precisam varrer o mercado todo)
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

    print(f"-> Ações Fixas na Fila: {cat_fixas}")
    if cat_opps: print(f"-> Oportunidades garimpadas: {cat_opps}")
    if cat_novatas: print(f"-> 🌟 ALERTA CAÇADOR (Novas): {cat_novatas}")
    print(f"-> Varredura de Desatualizadas: {cat_aleatorias}")
    print(f"-> TOTAL PARA ATUALIZAR: {len(fila)} ações.\n")

    # 3. PROCESSAMENTO REDUNDANTE (YF + FUNDAMENTUS)
    print("[4/5] Processando cruzamento de dados linha a linha...")
    batch_updates = []
    relatorio_opps = []
    relatorio_novatas = []
    relatorio_fixas_opps = [] 

    for ticker in fila:
        linha_idx = todas.index(ticker) + 2
        try:
            # 1. Puxa dados globais da API
            yf_info = yf.Ticker(f"{ticker}.SA").info
            preco = formatar(yf_info.get('currentPrice') or yf_info.get('regularMarketPrice'))
            n_acoes = formatar(yf_info.get('sharesOutstanding')) 
            roa = formatar(yf_info.get('returnOnAssets'))        
            peg_ratio = formatar(yf_info.get('trailingPegRatio') or yf_info.get('pegRatio')) 
            valor_mercado = formatar(yf_info.get('marketCap'))   
            vpa_yf = formatar(yf_info.get('bookValue'))             
            lpa_yf = formatar(yf_info.get('trailingEps'))
            dy_yf = formatar(yf_info.get('dividendYield', 0)) * 100
            pl_yf = formatar(yf_info.get('trailingPE'))
            pvp_yf = formatar(yf_info.get('priceToBook'))

            setor_eng = yf_info.get('sector', 'N/D')
            traducao_setores = {'Energy': 'Energia', 'Financial Services': 'Financeiro', 'Basic Materials': 'Materiais Básicos', 'Utilities': 'Utilidade Pública', 'Industrials': 'Indústria', 'Consumer Defensive': 'Consumo Defensivo', 'Consumer Cyclical': 'Consumo Cíclico', 'Healthcare': 'Saúde', 'Technology': 'Tecnologia', 'Communication Services': 'Comunicações', 'Real Estate': 'Imobiliário'}
            setor = traducao_setores.get(setor_eng, setor_eng)

            # 2. Tenta puxar do Fundamentus (Se não existir, o df.loc retorna vazio)
            f = df.loc[ticker] if (not df.empty and ticker in df.index) else {}

            # REDUNDÂNCIA 2: O Melhor dos Dois Mundos (Fallback)
            dy_final = formatar(f.get('Div.Yield', dy_yf))
            pl_final = formatar(f.get('P/L', pl_yf)) if f.get('P/L') else (preco / lpa_yf if lpa_yf > 0 else 0)
            pvp_final = formatar(f.get('P/VP', pvp_yf)) if f.get('P/VP') else (preco / vpa_yf if vpa_yf > 0 else 0)
            roe_final = formatar(f.get('ROE', 0))

            row_base = [
                setor, preco, dy_final, n_acoes, pl_final, pvp_final, 
                formatar(f.get('P/Ativo', 0)), formatar(f.get('Mrg Bruta', 0)), 
                formatar(f.get('Mrg Ebit', 0)), formatar(f.get('Mrg. Líq.', 0)), 
                formatar(f.get('P/EBIT', 0)), formatar(f.get('EV/EBIT', 0)), 
                formatar(f.get('Dív.Líq/ Patrim.', 0)), formatar(f.get('Dív.Líq/ Patrim.', 0)), 
                formatar(f.get('PSR', 0)), formatar(f.get('P/Cap.Giro', 0)), 
                formatar(f.get('P/Ativ Circ.Liq', 0)), formatar(f.get('Liq. Corr.', 0)), 
                roe_final, roa, formatar(f.get('ROIC', 0)), 
                0, 0, 0, formatar(f.get('Cresc. Rec.5a', 0)), 0, 
                formatar(f.get('Liq.2meses', 0)), vpa_yf, lpa_yf, peg_ratio, valor_mercado, 
                f"{agora_sp} OK"
            ]

            if ticker in cat_novatas:
                row_final = [ticker] + row_base
                range_update = f'A{linha_idx}:AG{linha_idx}'
            else:
                row_final = row_base
                range_update = f'B{linha_idx}:AG{linha_idx}'

            batch_updates.append({'range': range_update, 'values': [row_final]})

            tag_extra = ""
            if ticker in opps_brutas:
                if ticker in config.FIXAS_ACOES: tag_extra = " (Ação Fixa)"

            print(f"   ✅ [OK] {ticker} ({tag_extra or 'Processada'}) | Concluída.")

            if ticker in opps_brutas:
                detalhe_msg = f"R$ {preco} | 🏢 {setor} (P/L: {pl_final} | P/VP: {pvp_final} | ROE: {roe_final*100:.1f}%)"

                if ticker in config.FIXAS_ACOES:
                    relatorio_fixas_opps.append(f"• *{ticker}* está barata!\n   Motivo: P/L ({pl_final}) abaixo de 12, P/VP ({pvp_final}) abaixo de 1.5.\n   🏢 Setor: {setor}")
                relatorio_opps.append(f"• *{ticker}*{tag_extra}: {detalhe_msg}")

            if ticker in cat_novatas:
                relatorio_novatas.append(f"• *{ticker}*: R$ {preco} | 🏢 {setor} (DY: {dy_final*100:.1f}% | ROE: {roe_final*100:.1f}%)")

        except Exception as e:
            print(f"   ❌ [ERRO] Falha ao processar {ticker}: {e}")

    msg_out = ""
    if batch_updates:
        msg_out = "🤖 *Relatório de Ações* 🤖\n\n"
        if relatorio_fixas_opps:
            msg_out += "🚨 *ALERTA VIP: AÇÕES FIXAS EM OPORTUNIDADE* 🚨\n" + "\n".join(relatorio_fixas_opps) + "\n\n"
        if cat_fixas: msg_out += f"📌 *Fixas Processadas:*\n{', '.join(cat_fixas)}\n\n"
        if cat_aleatorias: msg_out += f"🎲 *Varredura de Desatualizadas:*\n{', '.join(cat_aleatorias)}\n\n"
        if relatorio_opps: msg_out += "🎯 *Ações em Oportunidade:*\n" + "\n".join(relatorio_opps) + "\n\n"
        if relatorio_novatas: msg_out += "🌟 *NOVA PREVIDENCIÁRIA ADICIONADA:*\n" + "\n".join(relatorio_novatas)

    return batch_updates, msg_out, aba_base
