import fitz  # É a biblioteca PyMuPDF que você instalou!
import requests
import io

def extrair_texto_do_pdf(url_do_pdf):
    """Abre o PDF online na memória e extrai o texto bruto."""
    if not url_do_pdf or not str(url_do_pdf).startswith("http"):
        return None

    try:
        # Disfarça o nosso robô como se fosse um navegador comum para a B3 não nos bloquear
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        resposta = requests.get(url_do_pdf, headers=headers, timeout=15)
        resposta.raise_for_status()

        # Abre o PDF diretamente na memória RAM (Ultra-rápido)
        pdf_memoria = io.BytesIO(resposta.content)
        documento = fitz.open(stream=pdf_memoria, filetype="pdf")

        texto_completo = ""
        
        # Lê apenas as primeiras 12 páginas (Onde está o ouro: Vacância, DRE, Portfólio)
        # Isso evita que a IA estoure o limite lendo anexos inúteis no final
        for num_pagina in range(min(12, len(documento))):
            pagina = documento.load_page(num_pagina)
            texto_completo += pagina.get_text("text") + "\n"

        documento.close()

        # Limpeza básica do texto para economizar espaço
        texto_limpo = " ".join(texto_completo.split())
        
        # Corta no limite seguro da IA (~15.000 caracteres)
        return texto_limpo[:15000] 

    except Exception as e:
        print(f"⚠️ Erro ao extrair texto do PDF {url_do_pdf}: {e}")
        return None
