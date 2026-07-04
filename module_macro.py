import pandas as pd
from mercados import indicadores  # Importa a biblioteca que você adicionou
from datetime import datetime

def atualizar_macro(aba_macro):
    print("📈 Iniciando coleta de dados macroeconômicos...")
    try:
        # Usando a biblioteca 'mercados' (ajuste conforme os métodos exatos dela)
        selic = indicadores.get_selic_meta()  # Exemplo de método
        ipca = indicadores.get_ipca_acumulado()
        dolar = indicadores.get_dolar_comercial()
        
        data_atual = datetime.now().strftime("%d/%m/%Y")
        
        # Prepara a linha para salvar
        nova_linha = [data_atual, selic, ipca, dolar]
        
        # Adiciona na planilha (adiciona uma linha nova no final)
        aba_macro.append_row(nova_linha)
        print("✅ [Macro] Dados atualizados com sucesso!")
        
    except Exception as e:
        print(f"⚠️ [Macro] Erro ao buscar dados econômicos: {e}")
