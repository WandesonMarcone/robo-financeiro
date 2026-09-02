"""Manutenção de compatibilidade do acesso a LLM — Fase 7, Etapa 7.6.

A auditoria 7.1 apontou esta classe como duplicação de ``modules/module_ia.py``
("``LLMManager`` com fila de modelos"). O método ``analisar`` passou a delegar
para a camada única ``services.llm``, preservando a mesma fila de modelos, a
mesma temperatura e o mesmo texto de erro do legado.
"""
from services import llm as camada_llm


class LLMManager:
    def analisar(self, prompt: str, sistema: str = "Você é um analista financeiro institucional sênior.") -> str:
        """
        Executa a análise testando uma fila de modelos e provedores configurados.
        """
        fila_modelos = [
            # --- GROQ (Gratuito e Ultra-rápido) ---
            ("groq", camada_llm.GROQ_MODEL or camada_llm.MODELO_GROQ_PADRAO),
            ("groq", "gemma2-9b-it"),            # Gemma 2 da Google
            ("groq", "mixtral-8x7b-32768"),       # Mistral / Mixtral

            # --- OPENROUTER / GPT OSS / OPENAI / OLLAMA ---
            ("openai", "gpt-4o-mini"),
            ("openai", "deepseek/deepseek-r1"),   # Exemplo de GPT OSS no OpenRouter
        ]

        mensagens = [
            {"role": "system", "content": sistema},
            {"role": "user", "content": prompt},
        ]
        conteudo, erro = camada_llm.completar_chat(mensagens, fila_modelos=fila_modelos, temperature=0.3)
        if erro is None:
            return conteudo
        return f"❌ Erro crítico: Todos os modelos e provedores falharam. Último erro: {erro}"


# Instância pronta para uso
llm = LLMManager()
