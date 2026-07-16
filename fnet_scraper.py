import requests
import time

class FnetDownloader:
    def __init__(self):
        self.session = requests.Session()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }
        self.url_download = "https://fnet.bmfbovespa.com.br/fnet/publico/downloadDocumento"

    def iniciar_sessao(self):
        try:
            url_inicial = "https://fnet.bmfbovespa.com.br/fnet/publico/pesquisarGerenciadorDocumentosDados"
            self.session.get(url_inicial, headers=self.headers, timeout=10)
        except Exception as e:
            print(f"⚠️ Erro na sessão B3: {e}")

    def baixar_pdf(self, id_documento):
        if not self.session.cookies:
            self.iniciar_sessao()
        params = {'id': id_documento}
        try:
            resposta = self.session.get(self.url_download, params=params, headers=self.headers, timeout=15)
            resposta.raise_for_status()

            if 'application/pdf' not in resposta.headers.get('Content-Type', ''):
                return None # Ignora silenciosamente os XMLs da B3

            return resposta.content 
        except Exception:
            return None

    def pesquisar_documentos(self, cnpj, data_inicio="01/01/2026", id_categoria=None):
        if not self.session.cookies:
            self.iniciar_sessao()

        url_pesquisa = "https://fnet.bmfbovespa.com.br/fnet/publico/pesquisarGerenciadorDocumentosDados"

        params = {
            'd': '1', 's': '0', 'l': '50', 
            'tipoFundo': '1', 
            'nomeEmissor': cnpj, # O SEGREDO: A B3 aceita o CNPJ neste campo!
            'dataInicial': data_inicio
        }

        if id_categoria:
            params['idCategoriaDocumento'] = id_categoria

        try:
            resposta = self.session.get(url_pesquisa, params=params, headers=self.headers, timeout=15)
            resposta.raise_for_status()

            dados_json = resposta.json()
            ids_encontrados = []

            # Sem travas de texto. Se veio pelo CNPJ, é o documento certo.
            for item in dados_json.get('data', []):
                id_doc = item.get('id')
                data_ref = item.get('dataReferencia', '').replace('/', '-') 
                if id_doc:
                    ids_encontrados.append((str(id_doc), data_ref, str(id_categoria)))

            return ids_encontrados

        except Exception as e:
            print(f"❌ Erro ao pesquisar {cnpj}: {e}")
            return []