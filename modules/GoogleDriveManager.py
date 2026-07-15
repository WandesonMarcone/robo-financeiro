import os
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

class GoogleDriveManager:
    def __init__(self):
        # Puxa as suas 3 chaves secretas lá do Render
        client_id = os.environ.get('CLIENT_ID')
        client_secret = os.environ.get('CLIENT_SECRET')
        refresh_token = os.environ.get('REFRESH_TOKEN')

        if not all([client_id, client_secret, refresh_token]):
            print("⚠️ Faltam credenciais do Google Drive nas variáveis de ambiente!")

        # Monta o "crachá" de acesso permanente
        self.creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            token_uri='https://oauth2.googleapis.com/token'
        )
        
        # Inicia o motor do Google Drive
        self.service = build('drive', 'v3', credentials=self.creds)

    def upload_pdf(self, caminho_arquivo, nome_arquivo):
        print(f"☁️ Subindo {nome_arquivo} para o Google Drive (100GB)...")
        try:
            # Prepara o arquivo
            file_metadata = {'name': nome_arquivo}
            media = MediaFileUpload(caminho_arquivo, mimetype='application/pdf', resumable=True)
            
            # Faz o upload
            arquivo = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()
            
            file_id = arquivo.get('id')
            
            # Muda a permissão do arquivo para "Qualquer um com o link pode ver"
            permissao = {
                'type': 'anyone',
                'role': 'reader'
            }
            self.service.permissions().create(
                fileId=file_id,
                body=permissao
            ).execute()
            
            # Pega o link final para você acessar
            link_final = self.service.files().get(
                fileId=file_id,
                fields='webViewLink'
            ).execute()
            
            print("✅ Upload concluído com sucesso!")
            return link_final.get('webViewLink')

        except Exception as e:
            print(f"❌ Erro ao fazer upload no Google Drive: {e}")
            return None
