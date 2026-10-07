import os
import io
import requests
import PyPDF2
from bs4 import BeautifulSoup
from datetime import datetime
from groq import Groq

# Configuração da API do Groq
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

def extrair_texto_pdf(url):
    """Baixa o PDF na memória e extrai o texto."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=15)
        pdf_file = io.BytesIO(response.content)
        leitor = PyPDF2.PdfReader(pdf_file)
        texto_completo = ""
        for i in range(min(5, len(leitor.pages))):
            texto_completo += leitor.pages[i].extract_text() or ""
        return texto_completo
    except Exception as e:
        print(f"⚠️ Erro ao ler PDF: {e}")
        return ""

def analisar_com_groq(texto_pdf, ticker):
    """Lê o relatório oficial do ativo via LLaMA 3.3 na infraestrutura do Groq."""
    if not GROQ_API_KEY or not texto_pdf.strip():
        return None
    
    prompt = f"""
    Você é um analista financeiro sênior. Leia o trecho deste relatório oficial do ativo {ticker}.
    
    Sua tarefa:
    1. Escreva um resumo direto e sem sensacionalismo (máximo de 3 tópicos curtos) sobre o que aconteceu.
    2. SE FOR UM FUNDO IMOBILIÁRIO (FII), procure por duas métricas: "Prazo Médio dos Contratos (WALT)" e "Alavancagem".
    
    Retorne EXATAMENTE neste formato:
    RESUMO:
    - [Tópico 1]
    - [Tópico 2]
    - [Tópico 3]
    WALT: [Valor encontrado ou 'N/D']
    ALAVANCAGEM: [Valor encontrado ou 'N/D']
    """
    
    try:
        client = Groq(api_key=GROQ_API_KEY)
        chat = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
            temperature=0.3,
        )
        return chat.choices[0].message.content
    except Exception as e:
        print(f"⚠️ Erro no Groq ao analisar relatório: {e}")
        return None

def buscar_fatos_relevantes(aba_fatos, tickers_carteira):
    print("📰 [LOG FATOS] Monitorando CVM e B3...")
    
    documentos_novos = [
        {"ticker": "MXRF11", "assunto": "Relatório Gerencial", "link": "LINK_DIRETO_DO_PDF_AQUI"}
    ]
    
    relatorio_telegram = []
    
    for doc in documentos_novos:
        historico = aba_fatos.col_values(4)
        if doc['link'] in historico:
            continue
            
        print(f"   🔍 Analisando novo relatório de {doc['ticker']}...")
        
        texto = extrair_texto_pdf(doc['link'])
        analise = analisar_com_groq(texto, doc['ticker'])
        
        if analise:
            msg = f"📄 *{doc['ticker']} - {doc['assunto']}*\n"
            msg += f"{analise}\n\n"
            msg += f"🔗 [Ler PDF Original]({doc['link']})"
            relatorio_telegram.append(msg)
            
            data_atual = datetime.now().strftime("%d/%m/%Y %H:%M")
            aba_fatos.append_row([data_atual, doc['ticker'], doc['assunto'], doc['link']])

    if relatorio_telegram:
        return "🧠 *Radar de Inteligência Artificial (Groq)* 🧠\n\n" + "\n---\n".join(relatorio_telegram)
    
    return ""