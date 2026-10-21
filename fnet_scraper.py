import requests
import time


def _eh_pdf(conteudo):
    return bool(conteudo) and conteudo.lstrip().startswith(b"%PDF")


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

    def baixar_pdf(self, id_documento, max_bytes=None):
        if not self.session.cookies:
            self.iniciar_sessao()
        params = {'id': id_documento}
        try:
            res = self.session.get(
                self.url_download,
                params=params,
                headers=self.headers,
                timeout=15,
                stream=bool(max_bytes),
            )
            res.raise_for_status()
            tipo = (res.headers.get("Content-Type") or "").lower()
            if "html" in tipo or "json" in tipo:
                res.close()
                return None
            if max_bytes:
                limite = int(max_bytes)
                tamanho = res.headers.get("Content-Length")
                if tamanho and str(tamanho).isdigit() and int(tamanho) > limite:
                    res.close()
                    return None
                partes = []
                total = 0
                for pedaco in res.iter_content(chunk_size=8192):
                    if not pedaco:
                        continue
                    total += len(pedaco)
                    if total > limite:
                        res.close()
                        return None
                    partes.append(pedaco)
                conteudo = b"".join(partes)
                res.close()
                return conteudo if _eh_pdf(conteudo) else None
            conteudo = res.content
            return conteudo if _eh_pdf(conteudo) else None
        except Exception:
            return None

    def capturar_tudo(self, data_inicio):
        if not self.session.cookies:
            self.iniciar_sessao()

        url_pesquisa = "https://fnet.bmfbovespa.com.br/fnet/publico/pesquisarGerenciadorDocumentosDados"
        documentos_gerais = []

        # Limite reduzido para 2000 por categoria. Seguro e não dá ban na B3.
        for start in range(0, 5000, 50):
            params = {
                'd': '1', 's': str(start), 'l': '50', 
                'tipoFundo': '1', 
                'dataInicial': data_inicio,
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

                    # A ETIQUETA PERFEITA CONTINUA AQUI
                    tipo_doc = item.get('tipoDocumento', 'Documento Sem Tipo').strip().title()

                    if id_doc:
                        documentos_gerais.append({
                            'id': str(id_doc),
                            'data_ref': data_ref,
                            'nome_fundo': descricao_fundo,
                            'tipo_doc': tipo_doc
                        })

                time.sleep(1.5) # Pausa maior (1.5s) para o Firewall da B3 não nos pegar
            except Exception as e:
                break

        return documentos_gerais