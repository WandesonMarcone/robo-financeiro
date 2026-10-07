import os
import json
from groq import Groq
from openai import OpenAI

def analisar_fatos_com_ia(prompt: str, system_prompt: str = "Você é um analista financeiro institucional sênior.") -> str:
    """
    Executa a análise testando uma cadeia modular de provedores e modelos (Groq -> OpenRouter -> OpenAI).
    """
    groq_key = os.environ.get("GROQ_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")

    groq_client = Groq(api_key=groq_key) if groq_key else None
    openai_client = OpenAI(api_key=openai_key) if openai_key else None
    openrouter_client = OpenAI(api_key=openrouter_key, base_url="https://openrouter.ai/api/v1") if openrouter_key else None

    modelo_groq = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

    fila_modelos = [
        ("groq", modelo_groq),
        ("openrouter", "meta-llama/llama-3.3-70b-instruct"), 
        ("openai", "gpt-4o-mini")
    ]

    ultimo_erro = ""

    for provedor, modelo in fila_modelos:
        try:
            if provedor == "groq" and groq_client:
                response = groq_client.chat.completions.create(
                    messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
                    model=modelo, temperature=0.1 # Temperatura 0.1 para JSON mais preciso
                )
                return response.choices[0].message.content

            elif provedor == "openrouter" and openrouter_client:
                response = openrouter_client.chat.completions.create(
                    messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
                    model=modelo, temperature=0.1
                )
                return response.choices[0].message.content

            elif provedor == "openai" and openai_client:
                response = openai_client.chat.completions.create(
                    messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
                    model=modelo, temperature=0.1
                )
                return response.choices[0].message.content

        except Exception as e:
            ultimo_erro = f"Provedor '{provedor}' com modelo '{modelo}' falhou: {str(e)}"
            continue

    return f"❌ Erro crítico na IA. Último erro: {ultimo_erro}"

def construir_prompt_interativo(ticker: str, tipo: str, topico: str, resumo_docs: str) -> str:
    # ... (SEU CÓDIGO ORIGINAL SE MANTÉM AQUI) ...
    restricao_formato = "\n\nREGRAS DE FORMATAÇÃO: 1. Seja direto. 2. Máx 3 bullets."
    return f"Ativo: {ticker}\nDocs: {resumo_docs}\nTarefa: {topico}{restricao_formato}"

# --- NOVA FUNÇÃO PARA GERAR O JSON DA IMAGEM ---
def gerar_resumo_fii_para_imagem(ticker: str, texto_pdf: str):
    """Lê o relatório e devolve um JSON puro pronto para virar imagem."""
    
    prompt = f"""
    Analise o Relatório do fundo {ticker}. Extraia os dados e retorne EXCLUSIVAMENTE um JSON.
    NÃO use formatação markdown (como ```json).
    
    TEXTO:
    {texto_pdf}

    ESTRUTURA OBRIGATÓRIA:
    {{
        "manchete": "Resumo principal em até 6 palavras",
        "dividendos": "Resumo do DY ou centavos por cota",
        "vacancia": "Vacância física atual",
        "imoveis": ["Imóvel 1", "Imóvel 2"],
        "vies": "POSITIVO" // POSITIVO, NEGATIVO ou NEUTRO
    }}
    """
    
    # Obrigamos a IA a agir como uma API
    sistema_json = "Você é um servidor de dados. Retorne apenas JSON válido."
    resposta_bruta = analisar_fatos_com_ia(prompt, system_prompt=sistema_json)

    try:
        # Limpa possível sujeira da IA antes de converter para dicionário Python
        limpo = resposta_bruta.replace("```json", "").replace("```", "").strip()
        dados_json = json.loads(limpo)
        return dados_json
    except json.JSONDecodeError as e:
        print(f"❌ Falha ao decodificar JSON: {e}\nRetorno bruto: {resposta_bruta}")
        return None