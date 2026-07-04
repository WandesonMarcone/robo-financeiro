import pandas as pd
import yfinance as yf
import requests
import io
import random
from datetime import datetime
import pytz

# --- CONFIGURAÇÕES DE FIIs ---
FIXAS_FIIS = ["GARE11", "MXRF11", "GGRC11"]

def formatar_fii(val):
    try:
        if isinstance(val, str):
            is_percent = '%' in val
            val = val.replace('%', '').replace('.', '').replace(',', '.')
            numero = float(val)
            return numero / 100 if is_percent else numero
        return float(val) if pd.notna(val) else 0.0
    except:
        return 0.0

def classificar_tipo(setor):
    s = str(setor).upper()
    # Correção do mapeamento de nomes do Fundamentus
    if any(x in s for x in ["TÍTULO", "PAPEL", "RECEBÍVEL", "VAL. MOB"]): return "Papel"
    if any(x in s for x in ["FUNDO DE FUNDOS", "FOF", "MISTO", "HÍBRIDO"]): return "FOF / Misto"
    if "N/D" in s or "OUTROS" in s: return "Híbrido/Outros"
    return "Tijolo"

def precisa_atualizar_fii(ticker, mapa_atualizacao, agora_dt, sp_tz):
    if ticker not in mapa_atualizacao:
        return True 

    val = str(mapa_atualizacao[ticker]).strip()
    if 'OK' not in val:
        return True 

    val = val.replace('OK', '').strip() 
    try:
        dia_mes, horario = val.split(' ')
        dia, mes = dia_mes.split('/')
        hora, minuto = horario.split(':')

        dt_af = datetime(agora_dt.year, int(mes), int(dia), int(hora), int(minuto))
        dt_af = sp_tz.localize(dt_af)

        if dt_af > agora_dt: 
            dt_af = dt_af.replace(year=agora_dt.year - 1)

        if (agora_dt - dt_af).total_seconds() < 7200:
            return False 
    except:
        pass 

    return True

def atualizar_fiis(aba_fiis):
    print("🏢 [LOG FIIs] Iniciando motor de FIIs (Filtro Antilixo Ativado)...")

    sp_tz = pytz.timezone('America/Sao_Paulo')
    agora_dt = datetime.now(sp_tz)
    data_atual = agora_dt.strftime("%d/%m %H:%M OK")

    try:
        url = "https://www.fundamentus.com.br/fii_resultado.php"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        df = pd.read_html(io.StringIO(response.text), decimal=',', thousands='.')[0]
        df['Papel'] = df['Papel'].str.strip().str.upper()
        df = df.set_index('Papel')
        
        for col in ['P/VP', 'Dividend Yield', 'Liquidez', 'Vacância Média', 'Valor de Mercado']:
            if col in df.columns:
                df[col] = df[col].apply(formatar_fii)
    except Exception as e:
        print(f"❌ [ERRO FIIs] Falha no scraping base: {e}")
        return ""

    dados_planilha = aba_fiis.get_all_values()
    tickers_planilha = []
    mapa_atualizacao = {}
    
    for row in dados_planilha[1:]: 
        if row and row[0].strip():
            t = row[0].strip().upper()
            tickers_planilha.append(t)
            mapa_atualizacao[t] = row[15] if len(row) > 15 else ""

    cat_fixas = [f for f in FIXAS_FIIS if precisa_atualizar_fii(f, mapa_atualizacao, agora_dt, sp_tz)]
    
    # 🎯 NOVO FILTRO DE GARIMPO INSTITUCIONAL
    df_cacador = df[
        (df['P/VP'] >= 0.85) & (df['P/VP'] <= 0.99) & 
        (df['Dividend Yield'] >= 0.08) & (df['Dividend Yield'] <= 0.14) &
        (df['Liquidez'] >= 1000000) &
        (df['Vacância Média'] <= 0.15)
    ]
    oportunidades_gerais = df_cacador.index.tolist()
    novatos_garimpados = [fii for fii in oportunidades_gerais if fii not in tickers_planilha and fii not in cat_fixas][:3]
    
    usadas = set(cat_fixas + novatos_garimpados)
    precisam_urgente = [t for t in tickers_planilha if t not in usadas and precisa_atualizar_fii(t, mapa_atualizacao, agora_dt, sp_tz)]
    
    if len(precisam_urgente) >= 2:
        cat_desatualizadas = random.sample(precisam_urgente, 2)
    else:
        cat_desatualizadas = precisam_urgente

    fila_total = cat_fixas + novatos_garimpados + cat_desatualizadas

    if not fila_total:
        print("✅ [FIIs] Nenhuma atualização necessária (Trava de 2h ativa para todos).")
        return ""

    print(f"-> Fila de FIIs: Fixas {cat_fixas} | Garimpados {novatos_garimpados} | Desatualizados {cat_desatualizadas}")

    batch_updates = []
    relatorio_telegram = []
    proxima_linha_vazia = len(dados_planilha) + 1 

    for ticker in fila_total:
        try:
            yf_info = yf.Ticker(f"{ticker}.SA").info
            preco = formatar_fii(yf_info.get('currentPrice') or yf_info.get('regularMarketPrice') or 0)

            f = df.loc[ticker] if ticker in df.index else {}

            setor = f.get('Segmento', 'N/D') if isinstance(f.get('Segmento'), str) else 'N/D'
            tipo = classificar_tipo(setor)
            pvp = f.get('P/VP', 0)
            dy = f.get('Dividend Yield', 0)
            vacancia = f.get('Vacância Média', 0)
            liquidez = f.get('Liquidez', 0)
            valor_mercado = f.get('Valor de Mercado', 0)

            vpa = preco / pvp if pvp > 0 else 0
            numero_cotas = valor_mercado / preco if preco > 0 else 0
            media_div_mensal = (preco * dy) / 12
            lucro_12m = valor_mercado * dy 

            walt = "Pendente (Etapa 3)"
            alavancagem = "Pendente (Etapa 3)"

            row_update_completo = [
                ticker, tipo, setor, preco, numero_cotas, pvp, dy, vacancia, 
                walt, alavancagem, liquidez, valor_mercado, vpa, lucro_12m, media_div_mensal, data_atual
            ]
            
            row_update_parcial = row_update_completo[1:] 

            if ticker in tickers_planilha:
                linha_idx = tickers_planilha.index(ticker) + 2
                batch_updates.append({'range': f'B{linha_idx}:P{linha_idx}', 'values': [row_update_parcial]})
            else:
                batch_updates.append({'range': f'A{proxima_linha_vazia}:P{proxima_linha_vazia}', 'values': [row_update_completo]})
                proxima_linha_vazia += 1
                
            if ticker in novatos_garimpados:
                relatorio_telegram.append(f"🌟 *NOVO FII GARIMPADO:* {ticker}\n   🏢 {tipo} | R$ {preco} | P/VP: {pvp:.2f} | DY: {dy*100:.1f}%")

            print(f"   ✅ [OK] FII {ticker} processado.")

        except Exception as e:
            print(f"   ❌ [ERRO] Falha ao processar {ticker}: {e}")

    if batch_updates:
        aba_fiis.batch_update(batch_updates, value_input_option='USER_ENTERED')
        print(f"💾 [FIIs] {len(batch_updates)} FIIs atualizados na planilha.")

    if relatorio_telegram:
        msg = "🏢 *FIIs CAÇADOR (Ativos Premium com Desconto)* 🏢\n" + "\n".join(relatorio_telegram) + "\n\n"
        return msg

    return ""