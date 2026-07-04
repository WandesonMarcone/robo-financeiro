import pandas as pd
from mercados import indicadores
from datetime import datetime

def formatar_macro(valor):
    """Garante que o valor numérico seja retornado corretamente e formatado"""
    try:
        return float(valor)
    except:
        return 0.0

def atualizar_macro(aba_macro):
    print("📈 Iniciando coleta de dados macroeconômicos...")
    try:
        # Funções com os nomes reais da biblioteca 'mercados'
        selic_atual = formatar_macro(indicadores.selic()) 
        ipca_atual = formatar_macro(indicadores.ipca())
        
        # A biblioteca original não tem dólar em 'indicadores'. 
        # Vamos deixar o espaço pronto com 0.0, ou você pode adicionar uma API depois
        dolar_atual = 0.0 

        data_atual = datetime.now().strftime("%d/%m/%Y")

        # Prepara a linha para salvar
        nova_linha = [data_atual, selic_atual, ipca_atual, dolar_atual]

        # Adiciona na planilha
        aba_macro.append_row(nova_linha)
        print(f"✅ [Macro] Selic: {selic_atual}% | IPCA: {ipca_atual}% salvos com sucesso!")

    except Exception as e:
        print(f"⚠️ [Macro] Erro ao buscar dados econômicos: {e}")