import os
import io  # <-- CORRIGIDO: Adicionado import vital para processamento de bytes
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

class GoogleDriveManager:
    def __init__(self):
        # Puxa as suas 3 chaves secretas lá do Render
        client_id = os.environ.get('CLIENT_ID')
        client_secret = os.environ.get('CLIENT_SECRET')
        refresh_token = os.environ.get('REFRESH_TOKEN')
        # ID da pasta raiz do seu projeto no Drive (onde tudo será criado dentro)
        self.root_folder_id = os.environ.get('DRIVE_ROOT_FOLDER_ID')

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

    def _obter_ou_criar_pasta(self, nome_pasta, parent_id=None):
        """Busca uma pasta por nome. Se não existir, cria automaticamente."""
        parent_id = parent_id or self.root_folder_id
        
        # Query para buscar se a pasta já existe dentro da pasta mãe
        query = f"name = '{nome_pasta}' and mimeType = 'application/vnd.google-apps.folder' and '{parent_id}' in parents and trashed = false"
        results = self.service.files().list(q=query, fields="files(id)").execute()
        arquivos = results.get('files', [])

        if arquivos:
            return arquivos[0]['id']
        
        # Se não existe, cria
        metadata = {
            'name': nome_pasta,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_id] if parent_id else []
        }
        pasta = self.service.files().create(body=metadata, fields='id').execute()
        return pasta.get('id')

    def upload_pdf_organizado(self, caminho_arquivo, nome_arquivo, ticker, categoria):
        """
        Cria pastas dinamicamente (Ticker -> Categoria) e faz o upload do PDF.
        Retorna o link público do arquivo.
        """
        print(f"☁️ Iniciando fluxo de upload estruturado para {ticker} -> {categoria}...")
        try:
            # 1. Garante a pasta do Ticker (ex: XPML11)
            ticker_folder_id = self._obter_ou_criar_pasta(ticker)

            # 2. Garante a subpasta da Categoria (ex: Relatório Gerencial) dentro da pasta do Ticker
            category_folder_id = self._obter_ou_criar_pasta(categoria, parent_id=ticker_folder_id)

            # 3. Prepara o metadado do arquivo apontando para a pasta correta
            file_metadata = {
                'name': nome_arquivo,
                'parents': [category_folder_id]
            }
            media = MediaFileUpload(caminho_arquivo, mimetype='application/pdf', resumable=True)

            # 4. Faz o upload físico
            arquivo = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()

            file_id = arquivo.get('id')

            # 5. Torna o arquivo público ("Qualquer pessoa com o link pode ler")
            permissao = {
                'type': 'anyone',
                'role': 'reader'
            }
            self.service.permissions().create(fileId=file_id, body=permissao).execute()

            # 6. Pega o link de visualização
            link_final = self.service.files().get(fileId=file_id, fields='webViewLink').execute()
            
            print(f"✅ Upload de {nome_arquivo} concluído com sucesso!")
            return link_final.get('webViewLink')

        except Exception as e:
            print(f"❌ Erro ao fazer upload estruturado no Google Drive: {e}")
            return None

    def upload_imagem_logo(self, bytes_imagem, nome_arquivo, pasta_destino_id):
        """Salva uma imagem (bytes) no Drive e torna pública"""
        try:
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
        except Exception as e:
            print(f"❌ Erro ao fazer upload de imagem: {e}")
            return None

    def upload_pdf(self, caminho_arquivo, nome_arquivo):
        """Faz upload simples na raiz do projeto"""
        print(f"☁️ Subindo {nome_arquivo} simples...")
        try:
            file_metadata = {
                'name': nome_arquivo,
                'parents': [self.root_folder_id] if self.root_folder_id else []
            }
            media = MediaFileUpload(caminho_arquivo, mimetype='application/pdf', resumable=True)

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

            link_final = self.service.files().get(fileId=file_id, fields='webViewLink').execute()
            return link_final.get('webViewLink')
        except Exception as e:
            print(f"❌ Erro no upload simples: {e}")
            return None