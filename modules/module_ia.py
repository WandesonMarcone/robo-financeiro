import os
from groq import Groq
from openai import OpenAI

def analisar_fatos_com_ia(prompt: str) -> str:
    """
    Executa a análise testando uma cadeia modular de provedores e modelos (Groq -> OpenRouter/GPT OSS -> OpenAI).
    """
    # System prompt padrão
    system_prompt = "Você é um analista financeiro institucional sênior."

    # ------------------------------------------------------------------
    # 1. CONFIGURAÇÃO DOS CLIENTES DE IA
    # ------------------------------------------------------------------
    groq_key = os.environ.get("GROQ_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")

    groq_client = Groq(api_key=groq_key) if groq_key else None
    
    # Cliente para OpenAI Oficial
    openai_client = OpenAI(api_key=openai_key) if openai_key else None
    
    # Cliente para GPT OSS via OpenRouter (usa a SDK da OpenAI com URL alterada)
    openrouter_client = OpenAI(
        api_key=openrouter_key,
        base_url="https://openrouter.ai/api/v1"
    ) if openrouter_key else None

    # ------------------------------------------------------------------
    # 2. FILA DE PRIORIDADE DE PROVEDORES E MODELOS
    # Formato: (Identificador do Cliente, Nome do Modelo)
    # ------------------------------------------------------------------
    modelo_groq = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

    fila_modelos = [
        # --- NÍVEL 1: GROQ (Gratuito e Ultra-rápido) ---
        ("groq", modelo_groq),
        ("groq", "gemma2-9b-it"),
        ("groq", "mixtral-8x7b-32768"),

        # --- NÍVEL 2: GPT OSS / OPEN-SOURCE (via OpenRouter) ---
        ("openrouter", "deepseek/deepseek-r1"),               # Raciocínio avançado OSS
        ("openrouter", "meta-llama/llama-3.3-70b-instruct"),  # Llama 3.3 OSS
        ("openrouter", "qwen/qwen-2.5-72b-instruct"),         # Qwen OSS

        # --- NÍVEL 3: OPENAI OFICIAL ---
        ("openai", "gpt-4o-mini"),
        ("openai", "gpt-4o")
    ]

    ultimo_erro = ""

    # ------------------------------------------------------------------
    # 3. EXECUÇÃO DA TENTATIVA COM FALLBACK AUTOMÁTICO
    # ------------------------------------------------------------------
    for provedor, modelo in fila_modelos:
        try:
            # Rota Groq
            if provedor == "groq" and groq_client:
                response = groq_client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    model=modelo,
                    temperature=0.3
                )
                return response.choices[0].message.content

            # Rota GPT OSS (OpenRouter)
            elif provedor == "openrouter" and openrouter_client:
                response = openrouter_client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    model=modelo,
                    temperature=0.3
                )
                return response.choices[0].message.content

            # Rota OpenAI Oficial
            elif provedor == "openai" and openai_client:
                response = openai_client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    model=modelo,
                    temperature=0.3
                )
                return response.choices[0].message.content

        except Exception as e:
            ultimo_erro = f"Provedor '{provedor}' com modelo '{modelo}' falhou: {str(e)}"
            print(f"⚠️ {ultimo_erro}. Tentando próximo da fila...")
            continue

    # Se nenhum provedor respondeu ou se faltam chaves de API
    return f"❌ Erro crítico na IA (Nenhum modelo respondeu). Último erro: {ultimo_erro}"
