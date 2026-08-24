import os
from groq import Groq
from openai import OpenAI

class LLMManager:
    def __init__(self):
        # 1. Provedor Groq (Gemma 2, Mixtral, Llama 3.3)
        self.groq_key = os.environ.get("GROQ_API_KEY")
        self.groq_client = Groq(api_key=self.groq_key) if self.groq_key else None

        # 2. Provedor Genérico / GPT OSS / OpenAI / OpenRouter / Ollama
        # (Aceita qualquer servidor que siga o padrão da OpenAI)
        self.openai_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY", "ollama")
        self.openai_base_url = os.environ.get("OPENAI_BASE_URL") # Ex: https://openrouter.ai/api/v1 ou http://localhost:11434/v1

        if self.openai_key or self.openai_base_url:
            self.openai_client = OpenAI(
                api_key=self.openai_key,
                base_url=self.openai_base_url if self.openai_base_url else None
            )
        else:
            self.openai_client = None

    def analisar(self, prompt: str, sistema: str = "Você é um analista financeiro institucional sênior.") -> str:
        """
        Executa a análise testando uma fila de modelos e provedores configurados.
        """
        # Lista de tentativas ordenadas por prioridade: (Provedor, Modelo)
        fila_modelos = [
            # --- GROQ (Gratuito e Ultra-rápido) ---
            ("groq", os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")),
            ("groq", "gemma2-9b-it"),            # Gemma 2 da Google
            ("groq", "mixtral-8x7b-32768"),       # Mistral / Mixtral

            # --- OPENROUTER / GPT OSS / OPENAI / OLLAMA ---
            ("openai", "gpt-4o-mini"),
            ("openai", "deepseek/deepseek-r1"),   # Exemplo de GPT OSS no OpenRouter
        ]

        ultimo_erro = ""

        for provedor, modelo in fila_modelos:
            try:
                # Tentativa via GROQ
                if provedor == "groq" and self.groq_client:
                    response = self.groq_client.chat.completions.create(
                        messages=[
                            {"role": "system", "content": sistema},
                            {"role": "user", "content": prompt}
                        ],
                        model=modelo,
                        temperature=0.3
                    )
                    return response.choices[0].message.content

                # Tentativa via OPENAI / OPENROUTER / GPT OSS
                elif provedor == "openai" and self.openai_client:
                    response = self.openai_client.chat.completions.create(
                        messages=[
                            {"role": "system", "content": sistema},
                            {"role": "user", "content": prompt}
                        ],
                        model=modelo,
                        temperature=0.3
                    )
                    return response.choices[0].message.content

            except Exception as e:
                ultimo_erro = str(e)
                print(f"⚠️ Falha no modelo '{modelo}' ({provedor}): {ultimo_erro}. Tentando o próximo...")
                continue

        return f"❌ Erro crítico: Todos os modelos e provedores falharam. Último erro: {ultimo_erro}"

# Instância pronta para uso
llm = LLMManager()
