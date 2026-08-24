import fitz  # PyMuPDF
import pdfplumber
import requests
import io

def extrair_texto_do_pdf(url_do_pdf):
    """Abre o PDF online, lê TODAS as páginas úteis e extrai o texto bruto."""
    if not url_do_pdf or not str(url_do_pdf).startswith("http"):
        return None

    try:
        # Disfarça o nosso robô como se fosse um navegador comum
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        resposta = requests.get(url_do_pdf, headers=headers, timeout=20)
        resposta.raise_for_status()

        # Abre o PDF diretamente na memória RAM
        pdf_memoria = io.BytesIO(resposta.content)
        documento = fitz.open(stream=pdf_memoria, filetype="pdf")

        texto_completo = ""

        # LÊ TODAS AS PÁGINAS DO RELATÓRIO
        for num_pagina in range(len(documento)):
            pagina = documento.load_page(num_pagina)
            texto_pagina = pagina.get_text("text")

            # FILTRO INTELIGENTE: Pular páginas inúteis para economizar memória da IA
            texto_minusculo = texto_pagina.lower()
            if "glossário" in texto_minusculo or "disclaimer" in texto_minusculo or "aviso legal" in texto_minusculo:
                continue # Pula para a próxima página ignorando essa

            texto_completo += texto_pagina + "\n"

        documento.close()

        # Limpeza para evitar que a IA se confunda com muitos espaços em branco
        texto_limpo = " ".join(texto_completo.split())

        # Corta no limite de 120.000 caracteres (Equivale a um PDF de 40+ páginas)
        return texto_limpo[:120000]

    except Exception as e:
        print(f"⚠️ Erro ao extrair texto do PDF {url_do_pdf}: {e}")
        return None

def extrair_texto_com_paginas(url_do_pdf):
    """
    Baixa o PDF da B3/CVM em memória e extrai o texto, 
    inserindo marcadores invisíveis de qual página o texto pertence.
    """
    try:
        # Faz o download do PDF em tempo real sem precisar salvar no HD
        response = requests.get(url_do_pdf, stream=True)
        response.raise_for_status()
        arquivo_pdf = io.BytesIO(response.content)

        texto_completo = ""

        # Abre o PDF na memória e extrai página por página
        with pdfplumber.open(arquivo_pdf) as pdf:
            for i, pagina in enumerate(pdf.pages):
                texto_pagina = pagina.extract_text()

                if texto_pagina:
                    # O PULO DO GATO: Carimba o número da página antes do texto
                    texto_completo += f"\n\n--- [PÁGINA {i + 1}] ---\n\n"
                    texto_completo += texto_pagina

        return texto_completo

    except Exception as e:
        print(f"❌ Erro ao ler o PDF {url_do_pdf}: {e}")
        return None
