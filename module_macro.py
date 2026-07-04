import requests
from datetime import datetime

def obter_selic():
    # Série 432: Meta para a taxa Selic (Banco Central)
    url = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados/ultimos/1?formato=json"
    res = requests.get(url, timeout=10)
    return float(res.json()[0]['valor'])

def obter_ipca_12m():
    # Série 13522: IPCA - Acumulado em 12 meses (Banco Central)
    url = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.13522/dados/ultimos/1?formato=json"
    res = requests.get(url, timeout=10)
    return float(res.json()[0]['valor'])

def obter_dolar():
    # API Pública de Câmbio em Tempo Real
    url = "https://economia.awesomeapi.com.br/last/USD-BRL"
    res = requests.get(url, timeout=10)
    return float(res.json()['USDBRL']['bid'])

def atualizar_macro(aba_macro):
    print("\n" + "="*40)
    print("🔍 [LOG MACRO] INICIANDO MÓDULO ECONÔMICO")
    print("="*40)
    
    try:
        print("⏳ [LOG MACRO] Conectando ao Banco Central para buscar Selic...")
        selic = obter_selic()
        print(f"✔️ [LOG MACRO] Selic capturada com sucesso: {selic}%")

        print("⏳ [LOG MACRO] Conectando ao Banco Central para buscar IPCA (12m)...")
        ipca = obter_ipca_12m()
        print(f"✔️ [LOG MACRO] IPCA capturado com sucesso: {ipca}%")

        print("⏳ [LOG MACRO] Conectando a AwesomeAPI para buscar Dólar...")
        dolar = obter_dolar()
        print(f"✔️ [LOG MACRO] Dólar capturado com sucesso: R$ {dolar:.2f}")

        data_atual = datetime.now().strftime("%d/%m/%Y")
        nova_linha = [data_atual, selic, ipca, dolar]

        print("⏳ [LOG MACRO] Escrevendo dados na aba BD_Macro do Google Sheets...")
        aba_macro.append_row(nova_linha)
        
        print("✅ [SUCESSO] Módulo Macro finalizado e gravado na planilha!\n")

    except Exception as e:
        print(f"❌ [ERRO CRÍTICO MACRO] Falha na execução do módulo: {e}\n")