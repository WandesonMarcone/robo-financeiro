from groq import Groq
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

def analisar_fatos_com_ia(prompt):
    chat_completion = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model="llama3-70b-8192"
    )
    return chat_completion.choices[0].message.content