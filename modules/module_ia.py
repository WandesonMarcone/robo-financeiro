import os
from groq import Groq

def analisar_fatos_com_ia(prompt):
    # Verificação crítica de segurança
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return "❌ Erro: Chave GROQ_API_KEY não encontrada no servidor."
    
    try:
        client = Groq(api_key=api_key)
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Você é um analista financeiro institucional sênior."},
                {"role": "user", "content": prompt}
            ],
            # 🔥 AQUI ESTÁ A CORREÇÃO: Usando o modelo novo e suportado pela Groq
            model="llama-3.3-70b-versatile",
            temperature=0.3,
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        return f"❌ Erro crítico na IA: {str(e)}"