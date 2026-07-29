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

def construir_prompt_interativo(ticker: str, tipo: str, topico: str, resumo_docs: str) -> str:
    """Monta o prompt exato dependendo do botão que o usuário clicou."""
    
    # REGRA DE OURO PARA O TELEGRAM (Impede a IA de fazer textões)
    restricao_formato = (
        "\n\nREGRAS DE FORMATAÇÃO (OBRIGATÓRIO):\n"
        "1. Seja extremamente conciso e direto ao ponto.\n"
        "2. NÃO escreva parágrafos longos, introduções genéricas ou conclusões.\n"
        "3. Use no máximo 3 bullet points curtos (máximo de 2 linhas cada).\n"
        "4. Formate em Markdown limpo."
    )

    contexto = f"Ativo: {ticker}\nDocumentos recentes:\n{resumo_docs}\n\n"

    # Define a missão baseada no tipo e no botão clicado
    if tipo == "fii":
        if topico == "resumo":
            missao = "Faça um micro-resumo de 2 linhas sobre o que é este Fundo Imobiliário e seu foco principal de atuação."
        elif topico == "visao":
            missao = "Descreva a Visão Geral, o Segmento de atuação e o Modelo de Gestão deste fundo."
        elif topico == "proventos":
            missao = "Analise os Proventos, Rendimentos recentes e a consistência de distribuição deste fundo."
        elif topico == "riscos":
            missao = "Aponte os principais Fatores de Risco (vacância, alavancagem, calotes ou liquidez) baseados nos relatórios recentes."
        elif topico == "parecer":
            missao = "Dê um Parecer Executivo final e direto para um investidor de longo prazo focado em renda."
            
    else: # AÇÃO
        if topico == "resumo":
            missao = "Faça um micro-resumo de 2 linhas sobre a empresa e seu core business."
        elif topico == "negocios":
            missao = "Descreva o Modelo de Negócios, sua posição no mercado e vantagens competitivas."
        elif topico == "saude":
            missao = "Analise a Saúde Financeira: margens, nível de endividamento e geração de caixa."
        elif topico == "dividendos":
            missao = "Analise a Política de Dividendos e o histórico recente de proventos da empresa."
        elif topico == "parecer":
            missao = "Dê um Parecer Executivo final e direto para um investidor de longo prazo (Value Investing)."

    return f"Você é um analista institucional sênior.\n{contexto}Sua tarefa: {missao}{restricao_formato}"

