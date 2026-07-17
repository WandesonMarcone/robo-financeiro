import os
import io  
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

class GoogleDriveManager:
    def __init__(self):
        client_id = os.environ.get('CLIENT_ID')
        client_secret = os.environ.get('CLIENT_SECRET')
        refresh_token = os.environ.get('REFRESH_TOKEN')
        self.root_folder_id = os.environ.get('DRIVE_ROOT_FOLDER_ID')

        if not all([client_id, client_secret, refresh_token]):
            print("⚠️ Faltam credenciais do Google Drive nas variáveis de ambiente!")

        self.creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            token_uri='https://oauth2.googleapis.com/token'
        )

        self.service = build('drive', 'v3', credentials=self.creds)

    def _obter_ou_criar_pasta(self, nome_pasta, parent_id=None):
        """Busca uma pasta por nome. Se não existir, cria automaticamente."""
        parent_id = parent_id or self.root_folder_id

        query = f"name = '{nome_pasta}' and mimeType = 'application/vnd.google-apps.folder' and '{parent_id}' in parents and trashed = false"
        results = self.service.files().list(q=query, fields="files(id)").execute()
        arquivos = results.get('files', [])

        if arquivos:
            return arquivos[0]['id']

        metadata = {
            'name': nome_pasta,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_id] if parent_id else []
        }
        pasta = self.service.files().create(body=metadata, fields='id').execute()
        return pasta.get('id')

    # ==========================================
    # UPLOADS OFICIAIS
    # ==========================================
    def upload_pdf_organizado(self, caminho_arquivo, nome_arquivo, ticker, mes_ref):
        try:
            print(f"☁️ Estruturando pastas: Fundos Imobiliários -> {ticker} -> {mes_ref}...")
            fiis_id = self._obter_ou_criar_pasta("Fundos Imobiliários")
            ticker_id = self._obter_ou_criar_pasta(ticker, parent_id=fiis_id)
            mes_id = self._obter_ou_criar_pasta(mes_ref, parent_id=ticker_id)

            file_metadata = {'name': nome_arquivo, 'parents': [mes_id]}
            media = MediaFileUpload(caminho_arquivo, mimetype='application/pdf', resumable=True)

            arquivo_upado = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webViewLink'
            ).execute()

            return arquivo_upado.get('webViewLink')

        except Exception as e:
            print(f"❌ Erro ao organizar pastas no Google Drive: {e}")
            return None

    # ==========================================
    # MOTOR "HUMAN-IN-THE-LOOP" (REVISÃO MANUAL)
    # ==========================================
    def upload_pdf_revisao(self, caminho_arquivo, nome_arquivo):
        """Salva o PDF temporariamente na pasta '⚠️ REVISÃO' e retorna o ID e Link"""
        try:
            print(f"🚧 Enviando {nome_arquivo} para a pasta de REVISÃO...")
            revisao_id = self._obter_ou_criar_pasta("⚠️ REVISÃO")

            file_metadata = {'name': nome_arquivo, 'parents': [revisao_id]}
            media = MediaFileUpload(caminho_arquivo, mimetype='application/pdf', resumable=True)

            arquivo_upado = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webViewLink'
            ).execute()

            # Retorna uma tupla com o ID (para mover depois) e o link (para você clicar)
            return arquivo_upado.get('id'), arquivo_upado.get('webViewLink')
        except Exception as e:
            print(f"❌ Erro ao enviar para REVISÃO: {e}")
            return None, None

    def mover_arquivo(self, file_id, ticker, mes_ref):
        """Arrasta um arquivo já existente do Limbo para a pasta oficial do Ticker"""
        try:
            print(f"📦 Movendo arquivo {file_id} para {ticker}/{mes_ref}...")
            
            # 1. Pega as pastas de destino do ativo
            fiis_id = self._obter_ou_criar_pasta("Fundos Imobiliários")
            ticker_id = self._obter_ou_criar_pasta(ticker, parent_id=fiis_id)
            mes_id = self._obter_ou_criar_pasta(mes_ref, parent_id=ticker_id)

            # 2. Descobre onde o arquivo está agora para poder tirar de lá
            file = self.service.files().get(fileId=file_id, fields='parents').execute()
            previous_parents = ",".join(file.get('parents'))

            # 3. Move o arquivo para a casa nova (adiciona o mes_id e remove a pasta de revisão)
            file_movido = self.service.files().update(
                fileId=file_id,
                addParents=mes_id,
                removeParents=previous_parents,
                fields='id, webViewLink'
            ).execute()

            print("✅ Movimentação concluída com sucesso!")
            return file_movido.get('webViewLink')
        except Exception as e:
            print(f"❌ Erro ao mover arquivo no Drive: {e}")
            return None

    def deletar_arquivo(self, file_id):
        """Apaga sumariamente o arquivo do Google Drive"""
        try:
            self.service.files().delete(fileId=file_id).execute()
            print(f"🗑️ Arquivo {file_id} apagado do Drive.")
            return True
        except Exception as e:
            print(f"❌ Erro ao deletar arquivo: {e}")
            return False

    # ==========================================
    # OUTROS UPLOADS
    # ==========================================
    def upload_imagem_logo(self, bytes_imagem, nome_arquivo, pasta_destino_id):
        try:
            file_metadata = {'name': nome_arquivo, 'parents': [pasta_destino_id]}
            media = MediaFileUpload(io.BytesIO(bytes_imagem), mimetype='image/png', resumable=True)

            arquivo = self.service.files().create(body=file_metadata, media_body=media, fields='id').execute()
            file_id = arquivo.get('id')
            
            self.service.permissions().create(fileId=file_id, body={'type': 'anyone', 'role': 'reader'}).execute()
            link = self.service.files().get(fileId=file_id, fields='webViewLink').execute()
            return link.get('webViewLink')
        except Exception as e:
            return None

    def upload_pdf(self, caminho_arquivo, nome_arquivo):
        print(f"☁️ Subindo {nome_arquivo} simples...")
        try:
            file_metadata = {
                'name': nome_arquivo,
                'parents': [self.root_folder_id] if self.root_folder_id else []
            }
            media = MediaFileUpload(caminho_arquivo, mimetype='application/pdf', resumable=True)
            arquivo = self.service.files().create(body=file_metadata, media_body=media, fields='id').execute()
            file_id = arquivo.get('id')
            self.service.permissions().create(fileId=file_id, body={'type': 'anyone', 'role': 'reader'}).execute()
            link_final = self.service.files().get(fileId=file_id, fields='webViewLink').execute()
            return link_final.get('webViewLink')
        except Exception as e:
            return None