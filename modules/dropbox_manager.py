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
    Baixa o arquivo da B3/CVM e salva no Dropbox organizando em pastas.
    Retorna o link público final do Dropbox.
    """
    dbx = autenticar_dropbox()
    if not dbx:
        return url_origem # Se o Dropbox falhar, devolve o link original da B3 para não quebrar o robô

    try:
        # 1. Faz o download do arquivo disfarçado de navegador
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://fnet.bmfbovespa.com.br/' # Ajuda a pular o bloqueio da B3
        }
        
        print(f"⬇️ Baixando documento de {ticker}: {url_origem}")
        resposta = requests.get(url_origem, headers=headers, stream=True, timeout=30)
        
        if resposta.status_code != 200:
            print(f"⚠️ Erro HTTP {resposta.status_code} ao baixar da B3.")
            return url_origem

        conteudo_pdf = resposta.content

        # 2. Constrói o caminho organizado dentro do Dropbox
        # Ex: /Terminal_Institucional/XPML11/Relatorio_Gerencial_2026-07-14.pdf
        nome_arquivo = f"{tipo_doc.replace(' ', '_')}_{data_str}.pdf"
        caminho_dropbox = f"/Terminal_Institucional/{ticker.upper()}/{nome_arquivo}"

        # 3. Faz o Upload
        dbx.files_upload(
            conteudo_pdf, 
            caminho_dropbox, 
            mode=dropbox.files.WriteMode("overwrite")
        )

        # 4. Gera o link público infinito
        try:
            link = dbx.sharing_create_shared_link_with_settings(caminho_dropbox)
            # Trocamos dl=0 por raw=1 para o PDF abrir direto na tela do Telegram/Navegador
            url_final = link.url.replace("?dl=0", "?raw=1") 
            print(f"✅ Salvo no Dropbox com sucesso: {url_final}")
            return url_final
            
        except ApiError as e:
            # Se o link já foi criado em uma execução anterior, nós o buscamos
            if e.error.is_shared_link_already_exists():
                links = dbx.sharing_list_shared_links(path=caminho_dropbox, direct_only=True).links
                if links:
                    url_final = links[0].url.replace("?dl=0", "?raw=1")
                    return url_final
            print(f"⚠️ Erro ao gerar link compartilhado: {e}")
            return url_origem

    except Exception as e:
        print(f"❌ Falha geral no gerenciador do Dropbox: {e}")
        return url_origem