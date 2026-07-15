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

    def upload_imagem_logo(self, bytes_imagem, nome_arquivo, pasta_destino_id):
        """Salva uma imagem (bytes) no Drive e torna pública"""
        file_metadata = {
            'name': nome_arquivo,
            'parents': [pasta_destino_id]
        }
        media = MediaFileUpload(io.BytesIO(bytes_imagem), mimetype='image/png', resumable=True)
        
        arquivo = self.service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()
        
        file_id = arquivo.get('id')
        self.service.permissions().create(
            fileId=file_id,
            body={'type': 'anyone', 'role': 'reader'}
        ).execute()
        
        link = self.service.files().get(fileId=file_id, fields='webViewLink').execute()
        return link.get('webViewLink')

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
