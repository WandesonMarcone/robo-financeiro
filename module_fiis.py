import pandas as pd
import yfinance as yf
import requests
import io
from datetime import datetime
import pytz

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
    if any(x in s for x in ["TÍTULO", "PAPEL", "RECEBÍVEL"]): return "Papel"
    if any(x in s for x in ["FUNDO DE FUNDOS", "FOF", "MISTO"]): return "FOF / Misto"
    return "Tijolo"

def atualizar_fiis(aba_fiis):
    print("🏢 [LOG FIIs] Iniciando motor de FIIs com MODO CAÇADOR...")

    # 1. Busca TODOS os FIIs do mercado no Fundamentus
    try:
        url = "https://www.fundamentus.com.br/fii_resultado.php"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        df = pd.read_html(io.StringIO(response.text), decimal=',', thousands='.')[0]
        df['Papel'] = df['Papel'].str.strip().str.upper()
        df = df.set_index('Papel')
        
        # Formatar colunas base para o filtro de garimpo funcionar matematicamente
        for col in ['P/VP', 'Dividend Yield', 'Liquidez', 'Vacância Média', 'Valor de Mercado']:
            if col in df.columns:
                df[col] = df[col].apply(formatar_fii)
    except Exception as e:
        print(f"❌ [ERRO FIIs] Falha no scraping base: {e}")
        return ""

    # 2. Mapeia a sua planilha para saber o que você JÁ TEM
    dados_planilha = aba_fiis.get_all_values()
    tickers_planilha = []
    
    for row in dados_planilha[1:]: # Pula o cabeçalho
        if row and row[0].strip():
            tickers_planilha.append(row[0].strip().upper())
            
    # 3. O GARIMPO (A Inteligência do Caçador)
    # Filtro: P/VP barato (0.4 a 1.0), DY alto (> 9%) e Liquidez viável (> 500k)
    df_cacador = df[
        (df['P/VP'] >= 0.40) & (df['P/VP'] <= 1.00) & 
        (df['Dividend Yield'] >= 0.09) & 
        (df['Liquidez'] >= 500000)
    ]
    
    oportunidades_gerais = df_cacador.index.tolist()
    
    # Isola apenas os FIIs bons que AINDA NÃO ESTÃO na sua planilha (Pega no máx 3 por vez)
    novatos_garimpados = [fii for fii in oportunidades_gerais if fii not in tickers_planilha][:3]
    
    if novatos_garimpados:
        print(f"🎯 [FIIs] O Robô garimpou {len(novatos_garimpados)} novos FIIs: {novatos_garimpados}")
        
    # A fila final de processamento = O que você já tem + O que o robô achou hoje
    fila_total = tickers_planilha + novatos_garimpados

    if not fila_total:
        print("⚠️ [AVISO] Nenhum Ticker na planilha e nenhum garimpado.")
        return ""

    sp_tz = pytz.timezone('America/Sao_Paulo')
    data_atual = datetime.now(sp_tz).strftime("%d/%m %H:%M OK")
    batch_updates = []
    relatorio_telegram = []

    # Localiza a primeira linha 100% vazia para escrever os fundos novos
    proxima_linha_vazia = len(dados_planilha) + 1 

    for ticker in fila_total:
        try:
            # Preço em Tempo Real (YFinance)
            yf_info = yf.Ticker(f"{ticker}.SA").info
            preco = formatar_fii(yf_info.get('currentPrice') or yf_info.get('regularMarketPrice') or 0)

            # Extração do Dataframe
            f = df.loc[ticker] if ticker in df.index else {}

            setor = f.get('Segmento', 'N/D') if isinstance(f.get('Segmento'), str) else 'N/D'
            tipo = classificar_tipo(setor)
            pvp = f.get('P/VP', 0)
            dy = f.get('Dividend Yield', 0)
            vacancia = f.get('Vacância Média', 0)
            liquidez = f.get('Liquidez', 0)
            valor_mercado = f.get('Valor de Mercado', 0)

            # 🧮 Engenharia Reversa (Cálculos de Dados Ocultos)
            vpa = preco / pvp if pvp > 0 else 0
            numero_cotas = valor_mercado / preco if preco > 0 else 0
            media_div_mensal = (preco * dy) / 12
            lucro_12m = valor_mercado * dy 

            # Conectores vazios para a Etapa 3 (Fatos Relevantes)
            walt = "Pendente (Etapa 3)"
            alavancagem = "Pendente (Etapa 3)"

            # MAPEAMENTO EXATO DA SUA PLANILHA:
            # A: Ticker | B: Tipo | C: Setor | D: Preço | E: Nº cotas | F: P/VP | G: DY | H: Vacância | I: Prazo Médio (WALT) | J: Alavancagem (%) | K: liquidez | L: Valor de mercado | M: VPA | N: lucro 12m | O: div mensal pago | P: Data
            
            row_update_completo = [
                ticker, tipo, setor, preco, numero_cotas, pvp, dy, vacancia, 
                walt, alavancagem, liquidez, valor_mercado, vpa, lucro_12m, media_div_mensal, data_atual
            ]
            
            row_update_parcial = row_update_completo[1:] # Tira o Ticker para atualizar fundos que já existem

            if ticker in tickers_planilha:
                # O fundo já existe: Atualiza da Coluna B até P
                linha_idx = tickers_planilha.index(ticker) + 2
                batch_updates.append({'range': f'B{linha_idx}:P{linha_idx}', 'values': [row_update_parcial]})
            else:
                # O fundo foi garimpado hoje: Adiciona na linha em branco (Coluna A até P)
                batch_updates.append({'range': f'A{proxima_linha_vazia}:P{proxima_linha_vazia}', 'values': [row_update_completo]})
                proxima_linha_vazia += 1
                
                # Monta o alerta VIP no Telegram para o novo FII
                relatorio_telegram.append(f"🌟 *NOVO FII GARIMPADO:* {ticker}\n   🏢 {tipo} | R$ {preco} | P/VP: {pvp:.2f} | DY: {dy*100:.1f}%")

            print(f"   ✅ [OK] FII {ticker} processado.")

        except Exception as e:
            print(f"   ❌ [ERRO] Falha ao processar {ticker}: {e}")

    # Gravação Rápida e em Lote no Google Sheets
    if batch_updates:
        aba_fiis.batch_update(batch_updates, value_input_option='USER_ENTERED')
        print(f"💾 [FIIs] {len(batch_updates)} FIIs atualizados/inseridos na planilha.")

    # Retorna o texto formatado para o Telegram se o robô caçou algo
    if relatorio_telegram:
        msg = "🏢 *OPORTUNIDADES EM FIIs (Modo Caçador)* 🏢\n" + "\n".join(relatorio_telegram) + "\n\n"
        return msg

    return ""