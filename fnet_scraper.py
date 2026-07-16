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
        try:
            url_inicial = "https://fnet.bmfbovespa.com.br/fnet/publico/pesquisarGerenciadorDocumentosDados"
            self.session.get(url_inicial, headers=self.headers, timeout=10)
            print("✅ Sessão iniciada com a B3. Cookies capturados.")
        except Exception as e:
            print(f"⚠️ Erro ao iniciar sessão com a B3: {e}")

    def baixar_pdf(self, id_documento):
        if not self.session.cookies:
            self.iniciar_sessao()

        params = {'id': id_documento}

        try:
            # print(f"📥 Baixando documento ID: {id_documento}...") # Removido para limpar os logs
            resposta = self.session.get(self.url_download, params=params, headers=self.headers, timeout=15)
            resposta.raise_for_status()

            # A TRAVA MESTRA 1: Verifica se a B3 mandou um PDF ou um XML de erro
            content_type = resposta.headers.get('Content-Type', '')
            if 'application/pdf' not in content_type:
                print(f"❌ Falha: O arquivo ID {id_documento} não é um PDF. Tipo: {content_type}")
                return None

            print(f"✅ Sucesso! PDF {id_documento} baixado da B3.")
            return resposta.content 

        except requests.exceptions.RequestException as e:
            print(f"❌ Erro de conexão ao baixar o documento {id_documento}: {e}")
            return None

    def pesquisar_documentos(self, nome_pesquisa, data_inicio="01/01/2026", id_categoria=None):
        if not self.session.cookies:
            self.iniciar_sessao()

        url_pesquisa = "https://fnet.bmfbovespa.com.br/fnet/publico/pesquisarGerenciadorDocumentosDados"

        params = {
            'd': '1', 's': '0', 'l': '50', 
            'tipoFundo': '1', 
            'nomeEmissor': nome_pesquisa, 
            'dataInicial': data_inicio
        }

        if id_categoria:
            params['idCategoriaDocumento'] = id_categoria

        try:
            resposta = self.session.get(url_pesquisa, params=params, headers=self.headers, timeout=15)
            resposta.raise_for_status()

            dados_json = resposta.json()
            ids_encontrados = []

            # print(f"DEBUG: B3 retornou {len(dados_json.get('data', []))} itens para a busca [{nome_pesquisa}].")

            for item in dados_json.get('data', []):
                descricao_fundo = item.get('descricaoFundo', '').upper()
                termo_busca = nome_pesquisa.upper() 

                # A TRAVA MESTRA 2: Só aceita se a palavra-chave estiver dentro da descrição oficial
                if termo_busca not in descricao_fundo:
                    # Descomente o print abaixo caso queira ver o escudo descartando coisas
                    # print(f"🛡️ Descartando doc de: {descricao_fundo} (Procurando: {termo_busca})")
                    continue

                id_doc = item.get('id')
                data_ref = item.get('dataReferencia', '').replace('/', '-') 

                if id_doc:
                    ids_encontrados.append((str(id_doc), data_ref, str(id_categoria)))

            return ids_encontrados

        except Exception as e:
            print(f"❌ Erro ao pesquisar {nome_pesquisa} na categoria {id_categoria}: {e}")
            return []