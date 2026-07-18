import requests
import os
from googleapiclient.http import MediaIoBaseUpload
import io
import config

def obter_link_logo(ticker, tipo, drive_manager):
    """
    Motor isolado de busca e gestão de logos.
    Isolado do bot principal para evitar travamentos em chamadas de rede.
    """
    try:
        nome_arquivo = f"{ticker.upper()}.png"
        pasta_tipo_nome = "Fiis" if tipo == "fii" else "Ações"
        pasta_github = "fiis" if tipo == "fii" else "acoes"

        # 1. Tenta buscar no Google Drive (Cache de Imagens)
        id_pasta_logos = drive_manager._obter_ou_criar_pasta("Logos")
        id_pasta_final = drive_manager._obter_ou_criar_pasta(pasta_tipo_nome, parent_id=id_pasta_logos)

        query = f"name='{nome_arquivo}' and '{id_pasta_final}' in parents and trashed=false"
        resultados = drive_manager.service.files().list(q=query, fields="files(id, webViewLink)").execute().get('files', [])

        if resultados:
            link = resultados[0].get('webViewLink', '')
            return link.replace("view?usp=drivesdk", "uc?export=view") if link else ""

        # 2. Busca Externa (GitHub ou Logo.dev)
        github_url = f"https://raw.githubusercontent.com/WandesonMarcone/icones-bolsabr/main/{pasta_github}/{ticker.upper()}.png"
        resp = requests.get(github_url, timeout=10)

        if resp.status_code != 200:
            logo_dev_token = os.environ.get("LOGO_DEV_TOKEN")
            if logo_dev_token:
                logo_dev_url = f"https://img.logo.dev/ticker:{ticker.upper()}.SA?token={logo_dev_token}"
                resp = requests.get(logo_dev_url, timeout=10)

        # 3. Persistência (Salva nova logo no Drive)
        if resp.status_code == 200 and 'image' in resp.headers.get('Content-Type', '').lower():
            file_metadata = {'name': nome_arquivo, 'parents': [id_pasta_final]}
            media = MediaIoBaseUpload(io.BytesIO(resp.content), mimetype='image/png', resumable=True)
            arquivo_salvo = drive_manager.service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
            
            link = arquivo_salvo.get('webViewLink', '')
            return link.replace("view?usp=drivesdk", "uc?export=view") if link else ""

    except Exception as e:
        print(f"Erro ao processar logo de {ticker}: {e}")
    return ""