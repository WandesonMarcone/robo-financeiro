import requests

def obter_dados_macro():
    try:
        # 1. Busca a Taxa Selic (Meta) no Banco Central (Série 432)
        url_selic = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados/ultimos/1?formato=json"
        resp_selic = requests.get(url_selic, timeout=5).json()
        selic = float(resp_selic[0]['valor'])
        data_selic = resp_selic[0]['data']

        # 2. Busca o IPCA Acumulado 12m no Banco Central (Série 13522)
        url_ipca = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.13522/dados/ultimos/1?formato=json"
        resp_ipca = requests.get(url_ipca, timeout=5).json()
        ipca = float(resp_ipca[0]['valor'])

        # 3. Busca o Dólar Comercial em Tempo Real (AwesomeAPI)
        url_dolar = "https://economia.awesomeapi.com.br/last/USD-BRL"
        resp_dolar = requests.get(url_dolar, timeout=5).json()
        dolar = float(resp_dolar['USDBRL']['bid'])
        variacao_dolar = float(resp_dolar['USDBRL']['pctChange'])

        # 4. Cálculo do Juro Real Atual (Selic - IPCA)
        juro_real = selic - ipca

        texto = "🌍 *PANORAMA MACROECONÔMICO BRASIL*\n\n"
        texto += f"🏛️ *Taxa Selic:* {selic:.2f}% a.a. _(Ref: {data_selic})_\n"
        texto += f"🛒 *IPCA (12m):* {ipca:.2f}%\n"
        texto += f"⚖️ *Juro Real (Aprox):* {juro_real:.2f}%\n\n"
        
        sinal_dolar = "+" if variacao_dolar > 0 else ""
        texto += f"💵 *Dólar Comercial:* R$ {dolar:.2f} ({sinal_dolar}{variacao_dolar}%)\n\n"
        
        texto += "_Dados extraídos via API do Banco Central do Brasil._"
        return texto

    except Exception as e:
        return f"❌ Erro ao buscar dados macroeconômicos: {e}"
