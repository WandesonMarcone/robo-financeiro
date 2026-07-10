import os
from groq import Groq

# Inicializa o cliente Groq
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

def analisar_fatos_com_ia(prompt):
    """Analisa fatos e documentos usando o motor Llama 3 do Groq."""
    try:
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
        return f"❌ Erro na análise Groq: {str(e)}"