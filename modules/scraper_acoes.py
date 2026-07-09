import io
import random
import requests
import pandas as pd
import yfinance as yf
import config
from modules.utils import formatar, precisa_atualizar, get_request_with_retry

def rodar_garimpo_acoes(planilha, agora_dt, agora_sp, sp_tz):
    print("📈 [1/5] Baixando dados globais do Fundamentus (O Arrastão)...")
    aba_base = planilha.worksheet("BD_Acoes")

    # 🛡️ REDUNDÂNCIA 1: Tenta o Fundamentus. Se falhar, segue o jogo só com o Yahoo Finance.
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
        print(f"⚠️ [AVISO] Fundamentus indisponível ({e}). Alternando para Yahoo Finance 100%.")
        df = pd.DataFrame() 

    print("\n[2/5] Organizando a Fila (Aplicando Trava de Tempo)...")
    dados_planilha = aba_base.get_all_values()
    todas_originais = []
    mapa_atualizacao = {}
    precos_antigos = {} # Guarda o preço anterior para o Telegram

    for row in dados_planilha[1:]:
        if row and row[0].strip() and not row[0].replace(',', '').replace('.', '').isnumeric():
            t = row[0].strip().upper()
            todas_originais.append(t)
            # O preço antigo está na Coluna C (índice 2)
            precos_antigos[t] = formatar(row[2]) if len(row) > 2 else 0
            # O carimbo de tempo está na Coluna AG (índice 32)
            mapa_atualizacao[t] = row[32] if len(row) > 32 else ""

    todas = list(todas_originais)

    cat_fixas = [f for f in config.FIXAS_ACOES if f in todas and precisa_atualizar(f, mapa_atualizacao, agora_dt, sp_tz)]

    cat_opps = []
    cat_novatas = []
    opps_brutas = []

    # 🎯 OPORTUNIDADES: Só roda se o Fundamentus conseguiu baixar a tabela geral
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

    if not fila:
        print("✅ [Ações] Nenhuma atualização necessária (Trava de 2h ativa para todas).")
        return [], "", aba_base

    print(f"-> Ações Fixas na Fila: {cat_fixas}")
    if cat_opps: print(f"-> Oportunidades garimpadas: {cat_opps}")
    if cat_novatas: print(f"-> 🌟 ALERTA CAÇADOR (Novas): {cat_novatas}")
    print(f"-> Varredura de Desatualizadas: {cat_aleatorias}")
    print(f"-> TOTAL PARA ATUALIZAR: {len(fila)} ações.\n")

    print("[3/5] Processando cruzamento de dados linha a linha...")
    batch_updates = []
    relatorio_fixas = []
    relatorio_opps = []
    relatorio_novatas = []
    relatorio_atualizados = []

    for ticker in fila:
        linha_idx = todas.index(ticker) + 2
        try:
            # 🌐 CAPTURA DE PRECISÃO: API GLOBO (Yahoo Finance)
            yf_info = yf.Ticker(f"{ticker}.SA").info
            preco_yf = formatar(yf_info.get('currentPrice') or yf_info.get('regularMarketPrice') or 0)
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

            # 🇧🇷 CAPTURA DE ARRASTÃO: BASE NACIONAL (Fundamentus)
            f = df.loc[ticker] if (not df.empty and ticker in df.index) else {}
            preco_fundamentus = formatar(f.get('Cotação', 0))
            
            # 🔥 CORREÇÃO DO BUG DO R$ 0
            preco = preco_yf if preco_yf > 0 else preco_fundamentus

            # 🛡️ REDUNDÂNCIA 2: Decisão de Inteligência (Prioriza Fundamentus, Falha para YF/Matemática)
            dy_final = formatar(f.get('Div.Yield', dy_yf))
            pl_final = formatar(f.get('P/L', pl_yf)) if f.get('P/L') else (preco / lpa_yf if lpa_yf > 0 else 0)
            pvp_final = formatar(f.get('P/VP', pvp_yf)) if f.get('P/VP') else (preco / vpa_yf if vpa_yf > 0 else 0)
            roe_final = formatar(f.get('ROE', 0))

            # ====================================================================================
            # 🗺️ MAPEAMENTO COMPLETO DAS 32 COLUNAS DA ABA "BD_Acoes" (COLUNAS B ATÉ AG)
            # ====================================================================================
            row_base = [
                setor,                                    # 00 | Coluna B: Setor (YF)
                preco,                                    # 01 | Coluna C: Preço (YF)
                dy_final,                                 # 02 | Coluna D: DY (Fundamentus -> fallback YF)
                n_acoes,                                  # 03 | Coluna E: Nº Ações (YF)
                pl_final,                                 # 04 | Coluna F: P/L (Fundamentus -> fallback YF)
                pvp_final,                                # 05 | Coluna G: P/VP (Fundamentus -> fallback YF)
                formatar(f.get('P/Ativo', 0)),            # 06 | Coluna H: P/Ativo (Fundamentus)
                formatar(f.get('Mrg Bruta', 0)),          # 07 | Coluna I: Marg. Bruta (Fundamentus)
                formatar(f.get('Mrg Ebit', 0)),           # 08 | Coluna J: Marg. EBIT (Fundamentus)
                formatar(f.get('Mrg. Líq.', 0)),          # 09 | Coluna K: Marg. Líq. (Fundamentus)
                formatar(f.get('P/EBIT', 0)),             # 10 | Coluna L: P/EBIT (Fundamentus)
                formatar(f.get('EV/EBIT', 0)),            # 11 | Coluna M: EV/EBIT (Fundamentus)
                formatar(f.get('Dív.Líq/ Patrim.', 0)),   # 12 | Coluna N: Div.Liq/Ebit (Fundamentus)
                formatar(f.get('Dív.Líq/ Patrim.', 0)),   # 13 | Coluna O: Div.Liq/Patri (Fundamentus)
                formatar(f.get('PSR', 0)),                # 14 | Coluna P: PSR (Fundamentus)
                formatar(f.get('P/Cap.Giro', 0)),         # 15 | Coluna Q: P/Cap.Giro (Fundamentus)
                formatar(f.get('P/Ativ Circ.Liq', 0)),    # 16 | Coluna R: P.At.Circ.Liq (Fundamentus)
                formatar(f.get('Liq. Corr.', 0)),         # 17 | Coluna S: Liq. Corr (Fundamentus)
                roe_final,                                # 18 | Coluna T: ROE (Fundamentus)
                roa,                                      # 19 | Coluna U: ROA (YF)
                formatar(f.get('ROIC', 0)),               # 20 | Coluna V: ROIC (Fundamentus)
                0,                                        # 21 | Coluna W: (Reservado/Vazio)
                0,                                        # 22 | Coluna X: (Reservado/Vazio)
                0,                                        # 23 | Coluna Y: (Reservado/Vazio)
                formatar(f.get('Cresc. Rec.5a', 0)),      # 24 | Coluna Z: CAGR Rec. 5a (Fundamentus)
                0,                                        # 25 | Coluna AA: (Reservado/Vazio)
                formatar(f.get('Liq.2meses', 0)),         # 26 | Coluna AB: Liq. Média (Fundamentus)
                vpa_yf,                                   # 27 | Coluna AC: VPA (YF)
                lpa_yf,                                   # 28 | Coluna AD: LPA (YF)
                peg_ratio,                                # 29 | Coluna AE: PEG Ratio (YF)
                valor_mercado,                            # 30 | Coluna AF: Valor Mercado (YF)
                f"{agora_sp} OK"                          # 31 | Coluna AG: Carimbo de Atualização
            ]
            
            if ticker in cat_novatas:
                row_final = [ticker] + row_base
                range_update = f'A{linha_idx}:AG{linha_idx}'
            else:
                row_final = row_base
                range_update = f'B{linha_idx}:AG{linha_idx}'

            batch_updates.append({'range': range_update, 'values': [row_final]})
            print(f"   ✅ [OK] {ticker} Concluída.")

            # --- CONSTRUÇÃO INTELIGENTE DO TELEGRAM (Old vs New) ---
            preco_velho = precos_antigos.get(ticker, preco) 
            icone_variacao = "📈" if preco > preco_velho else ("📉" if preco < preco_velho else "➖")
            
            # Se for Garimpo Novo (Oportunidades do Mercado ou Novatas)
            if ticker in cat_novatas or (ticker in opps_brutas and ticker not in config.FIXAS_ACOES):
                texto_ativo = f"🏭 *{ticker}* ({setor})\n   R$ {preco:.2f}\n   P/L: {pl_final:.1f} | P/VP: {pvp_final:.2f} | ROE: {roe_final*100:.1f}%"
                
                if ticker in cat_novatas: relatorio_novatas.append(texto_ativo)
                elif ticker in opps_brutas: relatorio_opps.append(texto_ativo)

            # Se for Fixa (Sempre mostra a variação)
            elif ticker in config.FIXAS_ACOES:
                texto_ativo = f"🏭 *{ticker}* ({setor})\n   R$ {preco_velho:.2f} ➔ R$ {preco:.2f} {icone_variacao}\n   P/L: {pl_final:.1f} | P/VP: {pvp_final:.2f} | ROE: {roe_final*100:.1f}%"
                
                # ALERTA MÁXIMO: Fixa em Ponto de Bala
                if ticker in opps_brutas:
                    relatorio_fixas_opps.append(f"🚨 *{ticker} ESTÁ BARATA!* 🚨\n   Motivo: P/L abaixo de 12 e P/VP abaixo de 1.5.\n   {texto_ativo}")
                else:
                    relatorio_fixas.append(texto_ativo)
            
            # Varreduras antigas
            else:
                texto_ativo = f"🏭 *{ticker}* ({setor})\n   R$ {preco_velho:.2f} ➔ R$ {preco:.2f} {icone_variacao}\n   P/L: {pl_final:.1f} | P/VP: {pvp_final:.2f} | ROE: {roe_final*100:.1f}%"
                relatorio_atualizados.append(texto_ativo)

        except Exception as e:
            print(f"   ❌ [ERRO] Falha ao processar {ticker}: {e}")

    msg_out = ""
    if batch_updates:
        msg_out = "🤖 *MOVIMENTAÇÃO DE AÇÕES* 🤖\n\n"
        if relatorio_fixas_opps: msg_out += "🏆 *ALERTA VIP: AÇÕES FIXAS EM OPORTUNIDADE* 🏆\n" + "\n\n".join(relatorio_fixas_opps) + "\n\n"
        if relatorio_fixas: msg_out += "📌 *SUA CARTEIRA FIXA:*\n" + "\n\n".join(relatorio_fixas) + "\n\n"
        if relatorio_opps: msg_out += "🎯 *TOP OPORTUNIDADES (P/L < 12):*\n" + "\n\n".join(relatorio_opps) + "\n\n"
        if relatorio_novatas: msg_out += "🌟 *NOVAS PREVIDENCIÁRIAS GARIMPADAS:*\n" + "\n\n".join(relatorio_novatas) + "\n\n"
        if relatorio_atualizados: msg_out += "🔄 *OUTRAS ATUALIZADAS:*\n" + "\n\n".join(relatorio_atualizados) + "\n\n"

    return batch_updates, msg_out, aba_base