import logging
import requests
from datetime import datetime
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from banco_dados import DadosFinanceirosFiis, DocumentosQualitativos, Ativo
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

class FiisFnetScraper:
    """Motor de captura de Informes e Relatórios Gerenciais via API do sistema FNET da B3/CVM."""
    
    def __init__(self, db_session: Session):
        self.session = db_session
        # Endpoint oficial (oculto) de onde a B3 puxa a tabela de FIIs
        self.base_url_fnet = "https://fnet.bmfbovespa.com.br/fnet/publico/pesquisarGerenciadorDocumentosDados"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json'
        }

    def atualizar_fiis(self, data_inicio: str = None) -> None:
        """Método principal orquestrador para FIIs."""
        logger.info(f"Iniciando raspagem FNET (FIIs)...")
        feed_fnet = self._buscar_feed_fnet(data_inicio)
        
        if not feed_fnet:
            logger.warning("Nenhum dado retornado do FNET.")
            return

        documentos = self._extrair_relatorios_gerenciais(feed_fnet)
        self._salvar_documentos(documentos)
        logger.info(f"Atualização concluída. Encontrados {len(documentos)} documentos estratégicos recentes.")

    def _buscar_feed_fnet(self, data_inicio: str = None) -> List[Dict[str, Any]]:
        """Faz a requisição com estratégia de RETRY automática."""
        params = {
            'd': 1, 's': 0, 'l': 50,
            'tipoFundo': 1, 'idCategoriaDocumento': 0,
            'idTipoDocumento': 0, 'idEspecieDocumento': 0
        }
        if data_inicio:
            params['dataInicial'] = data_inicio

        # CONFIGURAÇÃO DE RETRY (Blindagem)
        session = requests.Session()
        retry_strategy = Retry(
            total=3,                # Tenta 3 vezes
            backoff_factor=1,       # Espera 1s, 2s, 4s entre tentativas
            status_forcelist=[500, 502, 503, 504] # Só tenta de novo se o erro for de servidor
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)

        try:
            # Usa a session com retry
            response = session.get(self.base_url_fnet, headers=self.headers, params=params, timeout=60)
            
            if response.status_code == 200:
                dados = response.json()
                return dados.get('data', [])
            else:
                print(f"Erro no FNET: HTTP {response.status_code}")
                return []
        except Exception as e:
            print(f"Falha total ao conectar no FNET após tentativas: {e}")
            return []

    def _extrair_relatorios_gerenciais(self, feed: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filtra o feed procurando 'Relatório Gerencial' ou 'Fato Relevante' e constrói a URL oficial."""
        documentos_estruturados = []
        
        for item in feed:
            ticker = item.get('nomePregao', '').strip()
            categoria = item.get('descricaoCategoriaDocumento', '').upper()
            tipo_doc = item.get('descricaoTipoDocumento', '').upper()
            assunto = item.get('descricaoAssunto', '')
            id_doc = item.get('id')
            data_entrega_str = item.get('dataEntrega', '') # Ex: '11/07/2026 18:30'

            if not ticker or not id_doc:
                continue

            # Filtramos apenas os documentos vitais (Relatórios Gerenciais e Fatos Relevantes)
            if "GERENCIAL" in tipo_doc or "FATO RELEVANTE" in categoria or "FATO RELEVANTE" in tipo_doc:
                try:
                    data_publicacao = datetime.strptime(data_entrega_str.split(' ')[0], '%d/%m/%Y').date()
                except:
                    data_publicacao = datetime.now().date()

                # A MÁGICA: Esta URL pula o site da B3 e vai direto para a tela de impressão do PDF
                url_pdf = f"https://fnet.bmfbovespa.com.br/fnet/publico/exibirDocumento?id={id_doc}"

                documentos_estruturados.append({
                    'ticker_temporario': ticker, # Guardamos provisoriamente para achar o ID no banco depois
                    'data_publicacao': data_publicacao,
                    'tipo_documento': "Relatório Gerencial" if "GERENCIAL" in tipo_doc else "Fato Relevante",
                    'url_pdf': url_pdf,
                    'assunto': assunto[:250]
                })

        return documentos_estruturados

    def _salvar_documentos(self, documentos: List[Dict[str, Any]]) -> None:
        """Idempotência para PDFs: Relaciona o ticker com o banco e salva sem duplicar."""
        for doc in documentos:
            ticker_alvo = doc.pop('ticker_temporario')
            
            # Busca quem é este FII na nossa tabela 'ativos'
            ativo = self.session.query(Ativo).filter(Ativo.ticker == ticker_alvo).first()
            
            # Se você ainda não tem esse FII cadastrado na base, ele cadastra automaticamente!
            if not ativo:
                ativo = Ativo(ticker=ticker_alvo, cnpj="00.000.000/0000-00", tipo="FII")
                self.session.add(ativo)
                self.session.commit()
                
            doc['ativo_id'] = ativo.id

            try:
                novo_doc = DocumentosQualitativos(**doc)
                self.session.add(novo_doc)
                self.session.commit()
            except IntegrityError:
                # O banco avisou que este documento já foi guardado. Cancelamos a transação e seguimos.
                self.session.rollback()
                pass
