import requests
import time

class FnetDownloader:
    def __init__(self):
        self.session = requests.Session()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
        self.url_download = "https://fnet.bmfbovespa.com.br/fnet/publico/downloadDocumento"

    def iniciar_sessao(self):
        try:
            url_inicial = "https://fnet.bmfbovespa.com.br/fnet/publico/pesquisarGerenciadorDocumentosDados"
            self.session.get(url_inicial, headers=self.headers, timeout=10)
        except Exception as e:
            print(f"⚠️ Erro ao iniciar sessão com a B3: {e}")

    def baixar_pdf(self, id_documento):
        if not self.session.cookies:
            self.iniciar_sessao()

        params = {'id': id_documento}
        try:
            resposta = self.session.get(self.url_download, params=params, headers=self.headers, timeout=15)
            resposta.raise_for_status()

            # Evita baixar arquivos XML mascarados
            content_type = resposta.headers.get('Content-Type', '')
            if 'application/pdf' not in content_type:
                return None

            return resposta.content 
        except Exception:
            return None

    def pesquisar_documentos(self, nome_pesquisa, data_inicio="01/01/2026", id_categoria=None):
        if not self.session.cookies:
            self.iniciar_sessao()

        url_pesquisa = "https://fnet.bmfbovespa.com.br/fnet/publico/pesquisarGerenciadorDocumentosDados"

        # Aqui usamos o ID numérico da categoria para evitar bugs da B3
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

            for item in dados_json.get('data', []):
                descricao_fundo = item.get('descricaoFundo', '').upper()
                termo_busca = nome_pesquisa.upper() 

                # MODO ESPIÃO: Se achou a palavra, imprime o nome oficial no log!
                if termo_busca in descricao_fundo:
                    print(f"🕵️ MODO ESPIÃO -> Nome oficial na B3: {descricao_fundo}")
                    
                    id_doc = item.get('id')
                    data_ref = item.get('dataReferencia', '').replace('/', '-') 
                    if id_doc:
                        ids_encontrados.append((str(id_doc), data_ref, str(id_categoria)))

            return ids_encontrados

        except Exception as e:
            print(f"❌ Erro ao pesquisar {nome_pesquisa}: {e}")
            return []