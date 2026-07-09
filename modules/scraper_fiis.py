import pandas as pd
import yfinance as yf
import requests
import io
import random
from datetime import datetime
import pytz
import config
from modules.utils import formatar

def classificar_tipo(setor):
    """
    Classifica automaticamente o FII baseado no Segmento Oficial.
    """
    s = str(setor).upper()
    if any(x in s for x in ["TÍTULOS E VAL", "PAPEL", "RECEBÍVEL"]): return "Papel"
    if any(x in s for x in ["FUNDO DE FUNDOS", "FOF"]): return "FOF"
    if any(x in s for x in ["HÍBRIDO", "MISTO"]): return "Híbrido"
    # Se não é Papel nem FOF, só sobra cimento, tijolo e galpão
    return "Tijolo"

def rodar_garimpo_fiis(planilha, agora_dt, agora_sp, sp_tz):
    print("🏢 [1/5] Iniciando motor de FIIs (Extração de Vacância e DY)...")
    aba_fiis = planilha.worksheet("BD_FIIs")

    try:
        url = "https://www.fundamentus.com.br/fii_resultado.php"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        df = pd.read_html(io.StringIO(response.text), decimal=',', thousands='.')[0]
        df['Papel'] = df['Papel'].str.strip().str.upper()
        df = df.set_index('Papel')
        
        # O Fundamentus possui a coluna 'Qtd de imóveis'. Vamos puxar e garantir que é lida!
        for col in ['P/VP', 'Dividend Yield', 'Liquidez', 'Vacância Média', 'Valor de Mercado', 'Qtd de imóveis']:
            if col in df.columns:
                df[col] = df[col].apply(formatar)
    except Exception as e:
        print(f"❌ [ERRO FIIs] Falha no scraping base do Fundamentus: {e}")
        # Se cair, retorna DataFrame vazio para não crashar, mas perdemos a vacância momentaneamente
        df = pd.DataFrame() 

    dados_planilha = aba_fiis.get_all_values()
    tickers_planilha = []
    mapa_atualizacao = {}
    
    for row in dados_planilha[1:]: 
        if row and row[0].strip():
            t = row[0].strip().upper()
            tickers_planilha.append(t)
            # Verifica a coluna P (índice 15) que regista a última atualização
            mapa_atualizacao[t] = row[15] if len(row) > 15 else ""

    from modules.utils import precisa_atualizar
    cat_fixas = [f for f in config.FIXAS_FIIS if f in tickers_planilha and precisa_atualizar(f, mapa_atualizacao, agora_dt, sp_tz)]
    
    # 🎯 NOVO FILTRO DE GARIMPO INSTITUCIONAL (ELITE)
    novatos_garimpados = []
    if not df.empty:
        df_cacador = df[
            (df['P/VP'] >= 0.85) & (df['P/VP'] <= 1.05) &  # Baixei um pouco o piso para caçar pechinchas, mas não o lixo
            (df['Dividend Yield'] >= 0.08) &               # 8% mínimo ao ano é mais realista no ciclo atual de juros
            (df['Liquidez'] >= 1000000) &                  # 1 Milhão diário já garante saída de emergência
            (df['Vacância Média'] <= 0.10)                 # Tolerância máxima de 10% de imóveis vazios
        ]
        oportunidades_gerais = df_cacador.index.tolist()
        novatos_garimpados = [fii for fii in oportunidades_gerais if fii not in tickers_planilha and fii not in cat_fixas][:3]
    
    usadas = set(cat_fixas + novatos_garimpados)
    precisam_urgente = [t for t in tickers_planilha if t not in usadas and precisa_atualizar(t, mapa_atualizacao, agora_dt, sp_tz)]
    
    cat_desatualizadas = random.sample(precisam_urgente, 2) if len(precisam_urgente) >= 2 else precisam_urgente

    fila_total = cat_fixas + novatos_garimpados + cat_desatualizadas

    if not fila_total:
        print("✅ [FIIs] Nenhuma atualização necessária (Trava de 2h ativa para todos os fundos).")
        return ""

    print(f"-> Fila de FIIs: Fixas {cat_fixas} | Garimpados {novatos_garimpados} | Desatualizados {cat_desatualizadas}")

    batch_updates = []
    relatorio_telegram = []
    proxima_linha_vazia = len(dados_planilha) + 1 

    for ticker in fila_total:
        try:
            # 1. Puxa Cotação Atualizada a cada segundo no Terminal Global (YF)
            yf_info = yf.Ticker(f"{ticker}.SA").info
            preco = formatar(yf_info.get('currentPrice') or yf_info.get('regularMarketPrice') or 0)

            # 2. Puxa os dados Estruturais do Fundamentus
            f = df.loc[ticker] if (not df.empty and ticker in df.index) else {}

            setor = f.get('Segmento', 'N/D') if isinstance(f.get('Segmento'), str) else 'N/D'
            
            # ⚠️ CORREÇÃO MANUAL PARA O SEU GARE11 E VISC11 (Impedindo o erro do Fundamentus)
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
            qtd_imoveis = formatar(f.get('Qtd de imóveis', 0)) # ETAPA 3 CONCLUÍDA!

            # Cálculos Matemáticos Automáticos
            vpa = preco / pvp if pvp > 0 else 0
            numero_cotas = valor_mercado / preco if preco > 0 else 0
            media_div_mensal = (preco * dy) / 12
            lucro_12m = valor_mercado * dy 

            walt = "Mapeamento em Curso"
            
            # Mapeamento exato nas 16 colunas da aba de FIIs (A a P)
            row_update_completo = [
                ticker,                 # A: Ticker
                tipo,                   # B: Tipo (Tijolo, Papel, FOF)
                setor,                  # C: Segmento
                preco,                  # D: Preço Atual (Yahoo Finance)
                numero_cotas,           # E: Qtd de Cotas
                pvp,                    # F: P/VP
                dy,                     # G: Dividend Yield Anual
                vacancia,               # H: Vacância Média (Etapa 3!)
                qtd_imoveis,            # I: Quantidade de Imóveis (Etapa 3!)
                alavancagem,            # J: (Deixando espaço para dívida futura)
                liquidez,               # K: Liquidez Diária
                valor_mercado,          # L: Patrimônio / Valor de Mercado
                vpa,                    # M: Valor Patrimonial da Cota
                lucro_12m,              # N: Total Distribuído 12M
                media_div_mensal,       # O: Projeção de Renda Mensal/Cota
                f"{agora_sp} OK"        # P: Timestamp (Trava)
            ]
            
            row_update_parcial = row_update_completo[1:] 

            if ticker in tickers_planilha:
                linha_idx = tickers_planilha.index(ticker) + 2
                batch_updates.append({'range': f'B{linha_idx}:P{linha_idx}', 'values': [row_update_parcial]})
            else:
                batch_updates.append({'range': f'A{proxima_linha_vazia}:P{proxima_linha_vazia}', 'values': [row_update_completo]})
                proxima_linha_vazia += 1
                
            if ticker in novatos_garimpados:
                relatorio_telegram.append(f"🌟 *NOVO FII GARIMPADO:* {ticker}\n   🏢 {tipo} ({setor}) | R$ {preco} | P/VP: {pvp:.2f} | DY: {dy*100:.1f}% | 🏚️ Vacância: {vacancia*100:.1f}%")

            print(f"   ✅ [OK] FII {ticker} processado.")

        except Exception as e:
            print(f"   ❌ [ERRO] Falha ao processar {ticker}: {e}")

    msg_out = ""
    if batch_updates:
        msg_out = "🏢 *Relatório de FIIs* 🏢\n\n"
        if relatorio_telegram:
            msg_out += "🎯 *OPORTUNIDADES DE RENDA (Desconto + Baixa Vacância)*\n" + "\n".join(relatorio_telegram) + "\n\n"

    return batch_updates, msg_out, aba_fiis
