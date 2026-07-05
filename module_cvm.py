import os
import json
import io
import PyPDF2
from googleapiclient.discovery import build
from google.oauth2 import service_account
from googleapiclient.http import MediaIoBaseUpload

# O ID exato da sua pasta DadosFinanceiros
DRIVE_FOLDER_ID = "1Q-dkO4oSd6_9zmOeZmPX8nmuVWzdjHOq"

def autenticar_drive():
    google_creds = os.environ.get('GOOGLE_CREDS')
    if google_creds:
        creds_dict = json.loads(google_creds)
        creds = service_account.Credentials.from_service_account_info(
            creds_dict, scopes=['https://www.googleapis.com/auth/drive.file']
        )
        return build('drive', 'v3', credentials=creds)
    return None

def salvar_pdf_no_drive(nome_arquivo, pdf_bytes):
    """Salva um arquivo PDF diretamente na sua pasta do Google Drive"""
    try:
        drive_service = autenticar_drive()
        if not drive_service:
            return None, "Erro de autenticação com o Drive."

        file_metadata = {
            'name': nome_arquivo,
            'parents': [DRIVE_FOLDER_ID]
        }
        
        media = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype='application/pdf', resumable=True)
        
        arquivo = drive_service.files().create(
            body=file_metadata, media_body=media, fields='id, webViewLink'
        ).execute()
        
        return arquivo.get('webViewLink'), None
    except Exception as e:
        return None, str(e)

def extrair_texto_pdf(pdf_bytes):
    """Lê as páginas do PDF para enviar para a IA"""
    try:
        leitor = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
        texto = ""
        # Limita a 10 páginas para não sobrecarregar a memória e manter rapidez
        num_paginas = min(len(leitor.pages), 10) 
        for i in range(num_paginas):
            texto += leitor.pages[i].extract_text() + "\n"
        return texto
    except Exception as e:
        return f"Erro ao ler PDF: {str(e)}"