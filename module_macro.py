import requests
import yfinance as yf
from datetime import datetime
import pytz

def obter_selic():
    url = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados/ultimos/1?formato=json"
    res = requests.get(url, timeout=10)
    return float(res.json()[0]['valor'])

def obter_ipca_12m():
    url = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.13522/dados/ultimos/1?formato=json"
    res = requests.get(url, timeout=10)
    return float(res.json()[0]['valor'])

def obter_dolar():
    try:
        ticker = yf.Ticker("BRL=X")
        df = ticker.history(period="1d")
        return float(df['Close'].iloc[-1])
    except Exception as e:
        print(f"⚠️ [AVISO] Yahoo Finance falhou para o Dólar. Tentando Banco Central... Erro: {e}")
        url = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.10813/dados/ultimos/1?formato=json"
        res = requests.get(url, timeout=10)
        return float(res.json()[0]['valor'])

def atualizar_macro(aba_macro):
    print("🔍 [LOG MACRO] Buscando dados econômicos...")
    try:
        selic = obter_selic()
        ipca = obter_ipca_12m()
        dolar = obter_dolar()

        sp_tz = pytz.timezone('America/Sao_Paulo')
        data_hora_atual = datetime.now(sp_tz).strftime("%d/%m/%Y %H:%M")

        # TRATAMENTO DE DADOS PARA O GOOGLE SHEETS
        # Divide por 100 para o Sheets formatar % corretamente.
        selic_planilha = selic / 100 
        ipca_planilha = ipca / 100
        # Formata o dólar com vírgula para respeitar o idioma do Sheets
        dolar_planilha = str(round(dolar, 4)).replace('.', ',')

        nova_linha = [data_hora_atual, selic_planilha, ipca_planilha, dolar_planilha]

        # 'USER_ENTERED' avisa ao Sheets para aplicar a formatação visual correta
        aba_macro.insert_row(nova_linha, 2, value_input_option='USER_ENTERED')
        print("✅ [LOG MACRO] Salvo na linha 2 da aba BD_Macro com porcentagens corrigidas!")

        msg = "🌍 *Panorama Econômico*\n"
        msg += f"💵 1 Dólar: R$ {dolar:.2f}\n"
        msg += f"🏛️ Selic: {selic}%\n"
        msg += f"🛒 IPCA (12m): {ipca}%\n\n"
        
        return msg

    except Exception as e:
        print(f"❌ [ERRO MACRO]: {e}")
        return ""