import requests
import time

class FnetDownloader:
    def __init__(self):
        # Inicia a sessão que vai guardar os cookies magicamente
        self.session = requests.Session()
        
        # Disfarce perfeito de um navegador moderno (User-Agent)
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
        
        # URL base de onde saem os downloads do FNET
        self.url_download = "https://fnet.bmfbovespa.com.br/fnet/publico/downloadDocumento"

    def iniciar_sessao(self):
        """
        Faz uma requisição inicial apenas para receber os cookies da B3 (JSESSIONID)
        """
        try:
            url_inicial = "https://fnet.bmfbovespa.com.br/fnet/publico/pesquisarGerenciadorDocumentosDados"
            self.session.get(url_inicial, headers=self.headers, timeout=10)
            print("✅ Sessão iniciada com a B3. Cookies capturados.")
        except Exception as e:
            print(f"⚠️ Erro ao iniciar sessão com a B3: {e}")

    def baixar_pdf(self, id_documento):
        """
        Realiza o download do documento e verifica se é realmente um PDF.
        Retorna os bytes do arquivo ou None se falhar.
        """
        # Se a sessão não tiver cookies, inicia
        if not self.session.cookies:
            self.iniciar_sessao()

        params = {'id': id_documento}
        
        try:
            print(f"📥 Baixando documento ID: {id_documento}...")
            # Envia a requisição de download usando a sessão
            resposta = self.session.get(self.url_download, params=params, headers=self.headers, timeout=15)
            
            # 1. Verifica se a requisição HTTP deu sucesso (Código 200)
            resposta.raise_for_status()

            # 2. A TRAVA MESTRA: Verifica se a B3 mandou um PDF ou uma página de erro HTML
            content_type = resposta.headers.get('Content-Type', '')
            if 'application/pdf' not in content_type:
                print(f"❌ Falha: O arquivo retornado não é um PDF. Tipo recebido: {content_type}")
                return None
            
            print(f"✅ Sucesso! PDF {id_documento} baixado com sucesso.")
            return resposta.content # Retorna os bytes do PDF na memória

        except requests.exceptions.RequestException as e:
            print(f"❌ Erro de conexão ao baixar o documento {id_documento}: {e}")
            return None

    def pesquisar_documentos(self, ticker, data_inicio="01/01/2026", id_categoria=None):
        if not self.session.cookies:
            self.iniciar_sessao()

        url_pesquisa = "https://fnet.bmfbovespa.com.br/fnet/publico/pesquisarGerenciadorDocumentosDados"

        params = {
            'd': '1', 's': '0', 'l': '50', 
            'tipoFundo': '1', 
            'nomeEmissor': ticker,
            'dataInicial': data_inicio
        }
        
        # Só adiciona o filtro se você passar um ID específico
        if id_categoria:
            params['idCategoriaDocumento'] = id_categoria

        print(f"🔎 Pesquisando documentos para {ticker} (Data: {data_inicio})...")
        try:
            resposta = self.session.get(url_pesquisa, params=params, headers=self.headers, timeout=15)
            resposta.raise_for_status()

            dados_json = resposta.json()
            ids_encontrados = []

            for item in dados_json.get('data', []):
                id_doc = item.get('id')
                data_ref = item.get('dataReferencia', '').replace('/', '-') 
                
                # A B3 geralmente retorna o campo 'idTipoDocumento' ou 'idCategoriaDocumento'
                # Vamos pegar o ID da categoria para sabermos qual pasta criar no Drive
                id_cat = item.get('idCategoriaDocumento') 
                
                if id_doc:
                    # Agora retornamos 3 valores: ID do documento, Data, e o ID do Tipo (ex: 15)
                    ids_encontrados.append((str(id_doc), data_ref, str(id_cat)))

            print(f"✅ Encontrados {len(ids_encontrados)} documentos.")
            return ids_encontrados

        except Exception as e:
            print(f"❌ Erro ao pesquisar {ticker}: {e}")
            return []