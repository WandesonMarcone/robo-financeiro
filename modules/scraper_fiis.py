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
    """
    Classifica automaticamente o FII e atribui um Emoji visual para o Telegram.
    """
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
        response = get_request_with_retry(url, headers=headers)
        df = pd.read_html(io.StringIO(response.text), decimal=',', thousands='.')[0]
        df['Papel'] = df['Papel'].str.strip().str.upper()
        df = df.set_index('Papel')
        # Garante formatação inclusive do Backup de Cotação
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
            # O preço antigo dos FIIs está na Coluna D (índice 3)
            precos_antigos[t] = formatar(row[3]) if len(row) > 3 else 0 
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
        oportunidades_gerais = df_cacador.sort_values(by='Dividend Yield', ascending=False).index.tolist()
        novatos_garimpados = [fii for fii in oportunidades_gerais if fii not in tickers_planilha and fii not in cat_fixas][:3]

    usadas = set(cat_fixas + novatos_garimpados)
    precisam_urgente = [t for t in tickers_planilha if t not in usadas and precisa_atualizar(t, mapa_atualizacao, agora_dt, sp_tz)]
    cat_desatualizadas = random.sample(precisam_urgente, 2) if len(precisam_urgente) >= 2 else precisam_urgente

    fila_total = cat_fixas + novatos_garimpados + cat_desatualizadas
    if not fila_total: 
        print("✅ [FIIs] Nenhuma atualização necessária (Trava de 2h ativa para todos).")
        return [], "", aba_fiis
    
    # Este print vai mostrar exatamente o que o robô escolheu para trabalhar no log do GitHub
    print(f"-> Fila de FIIs: Fixas {cat_fixas} | Garimpados {novatos_garimpados} | Desatualizados {cat_desatualizadas}")

    batch_updates = []
    relatorio_fixas = []
    relatorio_opps = []
    relatorio_atualizados = []
    relatorio_fixas_opps = []
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

            # Correção Cirúrgica Anti-Fundamentus
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

            # =========================================================================
            # 🗺️ MAPEAMENTO COMPLETO DAS 16 COLUNAS DA ABA "BD_FIIs" (COLUNAS A ATÉ P)
            # =========================================================================
            row_update_completo = [
                ticker,                 # 🟢 Coluna A: Ticker do Ativo
                tipo,                   # 🟢 Coluna B: Tipo de FII (Classificação interna)
                setor,                  # 🟢 Coluna C: Segmento do Fundo (Fundamentus)
                preco,                  # 🔵 Coluna D: Cotação Atual (Yahoo Finance/Fundamentus)
                numero_cotas,           # 🧮 Coluna E: Quantidade de Cotas (Calculado)
                pvp,                    # 🟢 Coluna F: P/VP Real (Fundamentus)
                dy,                     # 🟢 Coluna G: Dividend Yield 12 Meses (Fundamentus)
                vacancia,               # 🟢 Coluna H: Vacância Média (Fundamentus)
                qtd_imoveis,            # 🟢 Coluna I: Quantidade Física de Imóveis (Fundamentus)
                "Mapeamento em Curso",  # ⚪ Coluna J: WALT 
                "Pendente",             # ⚪ Coluna K: Alavancagem / Dívida 
                liquidez,               # 🟢 Coluna L: Liquidez Média Diária (Fundamentus)
                valor_mercado,          # 🟢 Coluna M: Patrimônio Líquido (Fundamentus)
                vpa,                    # 🧮 Coluna N: Valor Patrimonial da Cota (Calculado)
                lucro_12m,              # 🧮 Coluna O: Lucro Total Distribuído 12M (Calculado)
                media_div_mensal,       # 🧮 Coluna P: Projeção de Dividendo Mensal/Cota (Calculado)
                f"{agora_sp} OK"        # ⏰ Coluna Q: Carimbo de Data/Hora (Trava)
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

            # Só mostra a vacância se for fundo de Tijolo (Oculta para fundos de Papel)
            txt_vacancia = f" | 🏚️ Vacância: {vacancia*100:.1f}%" if tipo == "Tijolo" else ""

            # Se for Garimpo Novo (nunca esteve na planilha, mostra só preço atual)
            if ticker in novatos_garimpados:
                texto_ativo = f"{emoji} *{ticker}* ({tipo})\n   R$ {preco:.2f}\n   P/VP: {pvp:.2f} | DY: {dy*100:.1f}%{txt_vacancia}"
                relatorio_opps.append(texto_ativo)

            # Se for Fixo (Sempre mostra a variação)
            elif ticker in cat_fixas:
                texto_ativo = f"{emoji} *{ticker}* ({tipo})\n   R$ {preco_velho:.2f} ➔ R$ {preco:.2f} {icone_variacao}\n   P/VP: {pvp:.2f} | DY: {dy*100:.1f}%{txt_vacancia}"

                # ALERTA MÁXIMO: Fixo que entrou em preço de oportunidade
                if ticker in oportunidades_gerais:
                    relatorio_fixas_opps.append(f"🚨 *{ticker} ENTROU EM DESCONTO!* 🚨\n   {texto_ativo}")
                else:
                    relatorio_fixas.append(texto_ativo)

            # Outros Atualizados (Desatualizadas)
            else:
                texto_ativo = f"{emoji} *{ticker}* ({tipo})\n   R$ {preco_velho:.2f} ➔ R$ {preco:.2f} {icone_variacao}\n   P/VP: {pvp:.2f} | DY: {dy*100:.1f}%{txt_vacancia}"
                relatorio_atualizados.append(texto_ativo)

            print(f"   ✅ [OK] FII {ticker} processado.")

        except Exception as e:
            print(f"   ❌ [ERRO] Falha {ticker}: {e}")

    # --- MONTAGEM ORGANIZADA E MODULAR DO TELEGRAM ---
    msg_blocos = ["🏢 *MOVIMENTAÇÃO DE FIIs* 🏢"]

    if relatorio_fixas_opps:
        bloco = "🏆 *ALERTA VIP: FIXAS EM OPORTUNIDADE* 🏆\n" + "\n\n".join(relatorio_fixas_opps)
        msg_blocos.append(bloco)

    if relatorio_fixas:
        bloco = "📌 *CARTEIRA FIXA:*\n" + "\n\n".join(relatorio_fixas)
        msg_blocos.append(bloco)

    if relatorio_opps:
        bloco = "🎯 *TOP OPORTUNIDADES:*\n" + "\n\n".join(relatorio_opps)
        msg_blocos.append(bloco)

    if relatorio_atualizados:
        bloco = "🔄 *ATUALIZAÇÕES DE FIIs:*\n" + "\n\n".join(relatorio_atualizados)
        msg_blocos.append(bloco)

    msg_out = ""
    if batch_updates:
        # Une os blocos com a linha divisória clara
        msg_out = "\n\n➖➖➖➖➖➖➖➖➖➖\n\n".join(msg_blocos)

    return batch_updates, msg_out, aba_fiis