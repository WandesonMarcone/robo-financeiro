import os
import requests
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

def salvar_pdf_e_gerar_link(url_origem, ticker, tipo_doc, data_str):
    """
    Baixa o arquivo da B3/CVM usando disfarce avançado (Sessão e Cookies) 
    e salva no Dropbox organizando em pastas.
    """
    dbx = autenticar_dropbox()
    if not dbx:
        return url_origem # Fallback

    try:
        # 1. CRIAR UMA SESSÃO HUMANA (Isso guarda os Cookies mágicos da B3)
        sessao = requests.Session()
        sessao.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
            'Referer': 'https://fnet.bmfbovespa.com.br/'
        })

        # 2. BATER NA PORTA DA FRENTE PRIMEIRO (Para a B3 nos dar o JSESSIONID)
        url_recepcao = "https://fnet.bmfbovespa.com.br/fnet/publico/pesquisarGerenciadorDocumentosCVM?tipoFundo=1"
        try:
            sessao.get(url_recepcao, timeout=15)
        except:
            pass # Se demorar, a gente ignora e tenta o download mesmo assim

        # 3. AGORA SIM, PEDIMOS O DOWNLOAD DO ARQUIVO
        print(f"⬇️ Baixando documento de {ticker}: {url_origem}")
        resposta = sessao.get(url_origem, stream=True, timeout=45)
        
        # A B3 às vezes retorna erro 500 mesmo com cookies se o arquivo for muito antigo. 
        # O nosso robô lida com isso.
        if resposta.status_code != 200:
            print(f"⚠️ B3 negou o download (HTTP {resposta.status_code}). Usando link original.")
            return url_origem

        # Para garantir que não estamos a baixar uma página de erro disfarçada
        if 'application/pdf' not in resposta.headers.get('Content-Type', '').lower():
            print("⚠️ O arquivo retornado não é um PDF válido. Usando link original.")
            return url_origem

        conteudo_pdf = resposta.content

        # 4. SALVAR NO DROPBOX
        nome_arquivo = f"{tipo_doc.replace(' ', '_')}_{data_str}.pdf"
        caminho_dropbox = f"/Terminal_Institucional/{ticker.upper()}/{nome_arquivo}"

        dbx.files_upload(conteudo_pdf, caminho_dropbox, mode=dropbox.files.WriteMode("overwrite"))

        # 5. GERAR O LINK PERMANENTE
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
            return url_origem

    except Exception as e:
        print(f"❌ Falha geral no gerenciador do Dropbox: {e}")
        return url_origem