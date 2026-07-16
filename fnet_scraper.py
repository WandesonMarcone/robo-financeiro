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
        except Exception:
            pass

    def baixar_pdf(self, id_documento):
        if not self.session.cookies:
            self.iniciar_sessao()
        params = {'id': id_documento}
        try:
            res = self.session.get(self.url_download, params=params, headers=self.headers, timeout=15)
            res.raise_for_status()
            if 'application/pdf' not in res.headers.get('Content-Type', ''):
                return None
            return res.content 
        except Exception:
            return None

    def capturar_tudo(self, data_inicio):
        """O ARRASTÃO GLOBAL: Traz todos os documentos, sem filtrar categoria"""
        if not self.session.cookies:
            self.iniciar_sessao()

        url_pesquisa = "https://fnet.bmfbovespa.com.br/fnet/publico/pesquisarGerenciadorDocumentosDados"
        documentos_gerais = []

        for start in range(0, 3000, 50):
            # Removemos o 'idCategoriaDocumento' para a B3 não bugar
            params = {
                'd': '1', 's': str(start), 'l': '50', 
                'tipoFundo': '1', 
                'dataInicial': data_inicio
            }

            try:
                res = self.session.get(url_pesquisa, params=params, headers=self.headers, timeout=15)
                data = res.json().get('data', [])
                
                if not data:
                    break 

                for item in data:
                    descricao_fundo = item.get('descricaoFundo', '').upper()
                    id_doc = item.get('id')
                    data_ref = item.get('dataReferencia', '').replace('/', '-')
                    
                    # A MÁGICA ATUALIZADA:
                    tipo_doc = item.get('tipoDocumento', '').strip().title()
                    if not tipo_doc:
                        tipo_doc = "Documento Nao Classificado"
                    
                    if id_doc:
                        documentos_gerais.append({
                            'id': str(id_doc),
                            'data_ref': data_ref,
                            'nome_fundo': descricao_fundo,
                            'tipo_doc': tipo_doc
                        })
                
                time.sleep(0.5) 
            except Exception as e:
                break
                
        return documentos_gerais