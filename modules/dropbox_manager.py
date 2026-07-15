import os
import dropbox
from dropbox.exceptions import ApiError

def autenticar_dropbox():
    """Cria a conexão blindada com o Dropbox usando o token infinito."""
    app_key = os.environ.get("DROPBOX_APP_KEY")
    app_secret = os.environ.get("DROPBOX_APP_SECRET")
    refresh_token = os.environ.get("DROPBOX_REFRESH_TOKEN")

    if not all([app_key, app_secret, refresh_token]):
        print("⚠️ Chaves do Dropbox não encontradas nas variáveis de ambiente.")
        return None

    try:
        # A biblioteca oficial faz a mágica de renovar o token sozinha em background
        dbx = dropbox.Dropbox(
            app_key=app_key,
            app_secret=app_secret,
            oauth2_refresh_token=refresh_token
        )
        return dbx
    except Exception as e:
        print(f"❌ Erro na autenticação do Dropbox: {e}")
        return None

def upload_para_dropbox(conteudo_pdf, ticker, tipo_doc, data_str):
    """
    Recebe os BYTES do PDF (baixados pela classe FnetDownloader) 
    e salva no Dropbox organizando em pastas, retornando o link direto.
    """
    dbx = autenticar_dropbox()
    if not dbx:
        return None # Falha na autenticação

    try:
        # 1. MONTAR O CAMINHO E NOME DO ARQUIVO
        nome_arquivo = f"{tipo_doc.replace(' ', '_')}_{data_str}.pdf"
        caminho_dropbox = f"/Terminal_Institucional/{ticker.upper()}/{nome_arquivo}"

        # 2. FAZER O UPLOAD DOS BYTES PARA A NUVEM
        dbx.files_upload(conteudo_pdf, caminho_dropbox, mode=dropbox.files.WriteMode("overwrite"))

        # 3. GERAR O LINK PERMANENTE (Raw = 1 para download/visualização direta)
        try:
            link = dbx.sharing_create_shared_link_with_settings(caminho_dropbox)
            url_final = link.url.replace("?dl=0", "?raw=1") 
            print(f"✅ Salvo no Dropbox com sucesso: {url_final}")
            return url_final

        except ApiError as e:
            if e.error.is_shared_link_already_exists():
                links = dbx.sharing_list_shared_links(path=caminho_dropbox, direct_only=True).links
                if links:
                    url_final = links[0].url.replace("?dl=0", "?raw=1")
                    print(f"✅ Arquivo já existia. Link recuperado: {url_final}")
                    return url_final
            print(f"⚠️ Erro ao gerar link compartilhado: {e}")
            return None

    except Exception as e:
        print(f"❌ Falha geral no gerenciador do Dropbox: {e}")
        return None