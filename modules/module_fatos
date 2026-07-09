import os
import io
import requests
import PyPDF2
import google.generativeai as genai
from bs4 import BeautifulSoup
from datetime import datetime

# Configuração Segura do Gemini
API_KEY = os.environ.get("GEMINI_API_KEY")
if API_KEY:
    genai.configure(api_key=API_KEY)
    # Usando o modelo flash: mais rápido e gratuito
    modelo = genai.GenerativeModel('gemini-1.5-flash') 

def extrair_texto_pdf(url):
    """Baixa o PDF na memória (sem gastar HD) e extrai o texto."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=15)
        # Lê o PDF direto da memória RAM
        pdf_file = io.BytesIO(response.content)
        leitor = PyPDF2.PdfReader(pdf_file)
        texto_completo = ""
        # Lê as primeiras 5 páginas (para economizar tempo e focar no resumo)
        for i in range(min(5, len(leitor.pages))):
            texto_completo += leitor.pages[i].extract_text()
        return texto_completo
    except Exception as e:
        print(f"⚠️ Erro ao ler PDF: {e}")
        return ""

def analisar_com_gemini(texto_pdf, ticker):
    """Pede à Inteligência Artificial para ler o documento."""
    if not API_KEY or not texto_pdf.strip():
        return None
    
    prompt = f"""
    Você é um analista financeiro sênior. Leia o trecho deste relatório oficial do ativo {ticker}.
    
    Sua tarefa:
    1. Escreva um resumo direto e sem sensacionalismo (máximo de 3 tópicos curtos) sobre o que aconteceu.
    2. SE FOR UM FUNDO IMOBILIÁRIO (FII), procure rigorosamente por duas métricas: "Prazo Médio dos Contratos (WALT)" e "Alavancagem".
    
    Retorne EXATAMENTE neste formato e nada mais:
    RESUMO:
    - [Tópico 1]
    - [Tópico 2]
    - [Tópico 3]
    WALT: [Valor encontrado ou 'N/D']
    ALAVANCAGEM: [Valor encontrado ou 'N/D']
    """
    
    try:
        resposta = modelo.generate_content(prompt)
        return resposta.text
    except Exception as e:
        print(f"⚠️ Erro no Gemini: {e}")
        return None

def buscar_fatos_relevantes(aba_fatos, tickers_carteira):
    print("📰 [LOG FATOS] Monitorando CVM e B3...")
    
    # Exemplo simulado de link direto de PDF da CVM (Na prática, você varrerá o fr.php do Fundamentus)
    # Para o teste, vamos simular que o robô achou um relatório novo do MXRF11
    
    documentos_novos = [
        {"ticker": "MXRF11", "assunto": "Relatório Gerencial", "link": "LINK_DIRETO_DO_PDF_AQUI"}
    ]
    
    relatorio_telegram = []
    
    for doc in documentos_novos:
        # 1. Verifica se já lemos esta notícia antes (Anti-Repetição)
        historico = aba_fatos.col_values(4) # Supondo que a Coluna 4 é a do Link
        if doc['link'] in historico:
            continue # Já leu, ignora.
            
        print(f"   🔍 Analisando novo relatório de {doc['ticker']}...")
        
        # 2. Extrai e Analisa
        texto = extrair_texto_pdf(doc['link'])
        analise = analisar_com_gemini(texto, doc['ticker'])
        
        if analise:
            # 3. Monta a mensagem com o Link Direto (Economia de armazenamento)
            msg = f"📄 *{doc['ticker']} - {doc['assunto']}*\n"
            msg += f"{analise}\n\n"
            msg += f"🔗 [Ler PDF Original]({doc['link']})"
            relatorio_telegram.append(msg)
            
            # 4. Salva no Histórico para não repetir amanhã
            data_atual = datetime.now().strftime("%d/%m/%Y %H:%M")
            aba_fatos.append_row([data_atual, doc['ticker'], doc['assunto'], doc['link']])
            
            # Aqui, futuramente, faremos o "Update" do WALT e Alavancagem na aba BD_FIIs
            # baseando-se na resposta do Gemini.

    if relatorio_telegram:
        return "🧠 *Radar de Inteligência Artificial* 🧠\n\n" + "\n---\n".join(relatorio_telegram)
    
    return ""
