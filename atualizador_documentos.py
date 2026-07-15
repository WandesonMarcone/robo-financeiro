# arquivo: atualizador_documentos.py

from fnet_scraper import FnetDownloader
from dropbox_manager import upload_para_dropbox # Ajuste para o nome real da sua função do Dropbox

def rotina_de_atualizacao(id_do_relatorio, ticker):
    """Função mestre que baixa da B3 e joga pro Dropbox"""
    # 1. Instancia o downloader da B3
    b3 = FnetDownloader()
    
    # 2. Baixa o PDF para a memória
    pdf_bytes = b3.baixar_pdf(id_do_relatorio)
    
    # 3. Se baixou com sucesso, envia para o Dropbox
    if pdf_bytes:
        # Define o nome da pasta e do arquivo no seu Dropbox
        caminho_no_dropbox = f"/Relatorios_FIIs/{ticker}_relatorio_gerencial.pdf"
        
        # Chama a sua função do Dropbox passando os bytes e o caminho
        link_dropbox = upload_para_dropbox(pdf_bytes, caminho_no_dropbox)
        
        print(f"🚀 Documento do {ticker} salvo no Dropbox!")
        return link_dropbox
    else:
        print(f"⚠️ Falha ao processar o documento do {ticker}.")
        return None

# ==========================================
# ÁREA DE TESTE (Roda só se você executar este arquivo direto)
# ==========================================
if __name__ == '__main__':
    # Vamos simular um teste real com um ID de documento válido da B3!
    # (Substitua "1184168" por um ID real que você saiba que existe hoje no FNET)
    id_teste = "1184168" 
    ticker_teste = "HGLG11"
    
    print(f"Iniciando teste de integração para {ticker_teste}...")
    link_gerado = rotina_de_atualizacao(id_teste, ticker_teste)
    
    if link_gerado:
        print(f"✅ Teste concluído com sucesso! Link: {link_gerado}")
