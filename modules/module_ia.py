import google.generativeai as genai
import os

def analisar_fatos_com_ia(resumo_prompt):
    """
    Função central de análise da IA. 
    Recebe o prompt construído pelo módulo CVM e retorna a análise do Gemini.
    """
    chave_api = os.environ.get("GEMINI_API_KEY")

    if not chave_api:
        return "❌ ERRO: Chave da API do Gemini não encontrada nas variáveis de ambiente."

    try:
        # Configuração da nova API do Gemini
        genai.configure(api_key=chave_api)
        
        # Modelo atualizado (gemini-1.5-pro é mais robusto para textos longos como PDFs)
        # Se preferir o modelo mais rápido e barato, pode trocar por 'gemini-1.5-flash'
        model = genai.GenerativeModel('gemini-1.5-pro-latest') 

        # A execução da IA
        response = model.generate_content(resumo_prompt)
        
        return response.text

    except Exception as e:
        return f"❌ Erro crítico ao consultar a IA (Gemini): {e}"