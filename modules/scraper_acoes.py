import io
import random
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime
import config
from modules.utils import (
    converter_numero,
    eh_valido,
    precisa_atualizar,
    get_request_with_retry,
)
from config import MAPA_SETORES_B3

def classificar_setor_por_mapa(ticker):
    """
    Varre o mapa fixo do config.py e devolve (Macro_Setor, Sub_Setor).
    Se a ação não estiver no mapa, devolve "Outros".
    """
    ticker_limpo = ticker.strip().upper()

    for macro, subsetores in MAPA_SETORES_B3.items():
        for sub, lista_tickers in subsetores.items():
            if ticker_limpo in lista_tickers:
                return macro, sub

    # Se a ação não estiver mapeada no config.py
    return "Outros", "Não Classificado"

def rodar_garimpo_acoes(planilha, agora_dt, agora_sp, sp_tz):
    print("📈 [1/5] Iniciando auditoria completa de Ações...")
    aba_base = planilha.worksheet("BD_Acoes")

    try:
        # Sem "www": o certificado TLS do Fundamentus só cobre o domínio raiz
        # (fundamentus.com.br); "www" causa SSLCertVerificationError (hostname
        # mismatch). Correção segura, mantendo a validação SSL ativa.
        url = "https://fundamentus.com.br/resultado.php"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8'
        }
        response = get_request_with_retry(url, headers=headers)
        
        # 🟢 ALTERAÇÃO 1: Adicionado decimal e thousands para ler formato BR
        df = pd.read_html(io.StringIO(response.text), decimal=',', thousands='.')[0]
        
        df['Papel'] = df['Papel'].str.strip().str.upper()
        df = df.set_index('Papel')

        colunas_numericas = [
            'Cotação', 'P/L', 'P/VP', 'Div.Yield', 'ROE', 'Liq.2meses',
            'P/Ativo', 'Mrg Bruta', 'Mrg Ebit', 'Mrg. Líq.', 'P/EBIT',
            'EV/EBIT', 'Dív.Líq/ Patrim.', 'PSR', 'P/Cap.Giro',
            'P/Ativ Circ.Liq', 'Liq. Corr.', 'ROIC', 'Cresc. Rec.5a',
        ]
        for col in colunas_numericas:
            if col in df.columns:
                df[col] = df[col].map(converter_numero)
            
    except Exception as e:
        print(f"⚠️ Fundamentus indisponível: {e}. Alternando para Yahoo.")
        df = pd.DataFrame() 

    dados_planilha = aba_base.get_all_values()
    # Linha duplicada no original removida (dados_planilha = aba_base.get_all_values())
    todas_originais, mapa_atualizacao, precos_antigos = [], {}, {}

    for row in dados_planilha[1:]:
        if row and row[0].strip() and not row[0].replace(',', '').replace('.', '').isnumeric():
            t = row[0].strip().upper()
            todas_originais.append(t)

            # Lógica de limpeza para o preço na Coluna C (índice 2)
            preco_planilha = converter_numero(row[2] if len(row) > 2 else None)
            if eh_valido(preco_planilha):
                precos_antigos[t] = preco_planilha

            # Mapeamento da Coluna AG (índice 32)
            mapa_atualizacao[t] = row[32] if len(row) > 32 else ""

    todas = list(todas_originais)
    cat_fixas = [f for f in config.FIXAS_ACOES if f in todas and precisa_atualizar(f, mapa_atualizacao, agora_dt, sp_tz)]

    opps_brutas, cat_novatas = [], []
    if not df.empty:
        opps_brutas = df[
            (df['P/L'] > 0) & (df['P/L'] < 12) & (df['P/VP'] < 1.5) & (df['ROE'] >= 0.08)
        ].index.tolist()
        cat_opps = [o for o in opps_brutas if o in todas_originais and o not in cat_fixas and precisa_atualizar(o, mapa_atualizacao, agora_dt, sp_tz)][:5]
        # Adequação dos filtros matemáticos pois as porcentagens viraram decimais puros (Ex: 6.0% agora é 0.06)
        candidatas = df[(df['P/L']>=2)&(df['P/L']<=15)&(df['P/VP']>=0.2)&(df['P/VP']<=1.5)&(df['Div.Yield']>=0.06)&(df['ROE']>=0.10)].index.tolist()
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
            # 🟢 ALTERAÇÃO 3: Inserção do Sufixo da B3 para o Yahoo Finance (.SA)
            yf_info = yf.Ticker(f"{ticker}.SA").info or {}
            macro_setor, sub_setor = classificar_setor_por_mapa(ticker)
            setor = macro_setor

            fundamentus_ok = (not df.empty) and (ticker in df.index)
            f = {}
            if fundamentus_ok:
                f = df.loc[ticker]
                if isinstance(f, pd.DataFrame):
                    f = f.iloc[0]

            def _fund(col):
                return converter_numero(f.get(col)) if fundamentus_ok else float("nan")

            preco_yf = converter_numero(yf_info.get("currentPrice"))
            if not eh_valido(preco_yf):
                preco_yf = converter_numero(yf_info.get("regularMarketPrice"))
            if not (eh_valido(preco_yf) and preco_yf > 0):
                preco_yf = None
            preco_fundamentus = _fund("Cotação")
            if not (eh_valido(preco_fundamentus) and preco_fundamentus > 0):
                preco_fundamentus = None
            preco = preco_yf if preco_yf is not None else preco_fundamentus

            lpa_yf = converter_numero(yf_info.get("trailingEps"))
            vpa_yf = converter_numero(yf_info.get("bookValue"))
            pl = _fund("P/L")
            if not eh_valido(pl):
                pl = (
                    (preco / lpa_yf)
                    if (eh_valido(preco) and eh_valido(lpa_yf) and lpa_yf != 0)
                    else float("nan")
                )
            pvp = _fund("P/VP")
            if not eh_valido(pvp):
                pvp = (
                    (preco / vpa_yf)
                    if (eh_valido(preco) and eh_valido(vpa_yf) and vpa_yf != 0)
                    else float("nan")
                )
            roe = _fund("ROE")
            dy = _fund("Div.Yield")
            qtd_acoes = converter_numero(yf_info.get("sharesOutstanding"))
            p_ativo = _fund("P/Ativo")
            marg_bruta = _fund("Mrg Bruta")
            marg_ebit = _fund("Mrg Ebit")
            marg_liq = _fund("Mrg. Líq.")
            p_ebit = _fund("P/EBIT")
            ev_ebit = _fund("EV/EBIT")
            div_liq_patrimonio = _fund("Dív.Líq/ Patrim.")
            psr = _fund("PSR")
            p_cap_giro = _fund("P/Cap.Giro")
            p_at_circ_liq = _fund("P/Ativ Circ.Liq")
            liq_corrente = _fund("Liq. Corr.")
            roa = converter_numero(yf_info.get("returnOnAssets"))
            roic = _fund("ROIC")
            cagr_rec_5a = _fund("Cresc. Rec.5a")
            liq_media = _fund("Liq.2meses")
            peg_ratio = converter_numero(yf_info.get("trailingPegRatio"))
            valor_mercado = converter_numero(yf_info.get("marketCap"))

            valores = {}
            if ticker in cat_novatas:
                valores["A"] = ticker
            valores["B"] = setor
            if eh_valido(preco):
                valores["C"] = preco
            if eh_valido(dy):
                valores["D"] = dy
            if eh_valido(qtd_acoes):
                valores["E"] = qtd_acoes
            if eh_valido(pl):
                valores["F"] = pl
            if eh_valido(pvp):
                valores["G"] = pvp
            if eh_valido(p_ativo):
                valores["H"] = p_ativo
            if eh_valido(marg_bruta):
                valores["I"] = marg_bruta
            if eh_valido(marg_ebit):
                valores["J"] = marg_ebit
            if eh_valido(marg_liq):
                valores["K"] = marg_liq
            if eh_valido(p_ebit):
                valores["L"] = p_ebit
            if eh_valido(ev_ebit):
                valores["M"] = ev_ebit
            if eh_valido(div_liq_patrimonio):
                valores["N"] = div_liq_patrimonio
                valores["O"] = div_liq_patrimonio
            if eh_valido(psr):
                valores["P"] = psr
            if eh_valido(p_cap_giro):
                valores["Q"] = p_cap_giro
            if eh_valido(p_at_circ_liq):
                valores["R"] = p_at_circ_liq
            if eh_valido(liq_corrente):
                valores["S"] = liq_corrente
            if eh_valido(roe):
                valores["T"] = roe
            if eh_valido(roa):
                valores["U"] = roa
            if eh_valido(roic):
                valores["V"] = roic
            if eh_valido(cagr_rec_5a):
                valores["Z"] = cagr_rec_5a
            if eh_valido(liq_media):
                valores["AB"] = liq_media
            if eh_valido(vpa_yf):
                valores["AC"] = vpa_yf
            if eh_valido(lpa_yf):
                valores["AD"] = lpa_yf
            if eh_valido(peg_ratio):
                valores["AE"] = peg_ratio
            if eh_valido(valor_mercado):
                valores["AF"] = valor_mercado
            if fundamentus_ok:
                valores["AG"] = agora_sp

            for coluna, valor in valores.items():
                batch_updates.append(
                    {"range": f"{coluna}{linha_idx}", "values": [[valor]]}
                )

            preco_velho = precos_antigos.get(ticker)
            preco_exib = preco if eh_valido(preco) else preco_velho
            p_v = preco_velho if eh_valido(preco_velho) else preco_exib
            pl_txt = f"{pl:.1f}" if eh_valido(pl) else "N/D"
            pvp_txt = f"{pvp:.2f}" if eh_valido(pvp) else "N/D"
            roe_txt = f"{roe*100:.1f}%" if eh_valido(roe) else "N/D"
            if eh_valido(preco_exib) and eh_valido(p_v):
                ico = "📈" if preco_exib > p_v else ("📉" if preco_exib < p_v else "➖")
                faixa_preco = f"R$ {p_v:.2f} ➔ R$ {preco_exib:.2f} {ico}"
            elif eh_valido(preco_exib):
                faixa_preco = f"R$ {preco_exib:.2f}"
            else:
                faixa_preco = "N/D"
            linha_ind = f"P/L: {pl_txt} | P/VP: {pvp_txt} | ROE: {roe_txt}"

            if ticker in config.FIXAS_ACOES:
                txt = f"🏭 *{ticker}*\n   {faixa_preco}\n   {linha_ind}"
                if ticker in opps_brutas:
                    relatorio_fixas_opps.append(f"🚨 *{ticker} EM OPORTUNIDADE!* 🚨\n{txt}")
                else:
                    relatorio_fixas.append(txt)
            elif ticker in opps_brutas:
                relatorio_opps.append(
                    f"🏭 *{ticker}* (Oportunidade)\n   {faixa_preco}\n   {linha_ind}"
                )
            elif ticker in cat_novatas:
                relatorio_novatas.append(
                    f"🏭 *{ticker}* (Nova Garimpada)\n   {faixa_preco}\n   {linha_ind}"
                )
            else:
                relatorio_atualizados.append(
                    f"🏭 *{ticker}*\n   {faixa_preco}\n   {linha_ind}"
                )

            print(f"   ✅ [OK] {ticker} mapeado e processado.")
        except Exception as e:
            print(f"   ❌ [ERRO] Falha {ticker}: {e}")
            try:
                aba_logs = planilha.worksheet("BD_Logs")
                aba_logs.append_row([str(datetime.now(sp_tz)), f"Ações: {ticker}", str(e)])
            except Exception as log_error:
                print(f"   ⚠️ Não foi possível gravar o log: {log_error}")

            # --------------------------

    # --- MONTAGEM MODULAR COM SEPARADOR ---
    msg_blocos = ["🤖 *MOVIMENTAÇÃO DE AÇÕES* 🤖"]
    if relatorio_fixas_opps: msg_blocos.append("🏆 *ALERTA VIP (Fixas em Oportunidade):*\n" + "\n\n".join(relatorio_fixas_opps))
    if relatorio_fixas: msg_blocos.append("📌 *CARTEIRA FIXA:*\n" + "\n\n".join(relatorio_fixas))
    if relatorio_opps: msg_blocos.append("🎯 *OPORTUNIDADES:*\n" + "\n\n".join(relatorio_opps))
    if relatorio_novatas: msg_blocos.append("🌟 *GARIMPADAS:*\n" + "\n\n".join(relatorio_novatas))
    if relatorio_atualizados: msg_blocos.append("🔄 *OUTRAS ATUALIZADAS:*\n" + "\n\n".join(relatorio_atualizados))

    msg_out = "\n\n➖➖➖➖➖➖➖➖➖➖\n\n".join(msg_blocos) if batch_updates else ""

    return batch_updates, msg_out, aba_base