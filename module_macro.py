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
    except:
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

        selic_planilha = selic / 100 
        ipca_planilha = ipca / 100
        dolar_planilha = float(round(dolar, 4))

        # --- LÓGICA DE ANTISPAM ---
        enviar_mensagem = True
        try:
            # Tenta ler a última linha gravada (Linha 2)
            ultima_linha = aba_macro.row_values(2)
            ultimo_selic = float(ultima_linha[1].replace(',', '.').replace('%', ''))
            ultimo_ipca = float(ultima_linha[2].replace(',', '.').replace('%', ''))
            ultimo_dolar = float(ultima_linha[3].replace(',', '.'))

            # Verifica se houve mudança real
            mudou_taxas = (selic_planilha != ultimo_selic) or (ipca_planilha != ultimo_ipca)
            mudou_dolar = abs(dolar_planilha - ultimo_dolar) >= 0.05 # Mudança de 5 centavos

            if not mudou_taxas and not mudou_dolar:
                enviar_mensagem = False
                print("⏸️ [LOG MACRO] Sem mudanças relevantes. Salvando em silêncio.")
        except:
            pass # Se der erro ao ler (ex: planilha vazia), manda a mensagem.

        # Salva na planilha convertendo o dólar para formato BR
        linha_salvar = [data_hora_atual, selic_planilha, ipca_planilha, str(dolar_planilha).replace('.', ',')]
        aba_macro.insert_row(linha_salvar, 2, value_input_option='USER_ENTERED')
        
        # Só retorna o texto se houver mudança
        if enviar_mensagem:
            msg = "🌍 *Atualização Econômica*\n"
            msg += f"💵 Dólar: R$ {dolar:.2f}\n"
            msg += f"🏛️ Selic: {selic}%\n"
            msg += f"🛒 IPCA: {ipca}%\n\n"
            return msg
        else:
            return ""

    except Exception as e:
        print(f"❌ [ERRO MACRO]: {e}")
        return ""