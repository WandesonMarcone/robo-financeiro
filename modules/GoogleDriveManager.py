import os
import io
from datetime import datetime
from io import BytesIO 
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

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

    def _limpar_e_extrair_ano_mes(self, mes_ref):
        """🛡️ Trava de segurança contra o erro da hora e tradutor de meses"""

        mapa_meses = {
            "01": "Janeiro", "1": "Janeiro",
            "02": "Fevereiro", "2": "Fevereiro",
            "03": "Março", "3": "Março",
            "04": "Abril", "4": "Abril",
            "05": "Maio", "5": "Maio",
            "06": "Junho", "6": "Junho",
            "07": "Julho", "7": "Julho",
            "08": "Agosto", "8": "Agosto",
            "09": "Setembro", "9": "Setembro",
            "10": "Outubro",
            "11": "Novembro",
            "12": "Dezembro"
        }

        try:
            mes_ref_limpo = str(mes_ref).strip().split(' ')[0] 

            if '-' in mes_ref_limpo:
                partes = mes_ref_limpo.split('-')
                ano = partes[0] if len(partes[0]) == 4 else partes[1]
                mes_num = partes[1] if len(partes[0]) == 4 else partes[0]
                mes_nome = mapa_meses.get(mes_num, mes_num)
                return ano, mes_nome

            ano_atual = datetime.now().strftime("%Y")
            mes_atual_num = datetime.now().strftime("%m")
            return ano_atual, mapa_meses.get(mes_atual_num, mes_atual_num)
        except:
            ano_atual = datetime.now().strftime("%Y")
            mes_atual_num = datetime.now().strftime("%m")
            return ano_atual, mapa_meses.get(mes_atual_num, mes_atual_num)

    # ==========================================
    # UPLOADS OFICIAIS COM HIERARQUIA PROFUNDA
    # ==========================================
    def upload_pdf_organizado(self, caminho_arquivo, nome_arquivo, ticker, mes_ref, tipo_ativo="FII"):
        try:
            ano, mes = self._limpar_e_extrair_ano_mes(mes_ref)

            doc_raiz_id = self._obter_ou_criar_pasta("Documentos", self.root_folder_id)
            pasta_tipo = "Ações" if str(tipo_ativo).upper() == "ACAO" else "Fundos Imobiliários"
            tipo_id = self._obter_ou_criar_pasta(pasta_tipo, parent_id=doc_raiz_id)
            ticker_id = self._obter_ou_criar_pasta(ticker, parent_id=tipo_id)
            ano_id = self._obter_ou_criar_pasta(ano, parent_id=ticker_id)
            mes_id = self._obter_ou_criar_pasta(mes, parent_id=ano_id)

            print(f"☁️ Estruturando Drive: Documentos -> {pasta_tipo} -> {ticker} -> {ano} -> {mes}")

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

            return arquivo_upado.get('id'), arquivo_upado.get('webViewLink')
        except Exception as e:
            print(f"❌ Erro ao enviar para REVISÃO: {e}")
            return None, None

    def mover_arquivo(self, file_id, ticker, mes_ref, tipo_ativo="FII"):
        """Arrasta um arquivo do Limbo para a pasta oficial (Blindado com nova hierarquia)"""
        try:
            ano, mes = self._limpar_e_extrair_ano_mes(mes_ref)
            
            doc_raiz_id = self._obter_ou_criar_pasta("Documentos", self.root_folder_id)
            pasta_tipo = "Ações" if str(tipo_ativo).upper() == "ACAO" else "Fundos Imobiliários"
            tipo_id = self._obter_ou_criar_pasta(pasta_tipo, parent_id=doc_raiz_id)
            ticker_id = self._obter_ou_criar_pasta(ticker, parent_id=tipo_id)
            ano_id = self._obter_ou_criar_pasta(ano, parent_id=ticker_id)
            mes_id = self._obter_ou_criar_pasta(mes, parent_id=ano_id)

            print(f"📦 Movendo arquivo {file_id} para Documentos/{pasta_tipo}/{ticker}/{ano}/{mes}...")

            file = self.service.files().get(fileId=file_id, fields='parents').execute()
            previous_parents = ",".join(file.get('parents', []))

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

    def mover_arquivo_da_revisao_por_id(self, file_id, ticker, mes_ref, novo_nome, tipo_ativo="FII"):
        try:
            ano, mes = self._limpar_e_extrair_ano_mes(mes_ref)

            doc_raiz_id = self._obter_ou_criar_pasta("Documentos", self.root_folder_id)
            pasta_tipo = "Ações" if str(tipo_ativo).upper() == "ACAO" else "Fundos Imobiliários"
            tipo_id = self._obter_ou_criar_pasta(pasta_tipo, parent_id=doc_raiz_id)
            pasta_ticker_id = self._obter_ou_criar_pasta(ticker, parent_id=tipo_id)
            pasta_ano_id = self._obter_ou_criar_pasta(ano, parent_id=pasta_ticker_id)
            pasta_mes_id = self._obter_ou_criar_pasta(mes, parent_id=pasta_ano_id)

            arquivo_atual = self.service.files().get(fileId=file_id, fields='parents').execute()
            pastas_antigas = ",".join(arquivo_atual.get('parents', []))

            self.service.files().update(
                fileId=file_id,
                addParents=pasta_mes_id,          
                removeParents=pastas_antigas,     
                fields='id, parents'
            ).execute()

            arquivo_renomeado = self.service.files().update(
                fileId=file_id,
                body={'name': novo_nome},
                fields='webViewLink'
            ).execute()

            print(f"✅ Arquivo {novo_nome} aprovado e movido com sucesso para a nova estrutura!")
            return arquivo_renomeado.get('webViewLink')

        except Exception as e:
            print(f"❌ Erro ao aprovar, mover e renomear no Drive: {e}")
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
    def salvar_logo_drive(self, ticker: str, conteudo_bytes: bytes) -> str:
        try:
            ticker_upper = ticker.upper().strip()
            nome_arquivo = f"{ticker_upper}.png"

            id_pasta_logos = self._obter_ou_criar_pasta("Logos", parent_id=self.root_folder_id)

            query = f"'{id_pasta_logos}' in parents and name = '{nome_arquivo}' and trashed = false"
            resultados = self.service.files().list(q=query, fields="files(id)").execute().get('files', [])

            if resultados:
                file_id = resultados[0]['id']
                return f"https://drive.google.com/uc?export=view&id={file_id}"

            media = MediaIoBaseUpload(BytesIO(conteudo_bytes), mimetype='image/png', resumable=True)
            file_metadata = {
                'name': nome_arquivo,
                'parents': [id_pasta_logos]
            }

            arquivo_salvo = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()

            file_id = arquivo_salvo.get('id')
            permission = {'type': 'anyone', 'role': 'reader'}
            self.service.permissions().create(fileId=file_id, body=permission).execute()

            return f"https://drive.google.com/uc?export=view&id={file_id}"

        except Exception as e:
            print(f"⚠️ Erro ao salvar logo do {ticker} no Drive: {e}")
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