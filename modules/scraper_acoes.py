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
    aba_metodo = planilha.worksheet("Metodos_Acoes")

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
        return [], "", aba_base

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

    # --- 2.1 Fixas puxadas do config.py ---
    cat_fixas = [f for f in config.FIXAS_ACOES if f in todas and precisa_atualizar(f, mapa_atualizacao, agora_dt, sp_tz)]
    fixas_travadas = [f for f in config.FIXAS_ACOES if f in todas and f not in cat_fixas]
    if fixas_travadas: 
        print(f"🔒 TRAVA ATIVADA: Ignorando {fixas_travadas} (Atualizadas há menos de 2h)")

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

    # --- 2.3 Oportunidades Reais ---
    opps_brutas = df_filtros[(df_filtros['P/L'] > 0) & (df_filtros['P/L'] < 12) & (df_filtros['P/VP'] < 1.5) & (df_filtros['ROE'] >= 8.0)].index.tolist()
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

    # --- 2.5 Aleatórias ---
    usadas = set(cat_fixas + cat_metodologia + cat_opps + cat_novatas)
    precisam_urgente = [t for t in todas_originais if t not in usadas and precisa_atualizar(t, mapa_atualizacao, agora_dt, sp_tz)]

    if len(precisam_urgente) >= 3:
        cat_aleatorias = random.sample(precisam_urgente, 3)
    else:
        cat_aleatorias = precisam_urgente

    fila = cat_fixas + cat_metodologia + cat_opps + cat_aleatorias + cat_novatas

    print(f"-> Ações Fixas na Fila: {cat_fixas}")
    if cat_metodologia: print(f"-> Metodologia (C3): {cat_metodologia} {'(Nova!)' if c3_nova else ''}")
    if cat_opps: print(f"-> Oportunidades garimpadas: {cat_opps}")
    if cat_novatas: print(f"-> 🌟 ALERTA CAÇADOR (Novas): {cat_novatas}")
    print(f"-> Varredura de Desatualizadas: {cat_aleatorias}")
    print(f"-> TOTAL PARA ATUALIZAR: {len(fila)} ações.\n")

    # 3. PROCESSAMENTO YAHOO FINANCE
    print("[4/5] Processando cruzamento de dados linha a linha...")
    batch_updates = []
    relatorio_opps = []
    relatorio_novatas = []
    relatorio_fixas_opps = [] 

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
            traducao_setores = {
                'Energy': 'Energia', 'Financial Services': 'Financeiro', 'Basic Materials': 'Materiais Básicos', 
                'Utilities': 'Utilidade Pública', 'Industrials': 'Indústria', 'Consumer Defensive': 'Consumo Defensivo', 
                'Consumer Cyclical': 'Consumo Cíclico', 'Healthcare': 'Saúde', 'Technology': 'Tecnologia', 
                'Communication Services': 'Comunicações', 'Real Estate': 'Imobiliário'
            }
            setor = traducao_setores.get(setor_eng, setor_eng)

            f = df.loc[ticker] if ticker in df.index else {}

            # RESTAURADO: Mapeamento completo e fiel das 32 colunas (B até AG)
            row_base = [
                setor,                                    # B: Setor
                preco,                                    # C: Preço
                formatar(f.get('Div.Yield', 0)),          # D: DY
                n_acoes,                                  # E: Nº Ações
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
                roa,                                      # U: ROA
                formatar(f.get('ROIC', 0)),               # V: ROIC
                0, 0, 0,                                  # W, X, Y
                formatar(f.get('Cresc. Rec.5a', 0)),      # Z: CAGR Rec
                0,                                        # AA: CAGR Lucros
                formatar(f.get('Liq.2meses', 0)),         # AB: Liq. Media
                vpa,                                      # AC: VPA
                lpa,                                      # AD: LPA
                peg_ratio,                                # AE: PEG Ratio
                valor_mercado,                            # AF: Valor Mercado
                f"{agora_sp} OK"                          # AG: Atualização
            ]

            if ticker in cat_novatas or (ticker == ticker_c3 and c3_nova):
                row_final = [ticker] + row_base
                range_update = f'A{linha_idx}:AG{linha_idx}'
            else:
                row_final = row_base
                range_update = f'B{linha_idx}:AG{linha_idx}'

            batch_updates.append({'range': range_update, 'values': [row_final]})

            # Logs de acompanhamento do terminal
            tag_extra = ""
            if ticker in opps_brutas:
                if ticker in config.FIXAS_ACOES: tag_extra = " (Ação Fixa)"
                elif ticker == ticker_c3: tag_extra = " (C3)"

            print(f"   ✅ [OK] {ticker} ({tag_extra or 'Processada'}) | Concluída com sucesso.")

            # RESTAURADO: Lógica e strings do Relatório Mestre do Telegram
            if ticker in opps_brutas:
                roe_wpp = formatar(f.get('ROE', 0)) * 100
                pl_wpp = formatar(f.get('P/L', 0))
                pvp_wpp = formatar(f.get('P/VP', 0))
                detalhe_msg = f"R$ {preco} | 🏢 {setor} (P/L: {pl_wpp} | P/VP: {pvp_wpp} | ROE: {roe_wpp:.1f}%)"

                if ticker in config.FIXAS_ACOES:
                    relatorio_fixas_opps.append(f"• *{ticker}* está barata!\n   Motivo: P/L ({pl_wpp}) abaixo de 12, P/VP ({pvp_wpp}) abaixo de 1.5 e ROE ({roe_wpp:.1f}%) Saudável.\n   🏢 Setor: {setor}")

                relatorio_opps.append(f"• *{ticker}*{tag_extra}: {detalhe_msg}")

            if ticker in cat_novatas:
                dy_wpp = formatar(f.get('Div.Yield', 0)) * 100
                roe_wpp = formatar(f.get('ROE', 0)) * 100
                relatorio_novatas.append(f"• *{ticker}*: R$ {preco} | 🏢 {setor} (DY: {dy_wpp:.1f}% | ROE: {roe_wpp:.1f}%)")

        except Exception as e:
            print(f"   ❌ [ERRO] Falha ao processar {ticker}: {e}")

    # Construção da mensagem final estruturada em Markdown
    msg_out = ""
    if batch_updates:
        msg_out = "🤖 *Relatório Mestre* 🤖\n\n"
        if relatorio_fixas_opps:
            msg_out += "🚨 *ALERTA VIP: AÇÕES FIXAS EM OPORTUNIDADE* 🚨\n" + "\n".join(relatorio_fixas_opps) + "\n\n"
        if cat_fixas: 
            msg_out += f"📌 *Fixas Processadas:*\n{', '.join(cat_fixas)}\n\n"
        if cat_metodologia: 
            status_c3 = "(Adicionada na Planilha!)" if c3_nova else ""
            msg_out += f"🔍 *Metodologia (C3):*\n{', '.join(cat_metodologia)} {status_c3}\n\n"
        if cat_aleatorias: 
            msg_out += f"🎲 *Varredura de Desatualizadas:*\n{', '.join(cat_aleatorias)}\n\n"
        if relatorio_opps: 
            msg_out += "🎯 *Ações em Oportunidade:*\n" + "\n".join(relatorio_opps) + "\n\n"
        if relatorio_novatas: 
            msg_out += "🌟 *NOVA PREVIDENCIÁRIA ADICIONADA:*\n" + "\n".join(relatorio_novatas)

    return batch_updates, msg_out, aba_base
