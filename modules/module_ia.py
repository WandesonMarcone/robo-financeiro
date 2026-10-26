import os
import json


def analisar_fatos_com_ia(prompt: str, system_prompt: str = "Você é um analista financeiro institucional sênior.") -> str:
    """
    Executa a análise testando uma cadeia modular de provedores e modelos (Groq -> OpenRouter -> OpenAI).
    """
    groq_key = os.environ.get("GROQ_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")

    groq_client = None
    openai_client = None
    openrouter_client = None
    if groq_key:
        try:
            from groq import Groq

            groq_client = Groq(api_key=groq_key)
        except Exception:
            groq_client = None
    if openai_key or openrouter_key:
        try:
            from openai import OpenAI
        except Exception:
            OpenAI = None
        if OpenAI and openai_key:
            openai_client = OpenAI(api_key=openai_key)
        if OpenAI and openrouter_key:
            openrouter_client = OpenAI(
                api_key=openrouter_key, base_url="https://openrouter.ai/api/v1"
            )

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

_TERMOS_RENDIMENTO = (
    "dividend yield",
    "dividend",
    "rendiment",
    "yield",
    " dy",
    "provento",
    "distribuicao",
    "distribuição",
    "r$/cota",
    "por cota",
)


def _data_doc_ia(doc):
    return getattr(doc, "data_publicacao", None) or getattr(doc, "id", 0) or 0


def _eh_tipo_fii(tipo):
    valor = getattr(tipo, "value", tipo)
    texto = str(valor or "").strip().lower()
    return texto.startswith("fii") or texto.endswith("fii")


def selecionar_docs_ia(docs, tipo=""):
    """Prioriza o ultimo Relatorio Gerencial do FII; senao os 5 mais recentes."""
    lista = list(docs or [])
    if not lista:
        return []
    lista = sorted(lista, key=_data_doc_ia, reverse=True)
    if _eh_tipo_fii(tipo):
        gerenciais = [
            d
            for d in lista
            if "gerencial" in str(getattr(d, "tipo_documento", "") or "").lower()
        ]
        escolhidos = []
        if gerenciais:
            escolhidos.append(gerenciais[0])
        for doc in lista:
            tipo_doc = str(getattr(doc, "tipo_documento", "") or "").lower()
            if "rendiment" in tipo_doc and doc not in escolhidos:
                escolhidos.append(doc)
                break
        if escolhidos:
            return escolhidos
    return lista[:5]


def _trecho_rendimento(texto, janela=500):
    """Recorte do gerencial em torno de DY/dividendo (tabelas costumam vir no fim)."""
    bruto = str(texto or "")
    if not bruto:
        return ""
    lower = bruto.lower()
    melhor = -1
    for termo in _TERMOS_RENDIMENTO:
        idx = lower.find(termo)
        if idx >= 0 and (melhor < 0 or idx < melhor):
            melhor = idx
    if melhor < 0:
        return ""
    ini = max(0, melhor - 80)
    fim = min(len(bruto), melhor + janela)
    return " ".join(bruto[ini:fim].split())


def montar_resumo_docs_ia(docs):
    partes = []
    for doc in docs or []:
        data = getattr(doc, "data_publicacao", None)
        data_str = data.strftime("%d/%m/%Y") if data else "Sem Data"
        texto = str(getattr(doc, "texto_extraido", None) or "")
        if texto:
            conteudo = texto[:3000] + ("..." if len(texto) > 3000 else "")
            trecho = _trecho_rendimento(texto)
            if trecho and trecho not in conteudo:
                conteudo = (
                    "Trecho de rendimento/dividendo:\n"
                    + trecho
                    + "\n\n"
                    + conteudo
                )
        else:
            conteudo = str(getattr(doc, "assunto", None) or "Sem informacoes detalhadas.")
        tipo_doc = getattr(doc, "tipo_documento", None) or "Documento"
        partes.append(f"--- {tipo_doc} ({data_str}) ---\n{conteudo}")
    return "\n\n".join(partes) if partes else "Nenhum documento detalhado no banco de dados para este ativo."


def construir_prompt_interativo(ticker: str, tipo: str, topico: str, resumo_docs: str, fatos=None) -> str:
    especie = "FII" if _eh_tipo_fii(tipo) else "acao"
    linhas_fatos = [str(item).strip() for item in (fatos or []) if str(item).strip()]
    bloco_fatos = "\n".join(f"- {item}" for item in linhas_fatos) or "- nenhum indicador estruturado"
    tarefas = {
        "resumo": (
            "Resumo objetivo. Se for FII, o primeiro bullet DEVE ser o rendimento "
            "(Dividend Yield e/ou dividendo por cota). Extraia do relatorio gerencial "
            "ou dos FATOS; nao invente."
        ),
        "proventos": (
            "Foque em rendimentos. Cite DY e valor por cota extraidos dos FATOS ou do "
            "relatorio gerencial. Se nao houver, diga que a distribuicao nao consta nas fontes."
        ),
        "dividendos": (
            "Foque na politica de dividendos. Cite DY se estiver nos FATOS ou nos docs. "
            "Nao invente valor."
        ),
        "visao": "Descreva o que o fundo faz e os ativos citados nos docs, sem inventar setor.",
        "riscos": "Liste riscos citados nas fontes. Sem inventar.",
        "negocios": "Descreva o modelo de negocios com base nas fontes.",
        "saude": "Resuma a saude financeira so com numeros presentes nas fontes.",
        "parecer": "Parecer curto com base nas fontes. Sem inventar numero.",
    }
    tarefa = tarefas.get(str(topico or "resumo"), tarefas["resumo"])
    regras = (
        "Nao invente numero, setor, inquilino ou imovel. "
        "Se DY/dividendo nao estiver nos FATOS nem nos docs, diga que nao consta. "
        "Maximo 4 bullets. Seja direto."
    )
    return (
        f"Ativo: {ticker} ({especie})\n"
        f"FATOS (planilha; so use se presentes):\n{bloco_fatos}\n\n"
        f"Docs:\n{resumo_docs}\n\n"
        f"Tarefa: {tarefa}\n{regras}"
    )


def _limpar_resumo_painel(texto):
    bruto = str(texto or "").strip()
    if not bruto or bruto.startswith("❌"):
        return ""
    bruto = bruto.replace("```", "").strip().strip('"').strip("'")
    linhas = [ln.strip() for ln in bruto.splitlines() if ln.strip()]
    bruto = " ".join(linhas)
    if not bruto:
        return ""
    partes = []
    atual = []
    for ch in bruto:
        atual.append(ch)
        if ch in ".!?":
            frase = "".join(atual).strip()
            if frase:
                partes.append(frase)
            atual = []
            if len(partes) >= 2:
                break
    if not partes:
        partes = [bruto]
    texto = " ".join(partes).strip()
    if len(texto) > 280:
        texto = texto[:277].rsplit(" ", 1)[0].strip() + "..."
    return texto


def gerar_resumo_painel(ticker: str, tipo: str, fatos) -> str:
    """1-2 frases so com os fatos recebidos. Vazio se nao houver fonte."""
    lista = [str(item).strip() for item in (fatos or []) if str(item).strip()]
    if not lista:
        return ""
    especie = "FII" if _eh_tipo_fii(tipo) else "acao"
    system_prompt = (
        "Voce resume ativos da B3 com base apenas nos fatos fornecidos. "
        "Nao invente setor, segmento, inquilino, imovel, numero ou opiniao. "
        "Se os fatos forem insuficientes, responda exatamente VAZIO."
    )
    prompt = (
        f"Ativo: {ticker} ({especie})\n"
        "Fatos:\n- "
        + "\n- ".join(lista)
        + "\n\nEscreva 1 ou 2 frases corridas, em portugues, descrevendo o que o ativo faz. "
        "Sem markdown, sem titulo, sem repetir o ticker, sem dizer que e um FII/acao de um setor "
        "a menos que isso esteja nos fatos. Nao use a palavra VAZIO se houver fato util."
    )
    bruto = analisar_fatos_com_ia(prompt, system_prompt=system_prompt)
    if str(bruto or "").strip().upper() == "VAZIO":
        return ""
    return _limpar_resumo_painel(bruto)

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