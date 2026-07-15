# arquivo: atualizador_documentos.py

from fnet_scraper import FnetDownloader
# Comentamos o Dropbox por enquanto para não dar erro
# from dropbox_manager import upload_para_dropbox 

def rotina_de_atualizacao(id_do_relatorio, ticker):
    """Função mestre que baixa da B3"""
    # 1. Instancia o downloader da B3
    b3 = FnetDownloader()
    
    # 2. Baixa o PDF para a memória
    pdf_bytes = b3.baixar_pdf(id_do_relatorio)
    
    # 3. Verifica se baixou com sucesso
    if pdf_bytes:
        tamanho = len(pdf_bytes) / 1024 # Calcula tamanho em KB
        print(f"🚀 Sucesso! Documento do {ticker} baixado. Tamanho: {tamanho:.2f} KB")
        # Retornamos uma mensagem de sucesso fictícia no lugar do link do Dropbox
        return f"Arquivo baixado na memória com sucesso ({tamanho:.2f} KB)!"
    else:
        print(f"⚠️ Falha ao processar o documento do {ticker}.")
        return None