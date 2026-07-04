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
    if any(x in s for x in ["FUNDO DE FUNDOS", "MISTO"]): return "FOF / Misto"
    return "Tijolo"

def atualizar_fiis(aba_fiis):
    print("🏢 [LOG FIIs] Iniciando motor de FIIs...")

    try:
        url = "https://www.fundamentus.com.br/fii_resultado.php"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        df = pd.read_html(io.StringIO(response.text), decimal=',', thousands='.')[0]
        df['Papel'] = df['Papel'].str.strip().str.upper()
        df = df.set_index('Papel')
    except Exception as e:
        print(f"❌ [ERRO FIIs] Falha no scraping base: {e}")
        return ""

    dados_planilha = aba_fiis.get_all_values()
    if len(dados_planilha) <= 1:
        print("⚠️ [AVISO] Nenhum Ticker encontrado na aba BD_FIIs.")
        return ""

    tickers_planilha = [row[0].strip().upper() for row in dados_planilha[1:] if row and row[0].strip()]

    sp_tz = pytz.timezone('America/Sao_Paulo')
    data_atual = datetime.now(sp_tz).strftime("%d/%m %H:%M OK")
    batch_updates = []
    relatorio_telegram = []

    for ticker in tickers_planilha:
        linha_idx = tickers_planilha.index(ticker) + 2
        try:
            yf_info = yf.Ticker(f"{ticker}.SA").info
            preco = formatar_fii(yf_info.get('currentPrice') or yf_info.get('regularMarketPrice') or 0)

            f = df.loc[ticker] if ticker in df.index else {}

            setor = f.get('Segmento', 'N/D')
            tipo = classificar_tipo(setor)
            pvp = formatar_fii(f.get('P/VP', 0))
            dy = formatar_fii(f.get('Dividend Yield', 0))
            vacancia = formatar_fii(f.get('Vacância Média', 0))
            liquidez = formatar_fii(f.get('Liquidez', 0))
            valor_mercado = formatar_fii(f.get('Valor de Mercado', 0))

            # Engenharia Reversa de Dados (Cálculos)
            vpa = preco / pvp if pvp > 0 else 0
            numero_cotas = valor_mercado / preco if preco > 0 else 0
            media_div_mensal = (preco * dy) / 12
            lucro_12m = valor_mercado * dy # Proxy do lucro distribuído no ano

            # Conectores para a Etapa 3
            walt = "Pendente (Etapa 3)"
            alavancagem = "Pendente (Etapa 3)"

            # A ORDEM EXATA DA SUA PLANILHA (Coluna B até P)
            row_update = [
                tipo,                       # B
                setor,                      # C
                preco,                      # D
                numero_cotas,               # E
                pvp,                        # F
                dy,                         # G
                vacancia,                   # H
                walt,                       # I
                alavancagem,                # J
                liquidez,                   # K
                valor_mercado,              # L
                vpa,                        # M
                lucro_12m,                  # N
                media_div_mensal,           # O
                data_atual                  # P
            ]

            batch_updates.append({'range': f'B{linha_idx}:P{linha_idx}', 'values': [row_update]})

            # Regra de Oportunidade
            if pvp > 0 and pvp <= 0.95 and dy >= 0.09:
                relatorio_telegram.append(f"• *{ticker}* ({tipo}): R$ {preco} | P/VP: {pvp:.2f} | DY: {dy*100:.1f}%")

            print(f"   ✅ [OK] FII {ticker} processado.")

        except Exception as e:
            print(f"   ❌ [ERRO] Falha ao processar {ticker}: {e}")

    if batch_updates:
        aba_fiis.batch_update(batch_updates, value_input_option='USER_ENTERED')
        print(f"💾 [FIIs] {len(batch_updates)} fundos atualizados.")

    if relatorio_telegram:
        msg = "🏢 *OPORTUNIDADES EM FIIs (Desconto)* 🏢\n" + "\n".join(relatorio_telegram) + "\n\n"
        return msg

    return ""