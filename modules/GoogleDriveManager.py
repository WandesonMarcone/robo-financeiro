import os
import io
import logging
import re
from datetime import datetime
from io import BytesIO
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

logger = logging.getLogger("robo.drive")

_MIME_PASTA = "application/vnd.google-apps.folder"
_MIME_ATALHO = "application/vnd.google-apps.shortcut"
_PASTA_LOGOS_ACOES = "Ações"
_PASTA_LOGOS_FIIS = "FIIs"
_ALIAS_PASTA_FIIS = (
    "FIIs",
    "FII",
    "Fundos Imobiliários",
    "Fundos Imobiliarios",
)
_ALIAS_PASTA_ACOES = (
    "Ações",
    "Acoes",
)
_EXTENSOES_LOGO = (".png", ".jpg", ".jpeg", ".webp", ".gif")
_CAMPOS_ARQUIVO_LOGO = "files(id,name,mimeType,shortcutDetails)"
_LOGOS_FOLDER_PADRAO = "1CwnYl7lq5U49vVr-BZBNC737tfvyyhuW"


def _erro_arquivo_ausente(erro):
    """404/410 (ou notFound) do Drive: o arquivo ja nao existe."""
    status = getattr(erro, "status_code", None) or getattr(erro, "resp", None)
    if hasattr(status, "status"):
        status = status.status
    try:
        status = int(status)
    except (TypeError, ValueError):
        status = None
    if status in (404, 410):
        return True
    texto = str(erro or "").lower()
    return (
        "file not found" in texto
        or "notfound" in texto
        or "httperror 404" in texto
        or "httperror 410" in texto
    )


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
        """Salva o PDF temporariamente na pasta '⚠️ REVISÃO' (dentro da raiz 'Documentos')"""
        try:
            print(f"🚧 Enviando {nome_arquivo} para a pasta de REVISÃO...")
            
            # 1. Garante a existência da pasta raiz "Documentos"
            doc_raiz_id = self._obter_ou_criar_pasta("Documentos", self.root_folder_id)
            
            # 2. Cria ou localiza a pasta de REVISÃO dentro de "Documentos"
            revisao_id = self._obter_ou_criar_pasta("⚠️ REVISÃO", parent_id=doc_raiz_id)

            file_metadata = {'name': nome_arquivo, 'parents': [revisao_id]}
            media = MediaFileUpload(caminho_arquivo, mimetype='application/pdf', resumable=True)

            arquivo_upado = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webViewLink'
            ).execute()

            # Retorna uma tupla com o ID e o link
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
        """Apaga o arquivo do Google Drive. 404/410 conta como ja apagado."""
        if not file_id:
            return True
        try:
            self.service.files().delete(fileId=file_id).execute()
            print(f"🗑️ Arquivo {file_id} apagado do Drive.")
            return True
        except Exception as e:
            if _erro_arquivo_ausente(e):
                print(f"🗑️ Arquivo {file_id} ja nao existia no Drive.")
                return True
            print(f"❌ Erro ao deletar arquivo: {e}")
            return False

    def _id_pasta_logos(self):
        try:
            import config
            configurado = getattr(config, "DRIVE_LOGOS_FOLDER_ID", "") or ""
        except Exception:
            configurado = ""
        return (
            os.environ.get("DRIVE_LOGOS_FOLDER_ID") or configurado or _LOGOS_FOLDER_PADRAO
        ).strip()

    def _escapar_query(self, valor):
        return str(valor).replace("\\", "\\\\").replace("'", "\\'")

    def _listar_drive(self, query, fields=_CAMPOS_ARQUIVO_LOGO, page_size=10):
        params = {
            "q": query,
            "fields": fields,
            "pageSize": page_size,
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
        }
        try:
            return (
                self.service.files()
                .list(corpora="allDrives", **params)
                .execute()
                .get("files", [])
            )
        except Exception:
            logger.debug("Listagem allDrives falhou; tentando Drive pessoal", exc_info=True)
            return (
                self.service.files()
                .list(**params)
                .execute()
                .get("files", [])
            )

    def _resolver_item_logo(self, item, esperar_pasta=False):
        """Segue atalho ate a pasta ou arquivo real da logo."""
        atual = item or {}
        visitados = set()
        while atual.get("mimeType") == _MIME_ATALHO:
            destino = (atual.get("shortcutDetails") or {}).get("targetId")
            if not destino or destino in visitados:
                return None
            visitados.add(destino)
            atual = (
                self.service.files()
                .get(
                    fileId=destino,
                    fields="id,name,mimeType,shortcutDetails",
                    supportsAllDrives=True,
                )
                .execute()
            )
        if esperar_pasta:
            mime = atual.get("mimeType")
            if mime and mime != _MIME_PASTA:
                return None
            return atual.get("id")
        if not atual.get("id"):
            return None
        return atual

    def resolver_pasta_logos(self, folder_id=None):
        """Resolve atalho para a pasta real de Ícones B3, sem confundir com Dados Financeiros."""
        alvo = (folder_id or self._id_pasta_logos()).strip()
        if not alvo:
            return None
        meta = (
            self.service.files()
            .get(
                fileId=alvo,
                fields="id,name,mimeType,shortcutDetails",
                supportsAllDrives=True,
            )
            .execute()
        )
        if meta.get("mimeType") == _MIME_ATALHO:
            destino = (meta.get("shortcutDetails") or {}).get("targetId")
            if not destino:
                logger.warning("Atalho de logos sem destino")
                return None
            return self.resolver_pasta_logos(destino)
        if meta.get("mimeType") != _MIME_PASTA:
            logger.warning("Destino de logos nao e pasta")
            return None
        return {"id": meta.get("id"), "name": meta.get("name")}

    def _nome_subpasta_logo(self, tipo):
        return _PASTA_LOGOS_FIIS if str(tipo or "").lower().startswith("fii") else _PASTA_LOGOS_ACOES

    def _aliases_subpasta_logo(self, tipo):
        if str(tipo or "").lower().startswith("fii"):
            return _ALIAS_PASTA_FIIS
        return _ALIAS_PASTA_ACOES

    def _subpasta_logos(self, tipo, criar=False):
        raiz = self.resolver_pasta_logos()
        if not raiz:
            return None
        if raiz.get("id") and self.root_folder_id and raiz["id"] == self.root_folder_id:
            logger.warning("Pasta de logos coincide com DRIVE_ROOT_FOLDER_ID; recusando mistura")
            return None
        for nome in self._aliases_subpasta_logo(tipo):
            query = (
                f"name = '{self._escapar_query(nome)}' "
                f"and '{raiz['id']}' in parents and trashed = false"
            )
            for item in self._listar_drive(query):
                pasta_id = self._resolver_item_logo(item, esperar_pasta=True)
                if pasta_id:
                    return pasta_id
        if not criar:
            return None
        nome = self._nome_subpasta_logo(tipo)
        pasta = (
            self.service.files()
            .create(
                body={
                    "name": nome,
                    "mimeType": _MIME_PASTA,
                    "parents": [raiz["id"]],
                },
                fields="id",
                supportsAllDrives=True,
            )
            .execute()
        )
        return pasta.get("id")

    def _arquivo_logo_bate(self, nome, chave):
        texto = str(nome or "").strip()
        if not texto:
            return False
        base, ext = os.path.splitext(texto)
        raiz = re.sub(r"[^A-Z0-9]", "", base.upper())
        if not raiz.startswith(chave):
            return False
        if ext and ext.lower() not in _EXTENSOES_LOGO:
            return False
        return True

    def _buscar_logo_na_pasta(self, pasta, chave):
        for nome in (
            f"{chave}.png",
            f"{chave}.jpg",
            f"{chave}.jpeg",
            f"{chave}.webp",
            f"{chave}.gif",
            chave,
        ):
            query = (
                f"'{pasta}' in parents and name = '{self._escapar_query(nome)}' "
                f"and trashed = false"
            )
            for item in self._listar_drive(query):
                arquivo = self._resolver_item_logo(item)
                if arquivo:
                    return arquivo
        query = (
            f"'{pasta}' in parents and name contains '{self._escapar_query(chave)}' "
            f"and trashed = false"
        )
        for item in self._listar_drive(query, page_size=50):
            if not self._arquivo_logo_bate(item.get("name"), chave):
                continue
            arquivo = self._resolver_item_logo(item)
            if arquivo:
                return arquivo
        return None

    def buscar_logo_catalogo(self, ticker: str, tipo: str = ""):
        """Localiza a logo no catálogo Ícones B3/Ações|FIIs. Não cria pastas."""
        chave = str(ticker or "").strip().upper()
        if not chave:
            return None
        pasta = self._subpasta_logos(tipo, criar=False)
        if pasta:
            achado = self._buscar_logo_na_pasta(pasta, chave)
            if achado:
                return achado
        raiz = self.resolver_pasta_logos()
        if not raiz or not raiz.get("id"):
            return None
        if raiz.get("id") and self.root_folder_id and raiz["id"] == self.root_folder_id:
            return None
        return self._buscar_logo_na_pasta(raiz["id"], chave)

    def baixar_arquivo(self, file_id, max_bytes=None):
        from googleapiclient.http import MediaIoBaseDownload

        pedido = self.service.files().get_media(
            fileId=file_id, supportsAllDrives=True
        )
        buf = BytesIO()
        downloader = MediaIoBaseDownload(buf, pedido)
        concluido = False
        while not concluido:
            _, concluido = downloader.next_chunk()
            if max_bytes and buf.tell() > int(max_bytes):
                return None
        dados = buf.getvalue()
        if max_bytes and len(dados) > int(max_bytes):
            return None
        return dados

    def baixar_logo_catalogo(self, file_id: str):
        from googleapiclient.http import MediaIoBaseDownload

        pedido = self.service.files().get_media(
            fileId=file_id, supportsAllDrives=True
        )
        buf = BytesIO()
        downloader = MediaIoBaseDownload(buf, pedido)
        concluido = False
        while not concluido:
            _, concluido = downloader.next_chunk()
        return buf.getvalue()

    def salvar_logo_catalogo(self, ticker: str, conteudo_bytes: bytes, tipo: str = "", mime_type: str = "image/png"):
        """Grava logo nova em Ações/FIIs. Não sobrescreve e não torna pública."""
        chave = str(ticker or "").strip().upper()
        if not chave or not conteudo_bytes:
            return None
        existente = self.buscar_logo_catalogo(chave, tipo)
        if existente:
            return existente
        pasta = self._subpasta_logos(tipo, criar=True)
        if not pasta:
            return None
        extensao = ".png"
        mime = mime_type or "image/png"
        if mime == "image/jpeg":
            extensao = ".jpg"
        elif mime == "image/webp":
            extensao = ".webp"
        elif mime == "image/gif":
            extensao = ".gif"
        nome = f"{chave}{extensao}"
        media = MediaIoBaseUpload(BytesIO(conteudo_bytes), mimetype=mime, resumable=True)
        return (
            self.service.files()
            .create(
                body={"name": nome, "parents": [pasta]},
                media_body=media,
                fields="id,name,mimeType",
                supportsAllDrives=True,
            )
            .execute()
        )

    def salvar_logo_drive(self, ticker: str, conteudo_bytes: bytes, tipo: str = "") -> str:
        """Compatibilidade: grava no catálogo Ícones B3 sem ACL pública."""
        try:
            salvo = self.salvar_logo_catalogo(ticker, conteudo_bytes, tipo=tipo)
            return (salvo or {}).get("id")
        except Exception:
            logger.warning("Falha ao salvar logo de %s no Drive", ticker, exc_info=True)
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