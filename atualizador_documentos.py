from fnet_scraper import FnetDownloader
from module.dropbox_manager import upload_para_dropbox # Agora importamos de verdade!

def rotina_de_atualizacao(id_do_relatorio, ticker):
    """Função mestre: Baixa da B3 e faz upload pro Dropbox"""
    # 1. Instancia o downloader da B3
    b3 = FnetDownloader()
    
    # 2. Baixa o PDF para a memória (Os seus 2701.26 KB!)
    pdf_bytes = b3.baixar_pdf(id_do_relatorio)
    
    # 3. Verifica se baixou e envia para a nuvem
    if pdf_bytes:
        # Você pode passar o tipo de documento e a data conforme quiser
        link_gerado = upload_para_dropbox(
            conteudo_pdf=pdf_bytes, 
            ticker=ticker, 
            tipo_doc="Relatorio_Gerencial", 
            data_str="Oficial"
        )
        return link_gerado
    else:
        print(f"⚠️ Falha ao baixar o documento do {ticker} da B3.")
        return None