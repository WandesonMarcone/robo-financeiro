import requests
import yfinance as yf
from datetime import datetime
import pytz

def obter_selic():
    # Série 432: Meta Selic
    url = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados/ultimos/1?formato=json"
    res = requests.get(url, timeout=10)
    return float(res.json()[0]['valor'])

def obter_ipca_12m():
    # Série 13522: IPCA 12 meses
    url = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.13522/dados/ultimos/1?formato=json"
    res = requests.get(url, timeout=10)
    return float(res.json()[0]['valor'])

def obter_dolar():
    """Tenta o Yahoo Finance (Tempo Real). Se falhar, usa o Banco Central (PTAX)."""
    try:
        ticker = yf.Ticker("BRL=X")
        df = ticker.history(period="1d")
        return float(df['Close'].iloc[-1])
    except Exception as e:
        print(f"⚠️ [AVISO] Yahoo Finance falhou para o Dólar. A tentar o Banco Central... Erro: {e}")
        # Plano B: Banco Central do Brasil (Série 10813 - Dólar Venda)
        url = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.10813/dados/ultimos/1?formato=json"
        res = requests.get(url, timeout=10)
        return float(res.json()[0]['valor'])

def atualizar_macro(aba_macro):
    print("🔍 [LOG MACRO] Buscando dados económicos...")
    try:
        selic = obter_selic()
        ipca = obter_ipca_12m()
        dolar = obter_dolar()

        sp_tz = pytz.timezone('America/Sao_Paulo')
        data_hora_atual = datetime.now(sp_tz).strftime("%d/%m/%Y %H:%M")

        nova_linha = [data_hora_atual, selic, ipca, dolar]

        # Insere sempre na Linha 2 (empurra o histórico para baixo)
        aba_macro.insert_row(nova_linha, 2)
        print("✅ [LOG MACRO] Salvo na linha 2 da aba BD_Macro!")

        # Monta a mensagem para o Telegram
        msg = "🌍 *Panorama Económico*\n"
        msg += f"💵 Dólar: R$ {dolar:.2f}\n"
        msg += f"🏛️ Selic: {selic}%\n"
        msg += f"🛒 IPCA (12m): {ipca}%\n\n"
        
        return msg

    except Exception as e:
        print(f"❌ [ERRO MACRO]: {e}")
        return ""