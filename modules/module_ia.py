import os
from groq import Groq

def analisar_fatos_com_ia(prompt):
    # Verificação crítica de segurança
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return "❌ Erro: Chave GROQ_API_KEY não encontrada no servidor (Verifique as Variáveis de Ambiente do Render)."
    
    try:
        client = Groq(api_key=api_key)
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Você é um analista financeiro institucional sênior."},
                {"role": "user", "content": prompt}
            ],
            model="llama3-70b-8192",
            temperature=0.3,
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        # Isso vai te mostrar o erro exato no chat se algo falhar
        return f"❌ Erro crítico na IA: {str(e)}"