import json

from services import llm


def analisar_fatos_com_ia(prompt: str, system_prompt: str = "Você é um analista financeiro institucional sênior.") -> str:
    """
    Executa a análise testando uma cadeia modular de provedores e modelos (Groq -> OpenRouter -> OpenAI).

    Fase 7, Etapa 7.6: a chamada é delegada à camada única ``services.llm``,
    preservando a mesma cadeia, temperatura e o mesmo texto de erro do legado.
    """
    mensagens = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    conteudo, erro = llm.completar_chat(mensagens, temperature=0.1)
    if erro is None:
        return conteudo
    return f"❌ Erro crítico na IA. Último erro: {erro}"

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
