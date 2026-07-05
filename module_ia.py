import google.generativeai as genai
import os

def analisar_documento_cvm(ticker, tipo_ativo, texto_documento):
    chave_api = os.environ.get("GEMINI_API_KEY")
    
    if not chave_api:
        return "❌ ERRO: Chave da API do Gemini não encontrada."
        
    try:
        genai.configure(api_key=chave_api)
        model = genai.GenerativeModel('gemini-pro') 
        
        if tipo_ativo == "FII":
            prompt = f"""
            Atue como um Gestor de Fundos de Investimento Institucional. Analise este extrato de relatório do fundo {ticker}.
            Extraia e responda de forma direta:
            1. 🏢 **Composição e Inquilinos:** Quais são os principais imóveis? Quem são os maiores devedores/inquilinos e % de receita que representam?
            2. ⚠️ **Saúde e Vacância:** Qual a vacância física/financeira atual? Houve calotes ou renegociações?
            3. 🎯 **Veredito do Especialista:** Com base nestes dados, o fundo demonstra solidez (Oportunidade) ou está em deterioração (Risco de Falência/Queda de dividendos)? Justifique em 2 linhas.
            
            Texto do relatório: {texto_documento}
            """
        else:
            prompt = f"""
            Atue como um Analista de Risco Sênior. Analise este Fato Relevante/Documento da ação {ticker}.
            Extraia e responda de forma direta:
            1. 📰 **O Fato:** O que aconteceu exatamente?
            2. 💰 **Impacto Financeiro:** Como isso afeta o lucro futuro, DRE e pagamento de dividendos?
            3. 🎯 **Veredito do Especialista:** Com base nisso, o ativo está a gerar uma Janela de Oportunidade ou um Sinal Vermelho (Risco)? Justifique em 2 linhas.
            
            Texto do relatório: {texto_documento}
            """
            
        response = model.generate_content(prompt)
        return response.text
        
    except Exception as e:
        return f"❌ Erro ao consultar a IA: {e}"
