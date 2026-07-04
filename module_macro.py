import requests
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
    # URL corrigida com /json/ incluído
    url = "https://economia.awesomeapi.com.br/json/last/USD-BRL"
    res = requests.get(url, timeout=10)
    return float(res.json()['USDBRL']['bid'])

def atualizar_macro(aba_macro):
    print("🔍 [LOG MACRO] Buscando dados econômicos...")
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
        msg = "🌍 *Panorama Econômico*\n"
        msg += f"💵 Dólar: R$ {dolar:.2f}\n"
        msg += f"🏛️ Selic: {selic}%\n"
        msg += f"🛒 IPCA (12m): {ipca}%\n\n"
        
        return msg

    except Exception as e:
        print(f"❌ [ERRO MACRO]: {e}")
        return ""