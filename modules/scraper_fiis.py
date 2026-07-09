import io
import random
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime
import pytz
import config
from modules.utils import formatar, precisa_atualizar
from modules.utils import get_request_with_retry

def classificar_tipo(setor):
    """
    Classifica automaticamente o FII baseado no Segmento Oficial.
    """
    s = str(setor).upper()
    if any(x in s for x in ["TÍTULOS E VAL", "PAPEL", "RECEBÍVEL"]): return "Papel"
    if any(x in s for x in ["FUNDO DE FUNDOS", "FOF"]): return "FOF"
    if any(x in s for x in ["HÍBRIDO", "MISTO"]): return "Híbrido"
    return "Tijolo"

def rodar_garimpo_fiis(planilha, agora_dt, agora_sp, sp_tz):
    print("🏢 [1/5] Iniciando motor de FIIs (Extração de Vacância e DY)...")
    aba_fiis = planilha.worksheet("BD_FIIs")

    try:
        url = "https://www.fundamentus.com.br/fii_resultado.php"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = get_request_with_retry(url, headers={'User-Agent': 'Mozilla/5.0'})
        df = pd.read_html(io.StringIO(response.text), decimal=',', thousands='.')[0]
        df['Papel'] = df['Papel'].str.strip().str.upper()
        df = df.set_index('Papel')
        
        # Garante a formatação numérica das colunas vitais vindas do Fundamentus
        for col in ['P/VP', 'Dividend Yield', 'Liquidez', 'Vacância Média', 'Valor de Mercado', 'Qtd de imóveis']:
            if col in df.columns:
                df[col] = df[col].apply(formatar)
    except Exception as e:
        print(f"❌ [ERRO FIIs] Falha no scraping base do Fundamentus: {e}")
        df = pd.DataFrame() 

    dados_planilha = aba_fiis.get_all_values()
    tickers_planilha = []
    mapa_atualizacao = {}
    
    for row in dados_planilha[1:]: 
        if row and row[0].strip():
            t = row[0].strip().upper()
            tickers_planilha.append(t)
            mapa_atualizacao[t] = row[15] if len(row) > 15 else ""

    # Puxa a lista VIP do config.py
    cat_fixas = [f for f in config.FIXAS_FIIS if f in tickers_planilha and precisa_atualizar(f, mapa_atualizacao, agora_dt, sp_tz)]
    
    # 🎯 FILTRO DE GARIMPO INSTITUCIONAL (ELITE)
    novatos_garimpados = []
    if not df.empty:
        df_cacador = df[
            (df['P/VP'] >= 0.85) & (df['P/VP'] <= 1.05) &  
            (df['Dividend Yield'] >= 0.08) &               
            (df['Liquidez'] >= 1000000) &                  
            (df['Vacância Média'] <= 0.10)                 
        ]
        oportunidades_gerais = df_cacador.index.tolist()
        novatos_garimpados = [fii for fii in oportunidades_gerais if fii not in tickers_planilha and fii not in cat_fixas][:3]
    
    usadas = set(cat_fixas + novatos_garimpados)
    precisam_urgente = [t for t in tickers_planilha if t not in usadas and precisa_atualizar(t, mapa_atualizacao, agora_dt, sp_tz)]
    cat_desatualizadas = random.sample(precisam_urgente, 2) if len(precisam_urgente) >= 2 else precisam_urgente

    fila_total = cat_fixas + novatos_garimpados + cat_desatualizadas

    if not fila_total:
        print("✅ [FIIs] Nenhuma atualização necessária (Trava de 2h ativa para todos os fundos).")
        return [], "", aba_fiis

    print(f"-> Fila de FIIs: Fixas {cat_fixas} | Garimpados {novatos_garimpados} | Desatualizados {cat_desatualizadas}")

    batch_updates = []
    relatorio_telegram = []
    proxima_linha_vazia = len(dados_planilha) + 1 

    for ticker in fila_total:
        try:
            # 📊 CAPTURA DA API INTERNACIONAL (YAHOO FINANCE)
            yf_info = yf.Ticker(f"{ticker}.SA").info
            preco = formatar(yf_info.get('currentPrice') or yf_info.get('regularMarketPrice') or 0)

            # 🏛️ CAPTURA DA BASE NACIONAL (FUNDAMENTUS)
            f = df.loc[ticker] if (not df.empty and ticker in df.index) else {}

            setor = f.get('Segmento', 'N/D') if isinstance(f.get('Segmento'), str) else 'N/D'
            
            # Correção cirúrgica de setor do GARE11 e VISC11 (Anti-mascaramento do Fundamentus)
            if ticker == "GARE11": 
                setor = "Galpões e Híbrido"
                tipo = "Tijolo"
            elif ticker == "VISC11":
                setor = "Shoppings"
                tipo = "Tijolo"
            else:
                tipo = classificar_tipo(setor)

            pvp = formatar(f.get('P/VP', 0))
            dy = formatar(f.get('Dividend Yield', 0))
            vacancia = formatar(f.get('Vacância Média', 0))
            liquidez = formatar(f.get('Liquidez', 0))
            valor_mercado = formatar(f.get('Valor de Mercado', 0))
            qtd_imoveis = formatar(f.get('Qtd de imóveis', 0)) 

            # 🧮 MÓDULO QUANTITATIVO PARALELO (CÁLCULOS MATEMÁTICOS DE REDUNDÂNCIA)
            vpa = preco / pvp if pvp > 0 else (valor_mercado / (valor_mercado / preco) if preco > 0 else 0)
            numero_cotas = valor_mercado / preco if preco > 0 else 0
            media_div_mensal = (preco * dy) / 12
            lucro_12m = valor_mercado * dy 

            walt = "Mapeamento em Curso"
            alavancagem = "Pendente"

            # =========================================================================
            # 🗺️ MAPEAMENTO COMPLETO DAS 16 COLUNAS DA ABA "BD_FIIs" (COLUNAS A ATÉ P)
            # =========================================================================
            row_update_completo = [
                ticker,                 # 🟢 Coluna A: Ticker do Ativo
                tipo,                   # 🟢 Coluna B: Tipo de FII (Classificação interna)
                setor,                  # 🟢 Coluna C: Segmento do Fundo (Fundamentus)
                preco,                  # 🔵 Coluna D: Cotação Atual (Yahoo Finance)
                numero_cotas,           # 🧮 Coluna E: Quantidade de Cotas (Calculado: Mkt Cap / Preço)
                pvp,                    # 🟢 Coluna F: P/VP Real (Fundamentus)
                dy,                     # 🟢 Coluna G: Dividend Yield 12 Meses (Fundamentus)
                vacancia,               # 🟢 Coluna H: Vacância Média - ETAPA 3 (Fundamentus)
                qtd_imoveis,            # 🟢 Coluna I: Quantidade Física de Imóveis - ETAPA 3 (Fundamentus)
                walt,                   # ⚪ Coluna J: WALT (Mapeamento Futuro)
                alavancagem,            # ⚪ Coluna K: Alavancagem / Dívida (Pendente Etapa 3)
                liquidez,               # 🟢 Coluna L: Liquidez Média Diária (Fundamentus)
                valor_mercado,          # 🟢 Coluna M: Patrimônio Líquido / Valor de Mercado (Fundamentus)
                vpa,                    # 🧮 Coluna N: Valor Patrimonial da Cota (Calculado: Preço / P/VP)
                lucro_12m,              # 🧮 Coluna O: Lucro Total Distribuído 12M (Calculado: Mkt Cap * DY)
                media_div_mensal,       # 🧮 Coluna P: Projeção de Dividendo Mensal/Cota (Calculado: (Preço*DY)/12)
                f"{agora_sp} OK"        # ⏰ Coluna Q: Carimbo de Data/Hora (Trava de 2 horas)
            ]
            
            # Se o ativo já existe, atualizamos a partir da coluna B para preservar o Ticker intacto na coluna A
            row_update_parcial = row_update_completo[1:] 

            if ticker in tickers_planilha:
                linha_idx = tickers_planilha.index(ticker) + 2
                batch_updates.append({'range': f'B{linha_idx}:Q{linha_idx}', 'values': [row_update_parcial]})
            else:
                batch_updates.append({'range': f'A{proxima_linha_vazia}:Q{proxima_linha_vazia}', 'values': [row_update_completo]})
                proxima_linha_vazia += 1
                
            if ticker in novatos_garimpados:
                relatorio_telegram.append(f"🌟 *NOVO FII GARIMPADO:* {ticker}\n   🏢 {tipo} ({setor}) | R$ {preco} | P/VP: {pvp:.2f} | DY: {dy*100:.1f}% | 🏚️ Vacância: {vacancia*100:.1f}%")

            print(f"   ✅ [OK] FII {ticker} processado com sucesso.")

        except Exception as e:
            print(f"   ❌ [ERRO] Falha ao processar {ticker}: {e}")

    msg_out = ""
    if batch_updates:
        if relatorio_telegram:
            msg_out = "🏢 *Relatório de FIIs* 🏢\n\n🎯 *OPORTUNIDADES DE RENDA (Desconto + Baixa Vacância)*\n" + "\n".join(relatorio_telegram) + "\n\n"

    return batch_updates, msg_out, aba_fiis
