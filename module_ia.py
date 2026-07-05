import google.generativeai as genai
import os

def analisar_fatos_com_ia(ticker):
    chave_api = os.environ.get("GEMINI_API_KEY")
    
    if not chave_api:
        return "❌ ERRO: Chave da API do Gemini não encontrada no servidor."
        
    try:
        genai.configure(api_key=chave_api)
        # Usamos o modelo flash por ser extremamente rápido para respostas no Telegram
        model = genai.GenerativeModel('gemini-1.5-flash') 
        
        prompt = f"""
        Você é um analista financeiro sênior de um Family Office.
        Faça um resumo direto e reto sobre os últimos fatos relevantes, relatórios gerenciais e notícias do ativo {ticker} (Brasil).
        
        Estruture a sua resposta EXATAMENTE assim:
        📰 *O que aconteceu recentemente?* (Resumo curto)
        ⚖️ *Impacto:* (É positivo, negativo ou neutro para a tese da empresa/fundo?)
        💰 *Dividendos/Payout:* (Houve algum impacto nos rendimentos?)
        """
        
        response = model.generate_content(prompt)
        return response.text
        
    except Exception as e:
        return f"❌ Erro ao consultar a IA: {e}"